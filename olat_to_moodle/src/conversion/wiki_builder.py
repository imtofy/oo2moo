"""Baut eine echte Moodle-Wiki-Aktivität (mod_wiki) mit echten Seiten aus
einem OLAT-wiki-Baustein.

Ein wiki-CourseNode referenziert sein Wiki-Paket über 'export/<ident>/
repo.zip', aufgelöst über manifest.resolve_repo_package() - derselbe
Mechanismus wie bei QTI-Testpaketen und CP-Bausteinen. Das Paket enthält
pro Seite ein '<Base64-Name>.properties'/'.wp'-Dateipaar (Metadaten/Inhalt);
bearbeitete Seiten haben zusätzlich '._oo_vr_<N>_<Base64-Name>.properties'/
'.wp'-Paare als Versionshistorie. Die Benennung ist nicht ganz einheitlich
(mal mit, mal ohne Versions-Suffix am aktuellen Stand) - _pick_current_pages()
nimmt pragmatisch die zuletzt erkennbare Fassung je Seite.

Gegen echten Moodle-Wiki-Export verifiziert (Schema aus Moodles eigenem
backup_wiki_stepslib.php UND einem echten populierten .mbz): Moodle
speichert Wiki-Seiten intern selbst als HTML (defaultformat/contentformat
'html'), OLATs eigene Wiki-Syntax (MediaWiki-artig) wird deshalb über
wiki_markup.to_html() umgewandelt, nicht 1:1 durchgereicht.

WICHTIG: Moodles restore_wiki_stepslib.php verarbeitet Seiten/Versionen nur,
wenn die Aktivitäts-Einstellung '{modname}_{id}_userinfo' auf 1 steht (siehe
xml_generator.py) - ohne das bliebe jedes noch so vollständige wiki.xml von
Moodle unbeachtet. userid bleibt hier trotzdem überall 0 (kein echter OLAT-
Autor wird übernommen, siehe _page_xml)."""

import html as html_lib
import re
from typing import Dict, Optional, TypedDict

from .wiki_markup import to_html

# Historische Versionsstände tragen dieses Präfix vor dem Base64-Seitennamen -
# nur der unpräfixierte Dateiname kann der aktuelle Stand sein.
_VERSION_HISTORY_PREFIX = '._oo_vr_'

# '<Base64Name>.wp' oder '<Base64Name>.wp-<Zahl>' (beide Formen kommen als
# jeweils "aktueller" Stand vor, siehe Moduldocstring) - ebenso für .properties.
_PAGE_FILE = re.compile(r'^(?P<key>.+?)\.(?P<kind>wp|properties)(?:-(?P<num>\d+))?$')


class WikiActivityResult(TypedDict):
    wiki_xml: str


def _basename(path: str) -> str:
    return path.split('|')[-1].split('/')[-1]


def _parse_properties(data: bytes) -> Dict[str, str]:
    """Parst eine Java-.properties-Datei (key=value, '#' leitet Kommentarzeilen
    ein) in ein Dict - Moodles eigene Escape-Konventionen (z.B. '\\:') kommen
    in den hier relevanten Feldern (Titel, Zeitstempel) nicht vor, deshalb
    bewusst kein vollständiger Properties-Parser."""
    result = {}
    for line in data.decode('utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if sep:
            result[key.strip()] = value.strip()
    return result


def _pick_current_pages(sub_vfs: Dict[str, bytes]) -> Dict[str, Dict[str, bytes]]:
    """Gruppiert die Dateien im Wiki-Paket-VFS je Seite (Base64-Schlüssel) und
    wählt pro Seite die zuletzt erkennbare .wp/.properties-Fassung - eine
    fehlende Versionsnummer (bloßes '<Name>.wp') zählt dabei als NEUER als
    jede nummerierte Fassung, siehe Moduldocstring."""
    best_num: Dict[str, Dict[str, float]] = {}
    chosen: Dict[str, Dict[str, bytes]] = {}

    for path, data in sub_vfs.items():
        name = _basename(path)
        if name.startswith(_VERSION_HISTORY_PREFIX) or name.startswith('._oo') or name == '._ootrash':
            continue
        match = _PAGE_FILE.match(name)
        if not match:
            continue
        key, kind, num = match.group('key'), match.group('kind'), match.group('num')
        rank = float('inf') if num is None else float(num)
        current_rank = best_num.setdefault(key, {}).get(kind, -1.0)
        if rank >= current_rank:
            best_num[key][kind] = rank
            chosen.setdefault(key, {})[kind] = data

    return {k: v for k, v in chosen.items() if 'wp' in v}


def _decode_page_title(key: str, properties: Dict[str, str]) -> str:
    """Nimmt bevorzugt 'pagename' aus den Properties (Original-Schreibweise
    inkl. Sonderzeichen) - der Base64-Schlüssel selbst ist nur der
    URL-sichere Dateiname und kann bei Sonderzeichen abweichen."""
    return properties.get('pagename') or key


def _millis_to_seconds(value: Optional[str], fallback: int) -> int:
    """OLATs cTime/mTime in den .properties-Dateien sind Java-Millisekunden-
    Zeitstempel, Moodles Backup-Felder erwarten Unix-Sekunden."""
    if not value:
        return fallback
    try:
        return int(value) // 1000
    except ValueError:
        return fallback


def build_wiki_activity(node, manifest, context_id: int, module_id: int,
                        now: int) -> Optional[WikiActivityResult]:
    """Baut eine vollständige Wiki-Aktivität mit echten Seiten aus einem
    OLAT-wiki-Knoten. Jede Seite bekommt genau eine Version (den aktuellen
    Stand) statt OLATs vollständiger, uneinheitlich benannter
    Versionshistorie - siehe Moduldocstring.

    Bricht mit None ab, wenn das Paket nicht auflösbar ist oder keine Seiten
    gefunden werden - main.py fällt dann auf die generische, leere Wiki-
    Aktivität zurück statt den Kurslauf abzubrechen.
    """
    sub_vfs = manifest.resolve_repo_package(node.get('ident'), 'WIKI', 'Wiki-Paket', node.get('title'))
    if sub_vfs is None:
        return None

    pages_by_key = _pick_current_pages(sub_vfs)
    if not pages_by_key:
        return None

    safe_name = html_lib.escape(str(node.get('title') or 'Wiki'))
    page_xmls = []
    first_page_title = None
    page_id = 0
    version_id = 0

    for key, files in pages_by_key.items():
        properties = _parse_properties(files['properties']) if 'properties' in files else {}
        title = _decode_page_title(key, properties)
        if first_page_title is None or key == 'SW5kZXg=':
            # 'SW5kZXg=' ist OLATs Base64-Kodierung von 'Index' - OLATs
            # eigene Startseiten-Konvention, deckt sich meist mit Moodles
            # 'firstpagetitle'. Sonst bleibt es bei der ERSTEN gefundenen Seite.
            if key == 'SW5kZXg=' or first_page_title is None:
                first_page_title = title

        wikitext = files['wp'].decode('utf-8', errors='replace')
        content_html = to_html(wikitext)

        created = _millis_to_seconds(properties.get('cTime'), now)
        modified = _millis_to_seconds(properties.get('mTime'), now)

        page_id += 1
        version_id += 1
        safe_title = html_lib.escape(title)
        safe_content = html_lib.escape(content_html, quote=False)
        page_xmls.append(f"""      <page id="{page_id}">
        <title>{safe_title}</title>
        <cachedcontent>{safe_content}</cachedcontent>
        <timecreated>{created}</timecreated>
        <timemodified>{modified}</timemodified>
        <timerendered>{now}</timerendered>
        <userid>0</userid>
        <pageviews>0</pageviews>
        <readonly>0</readonly>
        <versions>
          <version id="{version_id}">
            <content>{safe_content}</content>
            <contentformat>html</contentformat>
            <version>1</version>
            <timecreated>{modified}</timecreated>
            <userid>0</userid>
          </version>
        </versions>
        <tags>
        </tags>
      </page>""")

    safe_first_page = html_lib.escape(first_page_title or 'Index')
    pages_xml = "\n".join(page_xmls)
    wiki_xml = f"""<activity id="{module_id}" moduleid="{module_id}" modulename="wiki" contextid="{context_id}">
  <wiki id="{module_id}">
    <name>{safe_name}</name>
    <intro></intro>
    <introformat>1</introformat>
    <timecreated>{now}</timecreated>
    <timemodified>{now}</timemodified>
    <firstpagetitle>{safe_first_page}</firstpagetitle>
    <wikimode>collaborative</wikimode>
    <defaultformat>html</defaultformat>
    <forceformat>1</forceformat>
    <editbegin>0</editbegin>
    <editend>0</editend>
    <subwikis>
      <subwiki id="1">
        <groupid>0</groupid>
        <userid>0</userid>
        <pages>
{pages_xml}
        </pages>
        <synonyms>
        </synonyms>
        <links>
        </links>
      </subwiki>
    </subwikis>
  </wiki>
</activity>"""

    return {"wiki_xml": wiki_xml}
