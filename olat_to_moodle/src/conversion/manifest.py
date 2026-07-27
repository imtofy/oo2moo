"""Liest einen kompletten OLAT-Kursexport in ein flaches Dict aus virtuellem
Pfad → Rohdaten (Bytes) ein - durchsuchbar wie ein Dateisystem, ohne dass
man selbst mit verschachtelten ZIPs arbeiten muss.

Ein OLAT-Export ist ein ZIP, das selbst wieder ZIPs enthält (Kursordner,
Ressourcen, eingebettete QTI-Testpakete). CourseManifest packt das rekursiv
komplett aus, sodass der Rest des Konverters nie selbst mit zipfile
arbeiten muss.
"""

import zipfile
import io
import os
import posixpath
import re
import html as html_lib
import urllib.parse
import warnings
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from bs4 import XMLParsedAsHTMLWarning
from .anonymizer import sanitize_vfs

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def _is_empty_zip(data: bytes) -> bool:
    """Prüft, ob ein Zip-Archiv (z.B. OLATs 'oonode.zip') keine einzige Datei enthält."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return len(z.namelist()) == 0
    except Exception:
        return False


def _parse_cepage(xml_bytes: bytes) -> str | None:
    """Baut aus einer echten OLAT-"Content Editor"-Seite (page.xml, cepage-
    Bausteine wie org.olat.course.nodes.PageCourseNode - NICHT die ältere
    'sp'-Einzelseite) den zusammenhängenden HTML-Inhalt.

    Anders als bei 'sp' liegt der Text hier nicht als eine fertige HTML-
    Datei vor, sondern als flache, nach <pos> geordnete Liste einzelner
    Bausteine (<paragraphPart>, <titlePart>, ...) direkt unter
    <page>/<body>/<parts> (JPA: EIN PageBodyImpl mit @OneToMany-Liste, keine
    echte Verschachtelung - siehe OpenOLAT-Quelle org.olat.modules.ceditor).
    Ein <containerPart> darunter gruppiert mehrere dieser Geschwister-
    Bausteine (über <layoutOptions>/<columns>/<containercolumn>/<elementIds>,
    selbst wieder als HTML-escapte XML gespeichert) als Spalten nebeneinander
    - z.B. "Kapitel 1"/"Kapitel 2"/"Kapitel 3" als drei Kästen in
    einer Reihe statt linear untereinander. Ohne diese Funktion ginge diese
    Spalten-Gruppierung komplett verloren (jeder Baustein einzeln
    untereinander), weil der generische XML-Fallback in get_node_assets()
    nur alle <content>-Tags der Reihe nach aneinanderhängt.

    Baut die tatsächliche Spalten-Aufteilung nicht 1:1 nach (OLATs eigene
    CSS-Klassen je Layout-Typ, z.B. "1 breite Zeile + 3 Spalten darunter"
    bei block_1_3rows, sind hier nicht bekannt) - alle Spalten eines
    Containers werden gleich breit nebeneinander gesetzt, unabhängig vom
    genauen Layout-Namen. Bildbausteine (mediaPart/galleryPart) haben kein
    eigenes <content> und werden deshalb an ihrer Stelle ausgelassen, nicht
    nachgebaut.

    Gibt None zurück, wenn xml_bytes keine solche Content-Editor-Seite ist -
    dann greift in get_node_assets() weiterhin der ältere, generische
    XML-Fallback."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    if root.tag != 'page':
        return None
    parts_elem = root.find('body/parts')
    if parts_elem is None or len(parts_elem) == 0:
        return None

    # Erster Durchlauf: jeden Baustein mit eigenem <content> einsammeln
    # (key -> Klartext-HTML), bevor die Container ausgewertet werden - ein
    # containerPart referenziert häufig Bausteine, die im Dokument ERST
    # NACH ihm stehen (siehe pos-Reihenfolge), muss also nicht selbst suchen.
    part_html = {}
    for part in parts_elem:
        key_elem = part.find('key')
        content_elem = part.find('content')
        if key_elem is not None and key_elem.text and content_elem is not None and content_elem.text:
            part_html[key_elem.text.strip()] = html_lib.unescape(content_elem.text)

    consumed_keys = set()
    blocks = []
    for part in parts_elem:
        key_elem = part.find('key')
        key = key_elem.text.strip() if (key_elem is not None and key_elem.text) else None

        if part.tag == 'containerPart':
            layout_elem = part.find('layoutOptions')
            if layout_elem is None or not layout_elem.text:
                continue
            try:
                layout_root = ET.fromstring(html_lib.unescape(layout_elem.text))
            except ET.ParseError:
                continue
            columns = []
            for column in layout_root.findall('.//containercolumn'):
                col_keys = [s.text.strip() for s in column.findall('.//elementIds/string')
                           if s.text and s.text.strip() in part_html]
                if col_keys:
                    columns.append(col_keys)
            if not columns:
                continue
            consumed_keys.update(k for col in columns for k in col)
            if len(columns) == 1:
                blocks.append("".join(part_html[k] for k in columns[0]))
            else:
                cell_style = f"vertical-align:top; width:{100 / len(columns):.4f}%; padding:0 10px;"
                cells = "".join(f'<td style="{cell_style}">{"".join(part_html[k] for k in col)}</td>'
                                for col in columns)
                blocks.append(f'<table style="width:100%; border-collapse:collapse;"><tr>{cells}</tr></table>')
        elif key is not None and key not in consumed_keys and key in part_html:
            blocks.append(part_html[key])

    return "\n".join(blocks) if blocks else None


class CourseManifest:
    """Virtuelles Dateisystem eines OLAT-Kursexports (baut self.vfs: virtueller
    Pfad → Rohdaten). Pfade in verschachtelten ZIPs bekommen den Pfad der
    äußeren ZIP plus '|'-Trenner (z.B. 'export/123/repo.zip|imsmanifest.xml'),
    damit gleichnamige Dateien in verschiedenen Containern nicht kollidieren."""

    def __init__(self, olat_zip_path):
        """Entpackt den Export rekursiv ins VFS und anonymisiert direkt danach."""
        self.vfs = {}
        self._parse_zip(olat_zip_path, prefix="")
        # Erst NACH dem vollständigen (rekursiven) Entpacken bereinigen -
        # verschachtelte Inhalte (repo.zip, oonode.zip, ...) liegen zu diesem
        # Zeitpunkt schon als eigene flache vfs-Einträge vor, eine Sonder-
        # behandlung für Verschachtelung ist daher nicht nötig.
        replaced = sanitize_vfs(self.vfs)
        if replaced:
            print(f"[*] {replaced} Nutzerkennung(en)/E-Mail-Adresse(n) anonymisiert.")

    def get_course_title(self):
        """Liest den echten Kurstitel aus 'export/repo.xml' (<DisplayName>).

        Das ist der vom Autor vergebene Titel - schöner als der aus dem
        Zip-Dateinamen abgeleitete (der oft eine vorangestellte Kursnummer
        oder Unterstriche enthält). Nur die KURS-repo.xml liegt direkt unter
        'export/repo.xml'; Baustein-Pakete liegen unter 'export/<ident>/
        repo.xml' und werden vom Pfad-Suffix daher nicht getroffen. None,
        falls keine (gültige) Kurs-repo.xml existiert - der Aufrufer fällt
        dann auf den Dateinamen zurück."""
        hit = None
        for path, data in self.vfs.items():
            if path == 'export/repo.xml' or path.endswith('/export/repo.xml'):
                hit = data
                break
        if hit is None:
            return None
        try:
            root = ET.fromstring(hit)
        except ET.ParseError:
            return None
        title = (root.findtext('.//DisplayName') or '').strip()
        return title or None

    def _parse_zip(self, zip_source, prefix):
        """Liest eine ZIP-Datei (Pfad oder BytesIO) in self.vfs ein und steigt
        bei jeder gefundenen .zip-Datei rekursiv eine Ebene tiefer ab, bis
        keine ZIPs mehr übrig sind. prefix ist der VFS-Pfad-Präfix der
        aktuellen Verschachtelungsebene."""
        try:
            with zipfile.ZipFile(zip_source, 'r') as z:
                for name in z.namelist():
                    if name.endswith('/'):
                        continue

                    try:
                        data = z.read(name)
                        virtual_path = f"{prefix}{name}".replace('\\', '/')
                        self.vfs[virtual_path] = data

                        if name.lower().endswith('.zip'):
                            nested_prefix = f"{virtual_path}|"
                            self._parse_zip(io.BytesIO(data), nested_prefix)
                    except Exception:
                        continue
        except Exception:
            pass

    @staticmethod
    def _vfs_basename(path):
        """Dateiname eines VFS-Pfads, auch hinter Nested-Zip-Grenzen ('|')."""
        return os.path.basename(path.split('|')[-1])

    @classmethod
    def _is_junk_file(cls, path):
        """Erkennt OLAT-Metadaten/OS-Müll, die bei der Dateisuche nie als Treffer
        zählen dürfen (z.B. '._oo_meta_datei.pdf' würde sonst bei der Suche
        nach 'datei.pdf' fälschlich matchen)."""
        base = cls._vfs_basename(path)
        return base.startswith('._oo_meta_') or base == '.DS_Store'

    def search_file(self, search_string, base_path=None):
        """Sucht eine Datei im VFS und gibt {"path", "data"} zurück, oder None.

        Vierstufige Suche, jede Stufe nur falls die vorherige nichts findet
        (Junk-Dateien werden überall übersprungen):
          0 (nur mit base_path): relativ zum Verzeichnis des referenzierenden
            Dokuments - nötig, weil Editor-Bilder wie 'mceclip0.png' oft
            gleichzeitig in vielen Ordnern liegen, nur die im selben Ordner
            ist die richtige.
          1: Pfad-Suffix-Treffer MIT Pfadgrenze ('/' oder '|') - ein nacktes
            endswith() ohne Grenze könnte sonst falsche Dateien treffen
            ('datei.pdf' würde z.B. '...Materialien datei.pdf' matchen).
          2: exakter Dateiname irgendwo im Archiv (falls die Pfadangabe nicht
            mehr stimmt, die Datei aber noch existiert).
          3: unscharfe Substring-Suche als letzter Ausweg - kann Fehltreffer
            liefern, wird deshalb immer mit Warnung geloggt.
        """
        if not search_string:
            return None

        clean_str = urllib.parse.unquote(search_string).replace('\\', '/')
        search_lower = clean_str.lower().lstrip('/')

        if base_path:
            base_norm = base_path.replace('\\', '/')
            base_dir = base_norm.rsplit('/', 1)[0] if '/' in base_norm else ''
            container = base_norm.rsplit('|', 1)[0] + '|' if '|' in base_norm else ''

            candidates = []
            if clean_str.startswith('/'):
                candidates.append(container + clean_str.lstrip('/'))
            else:
                if base_dir:
                    candidates.append(f"{base_dir}/{clean_str}")
                candidates.append(container + clean_str)

            for cand in candidates:
                if '|' in cand:
                    zip_part, rel_part = cand.rsplit('|', 1)
                    cand = zip_part + '|' + posixpath.normpath(rel_part)
                else:
                    cand = posixpath.normpath(cand)
                cand_lower = cand.lower()
                for path, data in self.vfs.items():
                    if path.lower() == cand_lower:
                        return {"path": path, "data": data}

        for path, data in self.vfs.items():
            if self._is_junk_file(path):
                continue
            p = path.lower()
            if (p == search_lower
                    or p.endswith('/' + search_lower)
                    or p.endswith('|' + search_lower)):
                return {"path": path, "data": data}

        basename = os.path.basename(search_lower)
        for path, data in self.vfs.items():
            if self._is_junk_file(path):
                continue
            if self._vfs_basename(path).lower() == basename:
                return {"path": path, "data": data}

        basename_no_ext = os.path.splitext(basename)[0]
        if len(basename_no_ext) > 3:
            for path, data in self.vfs.items():
                if self._is_junk_file(path):
                    continue
                if basename_no_ext in self._vfs_basename(path).lower():
                    print(f"[!] Unscharfer Datei-Treffer: '{search_string}' -> "
                          f"'{path}' – bitte im Ergebnis prüfen.")
                    return {"path": path, "data": data}

        return None

    def search_directory(self, search_dir):
        """Sammelt alle Nicht-XML-Dateien in einem VFS-Ordner (rekursiv, über
        Zip-Grenzen hinweg). Überspringt XML-/Metadateien und ZIP-Dateien,
        deren Inhalt schon als entpackte Einträge im VFS vorliegt (sonst
        taucht die ZIP-Hülle zusätzlich zu ihrem eigenen Inhalt auf)."""
        assets = []
        if not search_dir:
            return assets

        clean_dir = search_dir.strip('/').replace('\\', '/')
        for v_path, v_data in self.vfs.items():
            if f"/{clean_dir}/" in v_path or v_path.startswith(
                    f"{clean_dir}/") or f"|{clean_dir}/" in v_path:
                if not v_path.endswith('.xml') and not v_path.endswith('/'):
                    raw_filename = v_path.split('|')[-1]
                    clean_name = os.path.basename(raw_filename)

                    if clean_name == '.DS_Store' or clean_name.startswith(
                            '._oo_meta_') or 'oonode.zip' in v_path or 'oonode.zip' in clean_name:
                        continue

                    if v_path.endswith('.zip') and any(
                            p.startswith(v_path + '|') for p in self.vfs):
                        continue

                    assets.append({"name": clean_name, "data": v_data})
        return assets

    def resolve_repo_package(self, ident, resource_type_marker, package_label, node_title=None):
        """Löst ein per Repository-Referenz eingebundenes Paket auf (iqtest/
        iqself-QTI-Pakete, cp-Content-Packages) - beide referenzieren ihr
        Paket über denselben 'export/<ident>/'-Mechanismus:
          - 'export/<ident>/repo.xml' bestätigt per <ResourceType>, dass hier
            wirklich ein Paket vom erwarteten Typ hängt (resource_type_marker
            als Teilstring, z.B. 'IMSQTI' oder 'IMSCP').
          - 'export/<ident>/repo.zip' ist das eigentliche Paket, von
            CourseManifest bereits rekursiv in self.vfs entpackt.

        package_label nur fürs Log (z.B. 'QTI-Paket', 'IMS-CP-Paket').
        Gibt bei jedem Fehlschlag None zurück (mit Logmeldung) - der Aufrufer
        fällt dann auf sein jeweiliges Fallback-Verhalten zurück, statt den
        Kurslauf abzubrechen.
        """
        title = node_title or ident
        if not ident:
            return None

        repo_xml_hit = self.search_file(f"export/{ident}/repo.xml")
        if not repo_xml_hit:
            print(f"[!] '{title}': repo.xml nicht gefunden (export/{ident}/repo.xml) "
                  f"– kein {package_label} auflösbar.")
            return None

        try:
            repo_root = ET.fromstring(repo_xml_hit['data'])
        except ET.ParseError as e:
            print(f"[!] '{title}': repo.xml nicht parsebar: {e}")
            return None

        resource_type = (repo_root.findtext('.//ResourceType') or '').upper()
        if resource_type_marker not in resource_type:
            print(f"[!] '{title}': repo.xml hat ResourceType '{resource_type}' "
                  f"(kein {package_label}) – übersprungen.")
            return None

        repo_zip_hit = self.search_file(f"export/{ident}/repo.zip")
        if not repo_zip_hit:
            print(f"[!] '{title}': repo.zip nicht gefunden (export/{ident}/repo.zip) "
                  f"– {package_label} bestätigt, aber Inhalt fehlt.")
            return None

        prefix = repo_zip_hit['path'] + '|'
        sub_vfs = {path[len(prefix):]: data for path, data in self.vfs.items()
                  if path.startswith(prefix)}
        if not sub_vfs:
            print(f"[!] '{title}': repo.zip enthält keine entpackten Dateien "
                  f"(kein gültiges ZIP?) – übersprungen.")
            return None

        return sub_vfs

    def get_node_assets(self, ident):
        """Liefert HTML-Inhalt und Anhänge, die direkt zu einem OLAT-Kursknoten
        gehören ('export/<ident>/' im VFS). Die erste .html/.htm-Datei wird
        als Inhalt genommen, alles andere als Anhang. Ohne HTML-Datei wird
        zuerst versucht, eine echte Content-Editor-Seite (cepage, page.xml)
        über _parse_cepage() korrekt samt Spalten-Layout zusammenzubauen;
        klappt das nicht (kein page.xml o.ä.), Text aus XML-Dateien gewonnen:
        zuerst CDATA-Blöcke, sonst <content>/<fragment>/<text>-Tags (typisch
        für ältere Struktur-Knoten ohne eigene HTML-Seite)."""
        assets = []
        html_content = ""
        xml_contents = []
        xml_raw_contents = []

        search_prefix = f"export/{ident}/"
        for path, data in self.vfs.items():
            if search_prefix in path:
                if path.endswith(('.html', '.htm')) and not html_content:
                    html_content = data.decode('utf-8-sig', errors='ignore')
                elif path.endswith('.xml'):
                    xml_contents.append(data.decode('utf-8-sig', errors='ignore'))
                    xml_raw_contents.append(data)
                else:
                    raw_filename = path.split('|')[-1]
                    clean_name = os.path.basename(raw_filename)

                    if clean_name == '.DS_Store' or clean_name.startswith('._oo_meta_'):
                        continue

                    if path.endswith('.zip') and any(p.startswith(path + '|') for p in self.vfs):
                        continue

                    assets.append({"name": clean_name, "data": data})

        if not html_content and xml_raw_contents:
            for xml_bytes in xml_raw_contents:
                cepage_html = _parse_cepage(xml_bytes)
                if cepage_html:
                    html_content = cepage_html
                    break

        if not html_content and xml_contents:
            extracted_blocks = []
            for xml_text in xml_contents:
                cdata_matches = re.findall(r'<!\[CDATA\[(.*?)]]>', xml_text, re.DOTALL)
                if cdata_matches:
                    extracted_blocks.extend(cdata_matches)
                    continue

                soup = BeautifulSoup(xml_text, 'html.parser')
                for tag in soup.find_all(['content', 'fragment', 'text']):
                    if tag.text.strip() and len(tag.text.strip()) > 10:
                        extracted_blocks.append(tag.text.strip())

            if extracted_blocks:
                html_content = "<br>".join(extracted_blocks)

        return html_content, assets

    def get_node_folder_tree(self, ident):
        """Liefert Dateien UND leere Unterordner eines Ordner-Kursknotens (bc/pf).

        Anders als get_node_assets() wird die Unterordner-Struktur NICHT
        flach zusammengeworfen - jede Datei behält ihren relativen Pfad
        (i.d.R. innerhalb von 'oonode.zip') als 'relpath'. Komplett LEERE
        Unterordner haben im entpackten self.vfs keine Entsprechung (ein
        reiner Verzeichniseintrag ohne Inhalt wird beim Entpacken in
        CourseManifest._parse_zip verworfen), dafür wird der rohe Node-
        Container hier zusätzlich direkt eingelesen.
        """
        prefix = f"export/{ident}/"
        files = []
        dirs_with_content = set()

        for path, data in self.vfs.items():
            if prefix not in path or path.endswith(('.html', '.htm', '.xml')):
                continue

            if '|' in path:
                # Datei liegt hinter einer Zip-Grenze - alles nach dem LETZTEN
                # '|' ist bereits der Pfad relativ zum tiefsten Container.
                raw_filename = path.split('|')[-1]
            else:
                # Lose Datei/Zip direkt unter export/<ident>/ - hier muss der
                # Präfix selbst abgeschnitten werden, sonst würde 'export/<ident>'
                # fälschlich als Unterordner-Pfad interpretiert.
                idx = path.find(prefix)
                raw_filename = path[idx + len(prefix):] if idx != -1 else os.path.basename(path)

            clean_name = os.path.basename(raw_filename)

            if clean_name == '.DS_Store' or clean_name.startswith('._oo_meta_'):
                continue
            if path.endswith('.zip') and any(p.startswith(path + '|') for p in self.vfs):
                continue
            if path.endswith('.zip') and _is_empty_zip(data):
                # Enthält der Container-Zip (z.B. 'oonode.zip') selbst gar
                # keine Dateien, wäre er als Anhang nur ein bedeutungsloser
                # leerer Download - kein echter Ordnerinhalt.
                continue

            reldir = os.path.dirname(raw_filename).replace('\\', '/').strip('/')
            files.append({"name": clean_name, "relpath": reldir, "data": data})
            if reldir:
                parts = reldir.split('/')
                for depth in range(1, len(parts) + 1):
                    dirs_with_content.add('/'.join(parts[:depth]))

        empty_dirs = []
        for path, data in self.vfs.items():
            if path.startswith(prefix) and '|' not in path[len(prefix):] and path.lower().endswith('.zip'):
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as inner:
                        for name in inner.namelist():
                            if name.endswith('/'):
                                dirpath = name.rstrip('/').replace('\\', '/')
                                if dirpath and dirpath not in dirs_with_content and dirpath not in empty_dirs:
                                    empty_dirs.append(dirpath)
                except Exception:
                    continue

        return files, empty_dirs
