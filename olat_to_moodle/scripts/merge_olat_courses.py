"""Einmalig lokal auszuführen – baut aus mehreren echten OLAT-Kursexporten
EINEN zusammengeführten Test-Kurs mit möglichst breiter Bausteintyp-Abdeckung,
gedeckelt auf höchstens MAX_PER_TYPE Instanzen pro OLAT-Bausteintyp (über alle
Quellkurse hinweg gezählt, nicht pro Kurs).

Nicht Teil der gebauten .exe – reines Entwickler-Testwerkzeug, damit der
Konverter an einem einzigen Kurs mit vielen verschiedenen Bausteinen getestet
werden kann statt viele einzelne Kurse durchzugehen.

Funktionsweise:
  1. Nutzt olat_parser.parse_olat_export() (denselben Parser wie der
     Konverter selbst) auf jedem Quell-ZIP, um Titel/Typ/Ident jedes Knotens
     zu bekommen – Struktur-Knoten ('st') zählen nicht mit, nur echte
     Bausteine.
  2. Wählt Knoten aus, bis MAX_PER_TYPE pro Typ erreicht ist (erster Kurs
     zuerst, Baumreihenfolge innerhalb eines Kurses).
  3. Baut einen neuen editortreemodel.xml-Baum: ein 'st'-Abschnitt pro
     beitragendem Quellkurs, benannt nach dem Kurs, mit dessen ausgewählten
     Knoten als direkte Kinder (bewusst flach – keine Mehrfachverschachtelung
     nötig, das würde nur unnötig gegen MAX_SECTION_DEPTH laufen).
  4. Kopiert export/<ident>/ je ausgewähltem Knoten unverändert (Idents sind
     über alle Quellkurse hinweg eindeutig – geprüft, keine Kollision).
  5. oocoursefolder.zip bleibt bewusst LEER (siehe Einschränkung unten).

Bekannte Einschränkung: Der gemeinsame Kursordner (oocoursefolder.zip) wird
NICHT übernommen – eine vollständige Zusammenführung je Kurs mit
Ordnerpräfix würde die Ausgabe auf mehrere hundert MB aufblähen (u.a.
große PDFs aus Kursen, deren übriger Inhalt gar nicht ausgewählt wurde)
und wäre trotzdem nur teilweise korrekt (Inline-Verweise auf coursefolder-
Pfade werden nicht umgeschrieben). Für einen reinen Bausteintyp-
Abdeckungstest unkritisch; Bausteine, die auf den Kursordner verweisen
(Ordner 'bc'/'pf', eingebettete Bilder in HTML-Seiten), zeigen im Ergebnis
leer/fehlend.

Aufruf: python scripts/merge_olat_courses.py
"""

import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from olat_parser import parse_olat_export  # noqa: E402

SOURCE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'Files')
OUTPUT_ZIP = os.path.join(os.path.dirname(__file__), '..', '..', 'merged_test_kurs.zip')
MAX_PER_TYPE = 2

# Bekannte Sonderfälle ohne editortreemodel.xml (eigenständige Testpakete /
# reines CP-Paket) – werden übersprungen, siehe Modul-Docstring.
_SKIP_FILES = {"BeispielTest.zip", "BeispielTest (1).zip", "alle_testfragen.zip", "CP.zip"}


def _find_entry(zf: zipfile.ZipFile, filename: str):
    """Findet einen Dateinamen im ZIP unabhängig von einer zusätzlichen
    Verschachtelungsebene (manche Exporte haben einen Wrapper-Ordner mit
    demselben Namen wie die Datei, siehe kommentierter_Musterkurs_OpenOLAT)."""
    for name in zf.namelist():
        if name == filename or name.endswith('/' + filename):
            return name
    return None


def _course_safe_name(course_name: str) -> str:
    return re.sub(r'[^A-Za-z0-9_]+', '_', course_name).strip('_')[:40] or "kurs"


def _find_node_element(tree_root, ident: str):
    """Sucht den <org.olat.course.tree.CourseEditorTreeNode>-Block mit
    gegebenem Ident (Wrapper-Ident, nicht das <cn>-eigene) im Originalbaum."""
    for elem in tree_root.iter('org.olat.course.tree.CourseEditorTreeNode'):
        ident_elem = elem.find('ident')
        if ident_elem is not None and ident_elem.text and ident_elem.text.strip() == ident:
            return elem
    return None


def _make_wrapper_node(ident: str, title: str) -> ET.Element:
    """Baut einen minimalen 'st'-Struktur-Knoten (siehe olat_parser
    ._extract_node_fields – class 'STCourseNode' + longTitle reichen)."""
    wrapper = ET.Element('org.olat.course.tree.CourseEditorTreeNode')
    ET.SubElement(wrapper, 'ident').text = ident
    ET.SubElement(wrapper, 'accessible').text = 'true'
    ET.SubElement(wrapper, 'selected').text = 'false'
    cn = ET.SubElement(wrapper, 'cn', {'class': 'org.olat.course.nodes.STCourseNode'})
    ET.SubElement(cn, 'ident').text = ident
    ET.SubElement(cn, 'type').text = 'st'
    ET.SubElement(cn, 'longTitle').text = title
    ET.SubElement(cn, 'shortTitle').text = title[:25]
    ET.SubElement(wrapper, 'children')
    return wrapper


def main():
    print(f"[*] Suche Quellkurse in {SOURCE_DIR} ...")
    source_zips = []
    for fname in sorted(os.listdir(SOURCE_DIR)):
        if not fname.lower().endswith('.zip') or fname in _SKIP_FILES:
            continue
        source_zips.append(os.path.join(SOURCE_DIR, fname))

    type_counts = {}
    selected_by_course = {}  # course_name -> [ident, ...]
    course_titles = {}       # course_name -> Anzeigename für die neue 'st'-Sektion

    for zip_path in source_zips:
        course_name = os.path.splitext(os.path.basename(zip_path))[0]
        try:
            nodes, _deleted = parse_olat_export(zip_path)
        except Exception as e:
            print(f"[!] '{course_name}': konnte nicht geparst werden ({type(e).__name__}: {e}) - übersprungen.")
            continue
        if not nodes:
            print(f"[*] '{course_name}': kein Kursbaum gefunden (Sonderfall) - übersprungen.")
            continue

        picked = []
        for node in nodes:
            node_type = node.get('type')
            if node_type == 'st':
                continue
            if type_counts.get(node_type, 0) >= MAX_PER_TYPE:
                continue
            type_counts[node_type] = type_counts.get(node_type, 0) + 1
            picked.append(node['ident'])

        if picked:
            selected_by_course[course_name] = picked
            course_titles[course_name] = course_name.replace('_', ' ')
            print(f"[+] '{course_name}': {len(picked)} Baustein(e) ausgewählt.")
        else:
            print(f"[*] '{course_name}': nichts mehr auszuwählen (alle Typen bereits gedeckelt).")

    print(f"\n[*] {sum(len(v) for v in selected_by_course.values())} Bausteine über "
          f"{len(selected_by_course)} Kurse, {len(type_counts)} verschiedene Typen.")
    print(f"    Typen: {', '.join(sorted(type_counts))}")

    # --- Neuen Baum + gesammelte Dateien aufbauen ---
    merged_root = ET.Element('org.olat.course.tree.CourseEditorTreeModel')
    root_node = ET.SubElement(merged_root, 'rootNode', {'class': 'org.olat.course.tree.CourseEditorTreeNode'})
    root_ident = str(int(time.time() * 1000))
    ET.SubElement(root_node, 'ident').text = root_ident
    root_children = ET.SubElement(root_node, 'children')

    export_sources = {}      # ident -> zip_path
    base_config_source = None

    for idx, (course_name, idents) in enumerate(selected_by_course.items()):
        zip_path = [z for z in source_zips if os.path.splitext(os.path.basename(z))[0] == course_name][0]
        if base_config_source is None:
            base_config_source = zip_path

        with zipfile.ZipFile(zip_path) as zf:
            tree_entry = _find_entry(zf, 'editortreemodel.xml')
            with zf.open(tree_entry) as f:
                src_root = ET.parse(f).getroot()

        section_ident = f"{root_ident}{idx:02d}"
        section_node = _make_wrapper_node(section_ident, f"Aus: {course_titles[course_name]}")
        section_children = section_node.find('children')

        for ident in idents:
            node_elem = _find_node_element(src_root, ident)
            if node_elem is None:
                print(f"[!] '{course_name}': Knoten {ident} im Baum nicht wiedergefunden - übersprungen.")
                continue
            # Eigene Kind-Knoten NICHT mitnehmen – jedes Kind wurde unabhängig
            # über die flache nodes-Liste von parse_olat_export bewertet, ein
            # unverändertes Mitschleppen würde die MAX_PER_TYPE-Deckelung umgehen.
            existing_children = node_elem.find('children')
            if existing_children is not None:
                node_elem.remove(existing_children)
            ET.SubElement(node_elem, 'children')
            section_children.append(node_elem)
            export_sources[ident] = zip_path

        root_children.append(section_node)

    if base_config_source is None:
        print("[!] Keine Kurse mit auswählbaren Bausteinen gefunden - Abbruch.")
        return

    # --- Alles in ein neues ZIP schreiben ---
    os.makedirs(os.path.dirname(OUTPUT_ZIP), exist_ok=True)
    with zipfile.ZipFile(OUTPUT_ZIP, 'w', zipfile.ZIP_DEFLATED) as out:
        out.writestr('editortreemodel.xml', ET.tostring(merged_root, encoding='unicode', xml_declaration=True))

        with zipfile.ZipFile(base_config_source) as zf:
            for meta_name in ('CourseConfig.xml', 'runstructure.xml'):
                entry = _find_entry(zf, meta_name)
                if entry:
                    out.writestr(meta_name, zf.read(entry))

        # export/<ident>/... je ausgewähltem Knoten, unverändert kopiert.
        for ident, zip_path in export_sources.items():
            with zipfile.ZipFile(zip_path) as zf:
                prefix = None
                for name in zf.namelist():
                    if f"export/{ident}/" in name or name.endswith(f"export/{ident}"):
                        prefix = name.split(f"export/{ident}")[0] + f"export/{ident}"
                        break
                if prefix is None:
                    continue
                for name in zf.namelist():
                    if name.startswith(prefix + '/') or name == prefix:
                        rel = name[len(prefix):].lstrip('/')
                        arcname = f"export/{ident}/{rel}" if rel else f"export/{ident}"
                        if name.endswith('/'):
                            continue
                        out.writestr(arcname, zf.read(name))

        # Bewusst LEER statt voll zusammengeführt: der komplette oocoursefolder.zip
        # jedes beitragenden Kurses würde die Ausgabe auf mehrere hundert MB
        # aufblähen (u.a. große PDFs aus Kursen, deren restlicher Inhalt gar
        # nicht ausgewählt wurde) – für einen reinen Bausteintyp-Abdeckungstest
        # unnötiger Ballast.
        # Bekannte Folge: Bausteine, die auf den gemeinsamen Kursordner verweisen
        # (z.B. Ordner-Bausteine 'bc'/'pf', Bilder in HTML-Seiten), zeigen im
        # Ergebnis leer/fehlend – für den Abdeckungstest selbst unkritisch.
        import io
        empty_cf = io.BytesIO()
        with zipfile.ZipFile(empty_cf, 'w', zipfile.ZIP_DEFLATED):
            pass
        out.writestr('oocoursefolder.zip', empty_cf.getvalue())

    print(f"\n[FERTIG] {OUTPUT_ZIP}")


if __name__ == '__main__':
    main()
