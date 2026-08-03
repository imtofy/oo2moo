"""Baut echte Moodle-Buch-Aktivitäten (mod_book) aus OLAT-cp-Bausteinen
(Content Package / IMS-CP).

Ein cp-CourseNode referenziert sein IMS-CP-Paket über den moduleConfiguration-
Entry 'repoSoftkey', aufgelöst über manifest.resolve_repo_package() – siehe
dort für den 'export/<ident>/'-Mechanismus (identisch für QTI-Testpakete,
siehe qti/qti_quiz_builder.py).

imsmanifest.xml organisiert die Seiten hierarchisch als <item>-Baum
(<organization><item>...<item>(verschachtelt)</item></item></organization>),
jedes <item> referenziert per identifierref eine <resource> mit href auf eine
HTML-Datei. Moodles Buchformat (mod_book) kennt nur EINE Verschachtelungs-
ebene (subchapter 0/1) – oberste Items werden Kapitel, alle tiefer
verschachtelten Items werden (wie bei MAX_SECTION_DEPTH bei Kursabschnitten)
auf die eine unterstützte Unterkapitel-Ebene abgeflacht. Nur die ERSTE
<organization> wird verwendet (IMS-CP erlaubt mehrere, ein zweiter Baum
wäre eine alternative Gliederung derselben Seiten, keine weiteren Kapitel).
"""

import html as html_lib
import posixpath
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple, TypedDict

from config import STANDALONE_CP_IDENT
from .file_manager import activity_title, escape_xml_text, FileAreaNames
from .html_cleaner import sanitize_for_moodle
from config import EMPTY_BOOK_WARNING


class BookActivityResult(TypedDict):
    """Rückgabeform von build_book_activity() bei Erfolg – als TypedDict
    statt eines nackten Dict, damit main.py beim Zugriff auf die einzelnen
    Schlüssel (book_result["book_xml"] etc.) keine falschen None-Typwarnungen
    bekommt."""
    book_xml: str
    file_ids: List[int]
    removed_links: List[Dict]


def _parse_manifest_items(manifest_bytes: bytes) -> List[Dict]:
    """Parst imsmanifest.xml's <organization>-Item-Baum (nur die erste
    Organisation, siehe Moduldocstring) zu einer flachen Liste
    [{'title', 'href', 'subchapter'}] in Dokumentreihenfolge. Oberste
    <item>s werden zu Kapiteln (subchapter=0), alle Kind-Items (egal wie
    tief verschachtelt) zu Unterkapiteln (subchapter=1) – Moodle kennt nur
    eine Verschachtelungsebene. Items ohne auflösbare Resource behalten
    ihren Titel als leeres Kapitel, statt die Gliederung zu verlieren."""
    root = ET.fromstring(manifest_bytes)
    for elem in root.iter():
        if '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]

    resources = {}
    for res in root.iter('resource'):
        identifier = res.get('identifier')
        href = res.get('href')
        if identifier and href:
            resources[identifier] = href

    pages = []

    def _walk(item_elem, is_top_level):
        """Wandert rekursiv durch den <item>-Baum und flacht alles unterhalb
        der obersten Ebene zu subchapter=1 ab."""
        title_elem = item_elem.find('title')
        title = title_elem.text.strip() if title_elem is not None and title_elem.text else 'Kapitel'
        identifierref = item_elem.get('identifierref')
        resolved_href = resources.get(identifierref) if identifierref else None
        pages.append({'title': title, 'href': resolved_href, 'subchapter': 0 if is_top_level else 1})
        for child in item_elem.findall('item'):
            _walk(child, is_top_level=False)

    orgs = root.find('organizations')
    if orgs is not None:
        first_org = orgs.find('organization')
        if first_org is not None:
            for item in first_org.findall('item'):
                _walk(item, is_top_level=True)

    return pages


def _find_by_basename(vfs: Dict[str, bytes], name: str,
                      base_href: Optional[str] = None) -> Optional[bytes]:
    """Sucht eine Datei im Paket-VFS: erst exakter Pfad, dann relativ zur
    referenzierenden Seite (base_href), zuletzt irgendeine Datei mit diesem
    Basisnamen – IMS-CP-Pakete referenzieren Dateien mal relativ zur
    HTML-Seite, mal nur als blanken Dateinamen.

    Die Auflösung relativ zu base_href ist wichtig, wenn dieselbe
    Bildbenennung in mehreren Kapitel-Ordnern vorkommt: ohne sie träfe der
    Basisnamen-Zweig immer dieselbe erste Datei, und beide Kapitel zeigten
    dasselbe Bild."""
    if name in vfs:
        return vfs[name]
    if base_href and '/' in base_href:
        candidate = posixpath.normpath(posixpath.join(posixpath.dirname(base_href), name))
        if candidate in vfs:
            return vfs[candidate]
    basename = name.split('/')[-1]
    for path, data in vfs.items():
        if path.split('/')[-1] == basename:
            return data
    return None


def find_standalone_cp_title(vfs: Dict[str, bytes]) -> Optional[str]:
    """Prüft, ob ein VFS ein eigenständig exportiertes IMS-Content-Package ist
    (OLAT-cp-Baustein ohne umgebenden Kurs) und liefert dessen Titel.

    main.py ruft das NUR auf, wenn parse_olat_export() keine Kursknoten
    gefunden hat und auch qti_pipeline.find_standalone_test_title() nichts
    gefunden hat – Titel gefunden → Mini-Kurs-Fallback, siehe
    config.STANDALONE_CP_IDENT. Nur ein imsmanifest.xml DIREKT im Wurzel-ZIP
    zählt – eines unter 'export/<ident>/' gehört zu einem normalen
    cp-Baustein innerhalb eines echten Kurses."""
    manifest_bytes = vfs.get('imsmanifest.xml')
    if manifest_bytes is None:
        return None
    try:
        root = ET.fromstring(manifest_bytes)
    except ET.ParseError:
        return None
    for elem in root.iter():
        if '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]
    org = root.find('.//organization')
    if org is None:
        return None
    title_elem = org.find('title')
    if title_elem is not None and title_elem.text and title_elem.text.strip():
        return title_elem.text.strip()
    return None


def _process_page(href: Optional[str], sub_vfs: Dict[str, bytes], file_mgr, context_id: int,
                  chapter_id: int, now: int,
                  link_map: Optional[Dict]) -> Tuple[str, List[int], List[Dict]]:
    """Lädt eine CP-HTML-Seite, bereinigt sie für Moodle und registriert
    referenzierte lokale Bilder/Dateien als Buch-Kapitel-Dateien
    (component='mod_book', filearea='chapter', itemid=chapter_id – Moodles
    Konvention, jedes Kapitel hat seinen eigenen Dateibereich). link_map
    löst kursinterne gotonode-Verweise auf, genau wie bei jedem anderen
    Bausteintyp (siehe node_processor.build_node_content).

    Gibt (bereinigtes HTML, File-IDs, entfernte Links) zurück."""
    if not href:
        return "", [], []

    html_bytes = _find_by_basename(sub_vfs, href)
    if html_bytes is None:
        print(f"[!] CP-Seite '{href}' nicht im Paket gefunden.")
        return "", [], []

    raw_html = html_bytes.decode('utf-8-sig', errors='ignore')
    clean_html, asset_paths, removed_links = sanitize_for_moodle(raw_html, link_map)

    file_ids = []
    if file_mgr is not None and asset_paths:
        # Jeder (contextid, component, filearea, itemid)-Dateibereich braucht
        # seinen eigenen Verzeichnis-Marker (filename='.'), sonst verwirft
        # Moodle beim Restore ALLE Dateien dieses Kapitels (siehe
        # file_manager.add_moodle_directory).
        file_ids.append(file_mgr.add_moodle_directory(
            context_id, "mod_book", "chapter", chapter_id, now))
        # sanitize_for_moodle liefert pro Bild-VORKOMMEN einen Eintrag
        # (zweimal referenziertes Bild = zwei Einträge). Im Dateibereich des
        # Kapitels darf jeder Name nur einmal vorkommen – gleicher Inhalt
        # wird deshalb einmal registriert, verschiedener Inhalt bekommt einen
        # eindeutigen Namen samt mitgezogenem Verweis (siehe FileAreaNames).
        chapter_names = FileAreaNames()
        registered = set()
        for asset_path in asset_paths:
            asset_data = _find_by_basename(sub_vfs, asset_path, base_href=href)
            if asset_data is None:
                print(f"[!] CP-Asset '{asset_path}' nicht im Paket gefunden.")
                continue
            original = asset_path.split('/')[-1]
            asset_filename, clean_html = chapter_names.assign_in_html(
                original, asset_data, clean_html)
            if asset_filename != original:
                print(f"[*] Kapitel '{href}': zwei verschiedene Dateien heißen "
                      f"'{original}' – die zweite wird als '{asset_filename}' übernommen.")
            if asset_filename in registered:
                continue
            registered.add(asset_filename)
            file_id = file_mgr.add_moodle_file(
                source_content=asset_data, filename=asset_filename,
                contextid=context_id, component="mod_book", filearea="chapter",
                itemid=chapter_id, now=now)
            file_ids.append(file_id)

    return clean_html, file_ids, removed_links


def _generate_book_xml(module_id: int, context_id: int, title: str,
                       intro_html: str, now: int, chapters: List[Dict]) -> str:
    """chapters: [{'id', 'title', 'subchapter', 'content'}, ...] in
    Anzeigereihenfolge – pagenum wird daraus fortlaufend vergeben. Die
    book-eigene id ist einfach module_id, Moodle braucht hier keine
    getrennte ID (wie bei Quiz, siehe qti_quiz_builder._generate_quiz_xml)."""
    safe_title = escape_xml_text(title)

    chapter_blocks = []
    for idx, ch in enumerate(chapters, start=1):
        safe_ch_title = escape_xml_text(ch['title'])
        # quote=False: Moodles Backup-XML erwartet in Text-Inhalten nur
        # &/</> escaped, literale Anführungszeichen (z.B. in
        # src="@@PLUGINFILE@@/foo.png") bleiben unescaped – sonst findet
        # backup_validator.py's @@PLUGINFILE@@-Regex (stoppt an echtem ")
        # kein Bild-Ende mehr und liest über den ganzen Rest des Kapitels hinweg.
        safe_content = html_lib.escape(ch['content'], quote=False)
        chapter_blocks.append(f"""      <chapter id="{ch['id']}">
        <pagenum>{idx}</pagenum>
        <subchapter>{ch['subchapter']}</subchapter>
        <title>{safe_ch_title}</title>
        <content>{safe_content}</content>
        <contentformat>1</contentformat>
        <hidden>0</hidden>
        <timemodified>{now}</timemodified>
        <importsrc></importsrc>
      </chapter>""")
    chapters_block = '\n'.join(chapter_blocks)

    return f"""<activity id="{module_id}" moduleid="{module_id}" modulename="book" contextid="{context_id}">
  <book id="{module_id}">
    <name>{safe_title}</name>
    <intro>{html_lib.escape(intro_html, quote=False)}</intro>
    <introformat>1</introformat>
    <numbering>1</numbering>
    <navstyle>1</navstyle>
    <customtitles>0</customtitles>
    <timecreated>{now}</timecreated>
    <timemodified>{now}</timemodified>
    <chapters>
{chapters_block}
    </chapters>
    <chaptertags>
    </chaptertags>
  </book>
</activity>"""


def build_fallback_book_xml(module_id: int, context_id: int, title: str,
                            intro_html: str, now: int, id_gen) -> str:
    """Minimales, aber valides book.xml mit einem Platzhalter-Kapitel – für
    den Fall, dass das IMS-CP-Paket nicht auflösbar ist.

    intro_html ist das von main.py bereits sanitisierte html_content der
    Knotenbeschreibung (dessen Bilder unter component=mod_book/filearea=
    intro/itemid=0 registriert wurden) – gehört deshalb ins <intro>-Feld,
    NICHT ins Kapitel (ein Kapitel bräuchte filearea='chapter', die Bilder
    wären dort falsch zugeordnet und blieben kaputt).

    Das Platzhalter-Kapitel bekommt einen deutlich sichtbaren Warnhinweis
    (analog zum is_fallback-Banner in moodle_xml.modify_activity_xml),
    damit ein Kursverantwortlicher erkennt, dass der eigentliche
    Content-Package-Inhalt nicht automatisch übernommen werden konnte.

    Wichtig: NIE das kopierte Template-book.xml unverändert stehen lassen –
    dessen <chapters> enthalten nur Platzhaltertext, kein echter Kursinhalt.
    """
    warning = EMPTY_BOOK_WARNING
    chapters = [{'id': id_gen.next(), 'title': title, 'subchapter': 0, 'content': warning}]
    return _generate_book_xml(
        module_id=module_id, context_id=context_id,
        title=title, intro_html=intro_html, now=now, chapters=chapters)


def build_book_activity(node: Dict, manifest, context_id: int, module_id: int, now: int,
                        file_mgr, id_gen, intro_html: str = "",
                        link_map: Optional[Dict] = None) -> Optional[BookActivityResult]:
    """Baut eine vollständige Buch-Aktivität mit echten Kapiteln aus einem
    OLAT-cp-Knoten. id_gen ist derselbe kurslaufweite IdGenerator wie bei
    qti_quiz_builder (siehe main.py) – Kapitel-IDs teilen sich damit einen
    kollisionsfreien ID-Raum mit Fragen/Kategorien-IDs.

    intro_html ist das von main.py bereits sanitisierte html_content der
    Knotenbeschreibung (Bilder darin sind unter component=mod_book/
    filearea=intro/itemid=0 registriert) – wird unverändert als <intro>
    übernommen, NICHT die rohe Beschreibung, sonst blieben Bildpfade
    unaufgelöst und die registrierten intro-Dateien wären unbenutzte
    Leichen im Backup. link_map löst kursinterne gotonode-Verweise in den
    Kapitel-Seiten auf, wie bei jedem anderen Bausteintyp.

    Bricht mit None ab, sobald das Paket nicht auflösbar ist oder keine
    Kapitel gefunden werden – main.py fällt dann auf das generische
    Verhalten zurück (Beschreibung als Intro, leeres Buch), statt den
    Kurslauf abzubrechen.

    Gibt bei Erfolg {"book_xml", "file_ids", "removed_links"} zurück, sonst None.
    """
    if node.get('ident') == STANDALONE_CP_IDENT:
        sub_vfs = manifest.vfs
    else:
        sub_vfs = manifest.resolve_repo_package(
            node.get('ident'), 'IMSCP', 'IMS-CP-Paket', node.get('title'))
        if sub_vfs is None:
            return None

    manifest_bytes = _find_by_basename(sub_vfs, 'imsmanifest.xml')
    if manifest_bytes is None:
        print(f"[!] '{node.get('title')}': imsmanifest.xml nicht im IMS-CP-Paket gefunden.")
        return None

    try:
        pages = _parse_manifest_items(manifest_bytes)
    except ET.ParseError as e:
        print(f"[!] '{node.get('title')}': imsmanifest.xml nicht parsebar: {e}")
        return None

    if not pages:
        print(f"[!] '{node.get('title')}': keine Kapitel im IMS-CP-Paket gefunden.")
        return None

    file_ids = []
    chapters = []
    removed_links = []
    for page in pages:
        chapter_id = id_gen.next()
        content, page_file_ids, page_removed_links = _process_page(
            page['href'], sub_vfs, file_mgr, context_id, chapter_id, now, link_map)
        chapters.append({'id': chapter_id, 'title': page['title'],
                         'subchapter': page['subchapter'], 'content': content})
        file_ids.extend(page_file_ids)
        removed_links.extend(page_removed_links)

    book_xml = _generate_book_xml(
        module_id=module_id, context_id=context_id,
        title=activity_title(node, 'Buch'), intro_html=intro_html, now=now, chapters=chapters)

    # Explizit typisierte Zwischenvariable statt eines direkt zurückgegebenen
    # Dict-Literals – PyCharms TypedDict-Erkennung matcht ein Literal direkt
    # im return sonst nicht zuverlässig gegen BookActivityResult.
    result: BookActivityResult = {
        "book_xml": book_xml, "file_ids": file_ids, "removed_links": removed_links,
    }
    return result
