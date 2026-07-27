"""Orchestriert die komplette Konvertierung eines OLAT-Kursexports zu einer Moodle-.mbz.

Liest den OLAT-Export ein (CourseManifest + olat_parser), geht jeden
Kursknoten durch, kopiert das passende Moodle-Aktivitäts-Template, befüllt
es mit dem konvertierten Inhalt (node_processor/moodle_xml) und packt am
Ende alles zu einer .mbz. Test-Bausteine (iqtest/iqself) bekommen über
qti_quiz_builder.py echte Fragen statt einer leeren Quiz-Hülle, cp-Bausteine
(Content Package) über cp_book_builder.py ein echtes Buch mit Kapiteln statt
eines übersprungenen Bausteins. Einstiegspunkt ist
convert_olat_to_moodle(olat_zip_path, output_mbz_path).
"""

import os
import re
import sys
import time
import tempfile
import tarfile
import shutil
import uuid

from config import (OLAT_INPUT_FILE, MOODLE_OUTPUT_FILE, OLAT_TO_MOODLE_MAPPING,
                    TEMPLATE_DIR, SKIPPED_OLAT_TYPES, STANDALONE_QTI_IDENT,
                    STANDALONE_CP_IDENT, FLATTENED_BOUNDARY_MARKER, FLATTENED_CHILD_MARKER,
                    UNRECOGNIZED_TYPE_MARKER, WARNING_SYMBOL,
                    OFFICE_DOCUMENT_EXTS, OFFICE_DOCUMENT_MARKER, OLAT_NAMES)
from conversion.manifest import CourseManifest
from conversion.olat_parser import parse_olat_export, MAX_SECTION_DEPTH
from conversion.moodle_xml import (modify_activity_xml, modify_module_xml, rewrite_inforef_xml,
                                   set_forum_announcement_type, modify_subsection_xml)
from conversion.file_manager import write_xml, FileManager
from conversion.node_processor import build_node_content
from conversion.html_cleaner import MODULE_VIEW_TOKENS
from validators.backup_validator import validate_moodle_backup_integrity
from validators.conversion_validator import validate_conversion_completeness
from conversion.xml_generator import (get_template_mapping, generate_course_xml,
                                      generate_section_xml, generate_moodle_backup_xml,
                                      create_empty_meta_files)
from qti.helpers import IdGenerator
from conversion.conversion_report import (build_unsupported_placeholder_html,
                                          build_flattened_boundary_html,
                                          write_protocol_activities)
# QTI-Fragen-Pipeline liegt zur besseren Übersicht in einem eigenen
# Unterordner (qti/, echtes Package mit __init__.py). Als normaler
# Package-Import bleibt er für PyInstallers statische Analyse sichtbar,
# siehe qti/qti_pipeline.py und qti/qti_quiz_builder.py für die
# entsprechenden paketrelativen Imports.
from qti import qti_pipeline
from qti import qti_quiz_builder
from conversion import cp_book_builder

if hasattr(sys.stdout, "reconfigure"):
    # Windows-Konsole steht oft auf cp850/cp1252 - ohne das würden Umlaute
    # in den Log-Ausgaben zu Ersatzzeichen.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# OLAT-Testbausteine, die statt einer leeren Quiz-Hülle eine echte
# Fragen-Quiz-Aktivität bekommen (siehe qti_quiz_builder.py).
QUIZ_OLAT_TYPES = ("iqtest", "iqself")


# Moodle-Backup-Platzhalter für kursinterne Aktivitäts-Links, wie html_cleaner
# sie aus gotonode-Verweisen baut ($@<TOKEN>VIEWBYID*<moduleid>@$). Wird nach
# der Hauptschleife gebraucht, um Verweise auf Bausteine zu entschärfen, die
# während der Konvertierung doch fehlgeschlagen sind.
_INTERNAL_LINK_TOKEN = re.compile(r'\$@[A-Z]+VIEWBYID\*(\d+)@\$')


def _neutralize_dead_internal_links(temp_dir, valid_module_ids):
    """Entschärft interne Aktivitäts-Link-Platzhalter, deren Ziel-Baustein
    nicht erfolgreich erzeugt wurde. link_map wird VOR der Hauptschleife
    gebaut - ein Ziel-Baustein kann danach noch abstürzen und übersprungen
    werden, dessen Platzhalter würde dann auf eine im Backup nicht
    existierende Modul-ID zeigen. Ersetzt solche Platzhalter durch '#'
    (inerter Anker)."""
    activities_dir = os.path.join(temp_dir, "activities")
    if not os.path.isdir(activities_dir):
        return

    def _replace(match):
        """Ersetzt einen Link-Platzhalter durch '#', falls sein Ziel-Modul nicht existiert."""
        return match.group(0) if int(match.group(1)) in valid_module_ids else '#'

    for act_folder in os.listdir(activities_dir):
        act_path = os.path.join(activities_dir, act_folder)
        if not os.path.isdir(act_path):
            continue
        for xml_file in os.listdir(act_path):
            if not xml_file.endswith('.xml'):
                continue
            xml_path = os.path.join(act_path, xml_file)
            with open(xml_path, 'r', encoding='utf-8') as f:
                content = f.read()
            new_content = _INTERNAL_LINK_TOKEN.sub(_replace, content)
            if new_content != content:
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)


def _resolve_moodle_type(olat_type: str, node: dict) -> str:
    """Ermittelt den Moodle-Modultyp für einen Knoten - normalerweise 1:1
    aus OLAT_TO_MOODLE_MAPPING, außer bei 'document'-Bausteinen mit einem
    Office-Format (docx/xlsx/pptx/...): die gehen als 'resource' (Datei-
    Ressource) sofort in den Download, ohne Zwischenschritt - browserseitig
    ohnehin nicht anzeigbar, aber ein Klick sollte trotzdem erstmal eine
    Übersicht statt eines überraschenden Downloads zeigen. Deshalb 'folder'
    (Verzeichnis mit der einen Datei drin) statt 'resource' - der eigentliche
    Download passiert dann erst beim gezielten Klick auf die Datei selbst."""
    m_type = OLAT_TO_MOODLE_MAPPING.get(olat_type, "page")
    if olat_type == "document":
        ext = os.path.splitext(node.get('html_file', ''))[1].lower()
        if ext in OFFICE_DOCUMENT_EXTS:
            m_type = "folder"
    return m_type


def convert_olat_to_moodle(olat_zip_path, output_mbz_path):
    """Konvertiert einen kompletten OLAT-Kursexport in eine Moodle-.mbz.

    Für jeden Knoten wird der passende Moodle-Modultyp bestimmt, das
    Template kopiert und mit dem konvertierten Inhalt befüllt - bei
    iqtest/iqself über qti_quiz_builder.py (echte Fragen), sonst über
    node_processor/moodle_xml (generischer HTML-Inhalt). Ein Fehler bei
    einem einzelnen Baustein bricht die Konvertierung NICHT ab: er wird
    geloggt, der halbfertige Aktivitätsordner verworfen, weiter mit dem
    nächsten Knoten. Am Ende werden verwaiste Dateien gesammelt, das
    Systemprotokoll geschrieben, alle Metadaten erzeugt, die Backup-
    Integrität geprüft und alles zu einer .mbz gepackt.
    """
    now = int(time.time())
    backup_id = uuid.uuid4().hex

    print("[DEBUG] Lade Template-Mapping...")
    template_mapping = get_template_mapping(TEMPLATE_DIR)

    print("[DEBUG] Erstelle rekursives Manifest...")
    manifest = CourseManifest(olat_zip_path)
    nodes, deleted_nodes = parse_olat_export(olat_zip_path)

    # ident → Titel, nur für 'st'-Knoten (Struktur/Abschnitte) - genau die
    # Idents, die in 'parent_st_idents' vorkommen können (siehe olat_parser.
    # _walk_tree: nur benannte 'st'-Knoten erweitern die Kette, ein
    # unbenannter Abschnitt wird nie Teil einer fremden parent_st_idents-Liste).
    section_titles_by_ident = {n['ident']: n['title'] for n in nodes if n.get('type') == 'st'}

    def _format_location(title, parent_st_idents):
        """Baut 'Abschnitt → Unterabschnitt → Name' aus der Struktur-Kette
        eines Bausteins - fürs Systemprotokoll, damit übersprungene
        Elemente im OLAT-Kurs auffindbar bleiben. Reicht bei unterschiedlich
        verschachtelten Elementen, aber NICHT bei zwei identischen Elementen
        direkt in derselben (oder keiner) Sektion - dafür siehe
        _disambiguate_skipped_elements()."""
        crumbs = [section_titles_by_ident.get(pid, '?') for pid in (parent_st_idents or [])]
        crumbs.append(title or 'Unbenannt')
        return ' → '.join(crumbs)

    def _disambiguate_skipped_elements(elements):
        """Hängt die OLAT-ident an, wenn zwei übersprungene Elemente in
        derselben Gruppe (gleicher Typ+Grund) identisch angezeigt würden -
        sonst sehen z.B. zwei gleichnamige SCORM-Pakete ohne umschliessenden
        Abschnitt wie ein einziges, verdoppeltes Element aus. Nur dann,
        NICHT generell - ein technischer ident-Wert wäre sonst bei jedem
        Eintrag nur Rauschen."""
        counts = {}
        for el in elements:
            key = (el['type'], el['title'])
            counts[key] = counts.get(key, 0) + 1
        for el in elements:
            key = (el['type'], el['title'])
            if counts[key] > 1 and el.get('ident'):
                el['title'] = f"{el['title']} (ident: {el['ident']})"

    # Kursname bevorzugt aus dem echten OLAT-Kurstitel (export/repo.xml's
    # <DisplayName>), sonst aus dem Zip-Dateinamen ableiten - statt jeden
    # Kurs als "Imported OpenOLAT Course" zu importieren.
    zip_stem = os.path.splitext(os.path.basename(str(olat_zip_path)))[0]
    course_fullname = (manifest.get_course_title()
                       or zip_stem.replace('_', ' ').strip()
                       or "Imported OpenOLAT Course")
    course_shortname = re.sub(r'[^A-Za-z0-9]+', '_', course_fullname).strip('_')[:100] or "Imported_Course"
    print(f"[*] Kursname: {course_fullname}")

    if not nodes:
        # Kein Kursbaustein gefunden - entweder ein kaputter/leerer Export,
        # oder (häufiger) ein eigenständig aus OLATs Testeditor exportiertes
        # QTI-Testpaket ohne umgebenden Kurs (kein editortreemodel.xml, der
        # Export IST bereits das QTI-Paket, erkennbar an einer
        # assessmentTest-Datei mit Titel) - wird dann als Mini-Kurs mit
        # einer Quiz-Aktivität verpackt und durchläuft dieselbe Hauptschleife
        # wie ein normaler iqtest-Baustein. Analog dazu ein eigenständig
        # exportiertes IMS-Content-Package (imsmanifest.xml direkt im
        # Wurzel-ZIP statt unter 'export/<ident>/') - wird als Mini-Kurs mit
        # einer Buch-Aktivität verpackt, wie ein normaler cp-Baustein.
        standalone_title = qti_pipeline.find_standalone_test_title(manifest.vfs)
        if standalone_title:
            print(f"[*] Kein Kursexport erkannt, aber ein eigenständiges QTI-Testpaket "
                  f"('{standalone_title}') – wird als Mini-Kurs mit einer Quiz-Aktivität verpackt.")
            nodes = [{
                'title': standalone_title, 'type': 'iqtest', 'ident': STANDALONE_QTI_IDENT,
                'html_file': '', 'rel_path': '', 'url': '', 'repo_softkey': '', 'qti_type': '',
            }]
        else:
            standalone_cp_title = cp_book_builder.find_standalone_cp_title(manifest.vfs)
            if standalone_cp_title:
                print(f"[*] Kein Kursexport erkannt, aber ein eigenständiges Content-Package "
                      f"('{standalone_cp_title}') – wird als Mini-Kurs mit einer Buch-Aktivität verpackt.")
                nodes = [{
                    'title': standalone_cp_title, 'type': 'cp', 'ident': STANDALONE_CP_IDENT,
                    'html_file': '', 'rel_path': '', 'url': '', 'repo_softkey': '', 'qti_type': '',
                }]

    processed_activities = []
    # Bereits beim Parsen verworfene Knoten (unbenannt, Teilnehmerliste)
    # landen mit auf der Systemprotokoll-Seite statt stillschweigend zu
    # verschwinden.
    skipped_elements = [
        {'title': _format_location(d['title'], d.get('parent_st_idents')),
         'type': f"{d['type']}, {d['reason']}", 'ident': d.get('ident')}
        for d in deleted_nodes
    ]
    used_filenames = set()
    removed_links_log = []
    # Struktur-Knoten, die tiefer als MAX_SECTION_DEPTH verschachtelt waren
    # und deshalb in den umschliessenden Abschnitt "hochgezogen" wurden -
    # landet im Systemprotokoll, damit sichtbar ist, dass hier nachgeprüft
    # werden sollte, ob die entstandene flachere Struktur so passt.
    flattened_structures = []
    # Sauber (nicht is_fallback) übertragene Bausteine, für die positive
    # Erfolgs-Tabelle im Systemprotokoll (siehe convert_olat_to_moodle unten).
    transferred_elements = []
    context_id_counter = 10001
    sections = {}
    # OLAT-STCourseNode-Ident → Moodle-section_id, die dieser Struktur-
    # Knoten öffnet (siehe parent_st_idents in olat_parser.py).
    st_section_map = {}
    next_section_id = 0
    # Eigener, weit entfernter Nummernkreis für Unterabschnitte (Moodle-
    # course_sections.section, das <number> in section.xml) - getrennt vom
    # Nummernkreis der normalen Abschnitte oben. Grund: Moodles eigenes
    # Restore verschiebt JEDEN Unterabschnitt beim Wiederherstellen ohnehin
    # ans Ende der Abschnitts-Reihenfolge (restore_section_structure_step::
    # process_section() in Moodle-Core setzt section->section komplett neu,
    # unsere <number> wird für Unterabschnitte also nie übernommen) - liegt
    # eine Unterabschnitts-Nummer aber ZWISCHEN zwei normalen Abschnitten
    # (z.B. Abschnitt 5, Unterabschnitt 6, Abschnitt 7), reißt das Verschieben
    # eine Lücke in die normale Abschnittsfolge, die Moodle danach mit
    # leeren "Neuer Abschnitt"-Plätzen auffüllt - genau die Lücken, die wir
    # in echten Kursen gesehen haben. Mit einem eigenen, weit über der
    # normalen Abschnittszahl liegenden Nummernkreis für Unterabschnitte
    # bleibt die normale Abschnittsfolge lückenlos, egal wie viele
    # Unterabschnitte dazwischen "eigentlich" lägen.
    next_subsection_id = 10_000
    allgemein_section_id = None
    # Eigener ID-Raum für Unterabschnitt-Aktivitäten: course_modules-IDs
    # 1..len(nodes) sind schon an die OLAT-Knoten vergeben, Systemprotokoll/
    # Verwaiste-Dateien nutzen ab len(nodes)+1 - Unterabschnitte entstehen
    # aber WÄHREND der Hauptschleife und brauchen daher einen eigenen
    # laufenden Zähler, der danach an write_protocol_activities übergeben wird.
    next_free_module_id = len(nodes) + 1
    subsection_instance_counter = 0
    # Gemeinsamer ID-Raum für alle QTI-Fragen/Kategorien/Quiz-Instanzen im
    # ganzen Kurslauf (verhindert doppelte IDs, falls mehrere Tests im Kurs
    # vorkommen) - siehe qti_quiz_builder.py.
    qti_id_gen = IdGenerator(start=1)
    all_question_categories_xml = []
    # Fragen-Bilanz je Test-Baustein (Soll-Ist-Validierung am Ende) - wird von
    # build_quiz_activity befüllt, siehe conversion_validator.py.
    quiz_reports = []

    def _get_or_create_allgemein_section():
        """Fallback-Abschnitt für Bausteine ohne umschließenden Struktur-Knoten."""
        nonlocal allgemein_section_id, next_section_id
        if allgemein_section_id is None:
            next_section_id += 1
            allgemein_section_id = next_section_id
            sections[allgemein_section_id] = {
                "id": allgemein_section_id, "title": "Allgemein", "module_ids": [],
                "component": None, "itemid": None, "parentcmid": None, "modname": None,
            }
        return allgemein_section_id

    # noinspection PyShadowingNames
    def _resolve_target_section(parent_st_idents):
        """Ermittelt die Moodle-section_id, in die ein Baustein anhand seiner
        umschließenden Struktur-Knoten-Kette gehört (siehe st_section_map)."""
        if not parent_st_idents:
            return _get_or_create_allgemein_section()
        target = st_section_map.get(parent_st_idents[-1])
        return target if target is not None else _get_or_create_allgemein_section()

    # Vorab-Pass für kursinterne Verweise (OLAT-ident → Moodle-Modul-ID/Typ),
    # muss VOR der Hauptschleife stehen, weil ein früher Baustein auf einen
    # später erzeugten verlinken kann. Modul-ID = enumerate-Position i,
    # identisch zur Hauptschleife unten. html_cleaner nutzt die Map, um
    # javascript:gotonode(...)-Verweise zu echten Moodle-Links aufzulösen.
    link_map = {}
    for i, node in enumerate(nodes, start=1):
        olat_type = node.get('type', '')
        if olat_type in SKIPPED_OLAT_TYPES:
            # Bekommt trotzdem eine ⚠️-Warn-Platzhalterseite (siehe Hauptschleife
            # unten) - interne Links darauf sollen dort landen statt tot zu sein.
            if "page" in template_mapping:
                ident = node.get('ident')
                if ident:
                    link_map[ident] = (i, "page")
            continue
        if olat_type == 'st' and len(node.get('parent_st_idents', [])) >= MAX_SECTION_DEPTH:
            # Zu tief verschachtelt → bekommt eine 'page' als 🔀-Markierung
            # statt des sonst üblichen 'label' (siehe Hauptschleife unten).
            if "page" in template_mapping:
                ident = node.get('ident')
                if ident:
                    link_map[ident] = (i, "page")
            continue
        # 'page' statt 'label' als Fallback-Ziel (siehe Hauptschleife unten) -
        # muss hier identisch sein, sonst zeigen interne OLAT-Links auf den
        # falschen (unverlinkbaren) Typ. _resolve_moodle_type() statt direkt
        # OLAT_TO_MOODLE_MAPPING, damit ein zum Ordner gewandelter Office-
        # Baustein (siehe dort) auch hier korrekt auf 'folder' zeigt.
        m_type = _resolve_moodle_type(olat_type, node)
        if m_type not in template_mapping:
            m_type = "page"
        if m_type not in template_mapping:
            continue
        ident = node.get('ident')
        if ident:
            link_map[ident] = (i, m_type)

    with tempfile.TemporaryDirectory() as temp_dir:
        file_mgr = FileManager(temp_dir)

        os.makedirs(os.path.join(temp_dir, "contexts", "context_1"), exist_ok=True)
        write_xml(os.path.join(temp_dir, "contexts", "context_1", "context.xml"),
                  '<context id="1" contextlevel="50" instanceid="1"></context>')
        os.makedirs(os.path.join(temp_dir, "course"), exist_ok=True)
        write_xml(os.path.join(temp_dir, "course", "course.xml"),
                  generate_course_xml(now, course_fullname, course_shortname))
        write_xml(os.path.join(temp_dir, "course", "inforef.xml"), "<inforef></inforef>")
        write_xml(os.path.join(temp_dir, "course", "roles.xml"), "<roles></roles>")
        write_xml(os.path.join(temp_dir, "course", "enrolments.xml"), "<enrolments></enrolments>")

        for i, node in enumerate(nodes, start=1):
            olat_type = node.get('type', '')
            parent_st_idents = node.get('parent_st_idents', [])
            node_title = str(node.get('title', 'Unbenannt'))
            raw_title = node_title  # unverändert, für die Erfolgs-Tabelle unten
            if node.get('flattened'):
                # Gehört zu einem zu tief verschachtelten, "hochgezogenen"
                # Container-Knoten (siehe elif olat_type == 'st' unten, der die
                # 🔀-Markierung für den Knoten selbst setzt) - macht diesen
                # Zusammenhang direkt im Kurs sichtbar, nicht nur im Systemprotokoll.
                node_title = f"{FLATTENED_CHILD_MARKER} {node_title}"

            if node.get('has_children') and len(parent_st_idents) < MAX_SECTION_DEPTH:
                # Nicht nur 'st' (reiner Struktur-Container) öffnet eine neue
                # Ebene, sondern jeder Knoten mit eigenen Kindern (z.B. eine
                # Einzelseite mit angehängtem Forum) - der Knoten fällt unten
                # trotzdem normal durch und bekommt zusätzlich seine eigene
                # Aktivität; die landet dann in seinem eigenen neuen
                # Abschnitt/Unterabschnitt (current_target_section_id unten).
                if len(parent_st_idents) == 0:
                    next_section_id += 1
                    new_section_id = next_section_id
                    sections[new_section_id] = {
                        "id": new_section_id, "title": node.get('title', f'Abschnitt {new_section_id}'),
                        "module_ids": [], "component": None, "itemid": None,
                        "parentcmid": None, "modname": None,
                    }
                else:
                    next_subsection_id += 1
                    new_section_id = next_subsection_id
                    # Verschachtelter Container (Ebene 2) → Moodle-Unterabschnitt
                    # (mod_subsection, Core seit Moodle 4.4). Die Aktivität
                    # selbst liegt im umschließenden Abschnitt, der neue
                    # Abschnitt ist über component/itemid mit ihr verknüpft
                    # (siehe generate_section_xml) - technisch bleiben alle
                    # Abschnitte eine flache Liste, Moodle zeigt sie nur
                    # optisch eingerückt an.
                    subsection_instance_counter += 1
                    subsection_module_id = next_free_module_id
                    next_free_module_id += 1
                    parent_section_id = st_section_map[parent_st_idents[0]]

                    sub_context_id = context_id_counter
                    context_id_counter += 1
                    sub_a_path = os.path.join(temp_dir, "activities", f"subsection_{subsection_module_id}")
                    shutil.copytree(template_mapping["subsection"], sub_a_path)
                    modify_module_xml(os.path.join(sub_a_path, "module.xml"),
                                      subsection_module_id, parent_section_id, now)
                    modify_subsection_xml(os.path.join(sub_a_path, "subsection.xml"),
                                          subsection_instance_counter, subsection_module_id,
                                          sub_context_id, node_title, now)
                    os.makedirs(os.path.join(temp_dir, "contexts", f"context_{sub_context_id}"), exist_ok=True)
                    write_xml(os.path.join(temp_dir, "contexts", f"context_{sub_context_id}", "context.xml"),
                              f'<context id="{sub_context_id}" contextlevel="70" '
                              f'instanceid="{subsection_module_id}"></context>')

                    sections[new_section_id] = {
                        "id": new_section_id, "title": node.get('title', f'Unterabschnitt {new_section_id}'),
                        "module_ids": [], "component": "mod_subsection", "itemid": subsection_instance_counter,
                        "parentcmid": subsection_module_id, "modname": "subsection",
                    }
                    sections[parent_section_id]["module_ids"].append(subsection_module_id)
                    processed_activities.append(
                        (subsection_module_id, "subsection", parent_section_id, node_title))

                st_section_map[node['ident']] = new_section_id
                current_target_section_id = new_section_id
            elif olat_type == 'st':
                print(f"[!] Struktur '{node_title}' liegt tiefer als {MAX_SECTION_DEPTH} Ebenen "
                      f"verschachtelt – Moodle unterstützt das nicht, Inhalt bleibt im "
                      f"umschließenden Abschnitt.")
                current_target_section_id = _resolve_target_section(parent_st_idents)

                boundary_link = None
                if "page" in template_mapping:
                    # 'page' statt des sonst üblichen 'label'-Fallthroughs
                    # (siehe OLAT_TO_MOODLE_MAPPING["st"]) - Labels haben in
                    # Moodle keine eigene View-Seite und wären vom
                    # Systemprotokoll aus nicht verlinkbar (siehe
                    # build_flattened_boundary_html). 'continue' unten
                    # verhindert, dass zusätzlich noch das generische
                    # label-Fallthrough für denselben Knoten läuft.
                    boundary_context_id = context_id_counter
                    context_id_counter += 1
                    boundary_context_path = os.path.join(temp_dir, "contexts", f"context_{boundary_context_id}")
                    os.makedirs(boundary_context_path, exist_ok=True)
                    write_xml(os.path.join(boundary_context_path, "context.xml"),
                              f'<context id="{boundary_context_id}" contextlevel="70" instanceid="{i}"></context>')
                    boundary_a_path = os.path.join(temp_dir, "activities", f"page_{i}")
                    shutil.copytree(template_mapping["page"], boundary_a_path)
                    modify_module_xml(os.path.join(boundary_a_path, "module.xml"), i,
                                      current_target_section_id, now)
                    boundary_title = f"{FLATTENED_BOUNDARY_MARKER} {node_title}"
                    modify_activity_xml(os.path.join(boundary_a_path, "page.xml"), "page", i,
                                        boundary_context_id, boundary_title, now, olat_type, False,
                                        build_flattened_boundary_html(), "")
                    rewrite_inforef_xml(os.path.join(boundary_a_path, "inforef.xml"), [])
                    sections[current_target_section_id]["module_ids"].append(i)
                    processed_activities.append((i, "page", current_target_section_id, boundary_title))
                    boundary_link = f"$@PAGEVIEWBYID*{i}@$"

                flattened_structures.append({
                    'location': _format_location(node_title, parent_st_idents),
                    'link': boundary_link,
                })
                continue
            else:
                current_target_section_id = _resolve_target_section(parent_st_idents)

            if olat_type in SKIPPED_OLAT_TYPES:
                # Bekommt trotzdem eine echte Aktivität an seiner Original-
                # Position im Kurs statt spurlos zu verschwinden - eine
                # ⚠️-Warn-Seite mit Handlungsempfehlung (siehe
                # build_unsupported_placeholder_html). 'page' statt 'label',
                # damit der Systemprotokoll-Eintrag unten wirklich dorthin
                # verlinken kann (label hat keine eigene View-Seite in Moodle).
                page_available = "page" in template_mapping
                skipped_elements.append({
                    'title': _format_location(node_title, parent_st_idents),
                    'type': olat_type, 'ident': node.get('ident'), 'symbol': WARNING_SYMBOL,
                    'link': f"$@PAGEVIEWBYID*{i}@$" if page_available else None,
                })
                if page_available:
                    context_id = context_id_counter
                    context_id_counter += 1
                    context_path = os.path.join(temp_dir, "contexts", f"context_{context_id}")
                    os.makedirs(context_path, exist_ok=True)
                    write_xml(os.path.join(context_path, "context.xml"),
                              f'<context id="{context_id}" contextlevel="70" instanceid="{i}"></context>')
                    a_path = os.path.join(temp_dir, "activities", f"page_{i}")
                    shutil.copytree(template_mapping["page"], a_path)
                    modify_module_xml(os.path.join(a_path, "module.xml"), i, current_target_section_id, now)
                    modify_activity_xml(os.path.join(a_path, "page.xml"), "page", i, context_id,
                                        f"⚠️ {node_title}", now, olat_type, False,
                                        build_unsupported_placeholder_html(olat_type), "")
                    rewrite_inforef_xml(os.path.join(a_path, "inforef.xml"), [])
                    sections[current_target_section_id]["module_ids"].append(i)
                    processed_activities.append((i, "page", current_target_section_id, f"⚠️ {node_title}"))
                continue

            # Fallback-Ziel bewusst 'page' statt 'label': label-Aktivitäten
            # haben in Moodle keine eigene View-Seite (has_view() == false)
            # und wären vom Systemprotokoll aus nicht verlinkbar.
            m_type = _resolve_moodle_type(olat_type, node)
            is_fallback = olat_type not in OLAT_TO_MOODLE_MAPPING
            if m_type not in template_mapping:
                print(f"[!] Moodle-Modul '{m_type}' nicht im Template. Fallback auf 'page'.")
                m_type = "page"
                is_fallback = True

            fallback_location = None
            if is_fallback:
                # Typ nicht erkannt/gemappt - anders als SKIPPED_OLAT_TYPES wird
                # trotzdem versucht, echten Inhalt zu übernehmen (unten), nur der
                # Bausteintyp selbst war unbekannt. Breadcrumb VOR dem ❓-Präfix
                # bilden (sonst würde das Symbol in der Protokoll-Zeile
                # auftauchen); der Systemprotokoll-Eintrag selbst kommt erst
                # ganz unten NACH erfolgreichem Aufbau - sonst gäbe es bei einem
                # späteren Konvertierungsfehler zwei Einträge für denselben Knoten.
                fallback_location = _format_location(node_title, parent_st_idents)
                node_title = f"{UNRECOGNIZED_TYPE_MARKER} {node_title}"

            if olat_type == "document" and m_type == "folder":
                # Zum Ordner gewandelter Office-Baustein (siehe
                # _resolve_moodle_type) - sichtbar kennzeichnen, sonst nicht
                # von einem echten OLAT-Ordner-Baustein (bc/pf) zu unterscheiden.
                node_title = f"{OFFICE_DOCUMENT_MARKER} {node_title}"

            src_dir = template_mapping.get(m_type)
            if not src_dir:
                # Auch das label-Template fehlt - darf nicht stillschweigend
                # passieren, sonst verschwindet der Baustein unbemerkt.
                print(f"[!] Kein Template für '{m_type}' vorhanden – "
                      f"'{node_title}' ({olat_type}) wird übersprungen.")
                # 'st'-Knoten zählen nie als Kurselement (siehe total_content_count
                # unten, das 'st' explizit ausschließt) - sonst würde ein Fehlschlag
                # beim Struktur-eigenen Label die Zählung verzerren.
                if olat_type != 'st':
                    skipped_elements.append({'title': _format_location(node_title, parent_st_idents),
                                             'type': f"{olat_type}, Template fehlt", 'ident': node.get('ident')})
                continue

            try:
                html_content, unique_attachments, node_removed_links, empty_dirs, content_issue = (
                    build_node_content(node, manifest, m_type, olat_type, link_map))
                if node_removed_links:
                    removed_links_log.append({'title': node_title, 'links': node_removed_links})

                context_id = context_id_counter
                context_id_counter += 1
                component_type = f"mod_{m_type}"
                filearea = "content" if m_type in ["page", "resource", "folder"] else "intro"
                node_file_ids = []

                context_path = os.path.join(temp_dir, "contexts", f"context_{context_id}")
                os.makedirs(context_path, exist_ok=True)
                write_xml(os.path.join(context_path, "context.xml"),
                          f'<context id="{context_id}" contextlevel="70" instanceid="{i}"></context>')

                if unique_attachments or empty_dirs:
                    dir_id = file_mgr.add_moodle_directory(context_id, component_type, filearea, 0, now)
                    node_file_ids.append(dir_id)

                    created_subdir_paths = set()

                    # noinspection PyShadowingNames
                    def _ensure_subdir_markers(relpath):
                        """Legt für relpath UND alle Elternpfade je einen Verzeichnis-
                        Marker an - ohne den zeigt Moodle den Unterordner gar
                        nicht erst an (siehe manifest.get_node_folder_tree)."""
                        if not relpath:
                            return
                        parts = relpath.split('/')
                        for depth in range(1, len(parts) + 1):
                            sub_relpath = '/'.join(parts[:depth])
                            if sub_relpath in created_subdir_paths:
                                continue
                            created_subdir_paths.add(sub_relpath)
                            sub_id = file_mgr.add_moodle_directory(
                                context_id, component_type, filearea, 0, now,
                                filepath=f"/{sub_relpath}/")
                            node_file_ids.append(sub_id)

                    for attach in unique_attachments:
                        relpath = attach.get("relpath", "")
                        _ensure_subdir_markers(relpath)
                        file_id = file_mgr.add_moodle_file(
                            source_content=attach["data"], filename=attach["name"],
                            contextid=context_id, component=component_type, filearea=filearea,
                            itemid=0, now=now, filepath=f"/{relpath}/" if relpath else "/"
                        )
                        node_file_ids.append(file_id)

                    for empty_dir in empty_dirs:
                        _ensure_subdir_markers(empty_dir)

                a_path = os.path.join(temp_dir, "activities", f"{m_type}_{i}")
                shutil.copytree(src_dir, a_path)
                modify_module_xml(os.path.join(a_path, "module.xml"), i, current_target_section_id, now)

                quiz_result = None
                if olat_type in QUIZ_OLAT_TYPES and m_type == "quiz":
                    quiz_result = qti_quiz_builder.build_quiz_activity(
                        node, manifest, context_id, i, qti_id_gen, now, file_mgr,
                        report_sink=quiz_reports)
                    if quiz_result is None:
                        # Testpaket nicht auflösbar oder keine unterstützten Fragen -
                        # dieselbe sichtbare Warnung wie beim cp-Fallback unten,
                        # nur direkt im html_content (landet gleich in <intro>,
                        # da quiz_result None den generischen else-Zweig nimmt).
                        content_issue = "Testpaket nicht auflösbar oder keine unterstützten Fragen"
                        html_content = (
                            '<p style="color:red;"><strong>Achtung:</strong> Der Inhalt dieses '
                            'Tests konnte nicht automatisch übernommen werden (Testpaket nicht '
                            'auflösbar oder keine unterstützten Fragen) – das Quiz ist leer, '
                            'bitte manuell nachbauen.</p>'
                        ) + html_content

                book_result = None
                if olat_type == "cp" and m_type == "book":
                    # html_content ist main.py's bereits sanitisierte Beschreibung
                    # (Bilder darin unter component=mod_book/filearea=intro/
                    # itemid=0 registriert) - build_book_activity nimmt sie
                    # unverändert als <intro>, damit die Bildpfade passen.
                    book_result = cp_book_builder.build_book_activity(
                        node, manifest, context_id, i, now, file_mgr, qti_id_gen,
                        intro_html=html_content, link_map=link_map)
                    if book_result is None:
                        # Sichtbare Warnung entsteht schon unten in
                        # cp_book_builder.build_fallback_book_xml - hier nur fürs
                        # Systemprotokoll vermerken.
                        content_issue = "Content-Package nicht auflösbar"

                if quiz_result is not None:
                    # Echte Fragen statt der leeren generischen Quiz-Hülle -
                    # quiz.xml wird komplett neu geschrieben statt gepatcht.
                    write_xml(os.path.join(a_path, "quiz.xml"), quiz_result["quiz_xml"])
                    all_question_categories_xml.append(quiz_result["category_entries_xml"])
                    rewrite_inforef_xml(os.path.join(a_path, "inforef.xml"), node_file_ids,
                                        question_category_ids=quiz_result["category_ids"])
                elif m_type == "book":
                    # book.xml wird IMMER frisch geschrieben statt gepatcht -
                    # das kopierte Template enthält echten Beispiel-Lehrinhalt
                    # (Muster-Kapitel), der nie unverändert stehen bleiben darf,
                    # auch nicht im CP-Paket-Fehlerfall (book_result is None).
                    if book_result is not None:
                        write_xml(os.path.join(a_path, "book.xml"), book_result["book_xml"])
                        rewrite_inforef_xml(os.path.join(a_path, "inforef.xml"),
                                            node_file_ids + book_result["file_ids"])
                        if book_result["removed_links"]:
                            removed_links_log.append({'title': node_title,
                                                      'links': book_result["removed_links"]})
                        # Kapitel-Dateien zählen als verwendet, sonst tauchen
                        # z.B. PDFs aus dem CP-Paket zusätzlich als
                        # "verwaiste Dateien" im Systemprotokoll auf.
                        used_filenames.update(book_result["used_filenames"])
                    else:
                        # Sichtbarer Warnhinweis IM Buch selbst (siehe
                        # cp_book_builder.build_fallback_book_xml) statt eines
                        # is_fallback-Banners - is_fallback ist für cp immer
                        # False (cp steht ja im Mapping), das Buch bekommt den
                        # Hinweis stattdessen direkt als Kapitelinhalt.
                        fallback_xml = cp_book_builder.build_fallback_book_xml(
                            i, context_id, node_title, html_content, now, qti_id_gen)
                        write_xml(os.path.join(a_path, "book.xml"), fallback_xml)
                        rewrite_inforef_xml(os.path.join(a_path, "inforef.xml"), node_file_ids)
                else:
                    if m_type == "label" and olat_type != 'st':
                        # 'label' steht in OLAT_TO_MOODLE_MAPPING nie für einen
                        # echten OLAT-Bausteintyp, sondern immer nur als
                        # Auffangbecken für Typen ohne Moodle-Äquivalent (co,
                        # en, members, cal, checklist, ms, den) - Titel/Text
                        # bleibt erhalten, die eigentliche Funktion (E-Mail
                        # verschicken, Einschreiben, Kalendereinträge, ...)
                        # geht komplett verloren. Darf deshalb nicht als
                        # ✅ durchgehen.
                        content_issue = "Kein Moodle-Baustein mit eigener Funktion – nur Titel als Textfeld übernommen"
                        olat_name = OLAT_NAMES.get(olat_type, olat_type)
                        html_content = (
                            f'<p style="color:red;"><strong>Achtung:</strong> Für diesen '
                            f'OLAT-Bausteintyp ({olat_name}) gibt es keine funktionale Moodle-'
                            f'Entsprechung – nur Titel/Beschreibung wurden als Textfeld '
                            f'übernommen, die eigentliche Funktion fehlt. Bitte manuell prüfen, '
                            f'ob und wie das nachgebaut werden muss.</p>'
                        ) + html_content
                    if m_type == "url" and not node.get('url', ''):
                        # Keine echte Adresse hinterlegt - moodle_xml setzt gleich
                        # http://example.invalid/ als Ziel, hier zusätzlich sichtbar
                        # im Aktivitätstext, damit es nicht nur im Link selbst auffällt.
                        content_issue = "Keine externe URL hinterlegt"
                        html_content = (
                            '<p style="color:red;"><strong>Achtung:</strong> Für diesen '
                            'Baustein war in OLAT keine gültige externe Adresse hinterlegt – '
                            'der Link führt aktuell absichtlich ins Leere '
                            '(http://example.invalid/). Bitte manuell die richtige URL '
                            'eintragen.</p>'
                        ) + html_content
                    modify_activity_xml(os.path.join(a_path, f"{m_type}.xml"), m_type, i, context_id,
                                        node_title, now, olat_type, is_fallback, html_content,
                                        node.get('url', ''))
                    if olat_type == 'info' and m_type == 'forum':
                        # OLATs "Mitteilungen" entsprechen inhaltlich Moodles
                        # Ankündigungen - laufen aber über dasselbe forum-
                        # Template wie ein normales Forum, daher hier gezielt
                        # nachträglich zu type='news' + Auto-Abo umgeschaltet.
                        set_forum_announcement_type(os.path.join(a_path, f"{m_type}.xml"))
                    rewrite_inforef_xml(os.path.join(a_path, "inforef.xml"), node_file_ids)

                sections[current_target_section_id]["module_ids"].append(i)
                processed_activities.append((i, m_type, current_target_section_id, node_title))
                view_token = MODULE_VIEW_TOKENS.get(m_type)
                node_link = f"$@{view_token}*{i}@$" if view_token else None
                if fallback_location is not None:
                    # Nur bis hierher gekommen (kein Konvertierungsfehler) →
                    # jetzt erst den Systemprotokoll-Eintrag setzen, m_type ist
                    # garantiert 'page' (siehe is_fallback oben) → verlinkbar.
                    skipped_elements.append({
                        'title': fallback_location,
                        'type': f"{olat_type}, Unbekannter Bausteintyp – Inhalt trotzdem übernommen",
                        'ident': node.get('ident'), 'symbol': UNRECOGNIZED_TYPE_MARKER,
                        'link': f"$@PAGEVIEWBYID*{i}@$",
                    })
                elif content_issue is not None and olat_type != 'st':
                    # Bausteintyp erkannt, Aktivität wurde angelegt - aber der
                    # eigentliche Inhalt fehlt (Quiz/Buch nicht auflösbar,
                    # referenzierte Datei fehlt, keine URL hinterlegt). Zählt
                    # bewusst NICHT als ✅, sonst würde "Aktivität existiert"
                    # mit "Inhalt ist tatsächlich angekommen" verwechselt -
                    # dasselbe ❓-Symbol wie bei unbekannten Typen, weil die
                    # Bedeutung ("bitte gegenprüfen") hier genauso zutrifft.
                    skipped_elements.append({
                        'title': _format_location(node_title, parent_st_idents),
                        'type': f"{olat_type}, {content_issue}",
                        'ident': node.get('ident'), 'symbol': UNRECOGNIZED_TYPE_MARKER,
                        'link': node_link,
                    })
                elif olat_type != 'st':
                    # Sauberer Erfolgsfall (Typ erkannt, Inhalt angekommen) - für
                    # die ✅-Erfolgstabelle im Systemprotokoll. Derselbe
                    # Token-Katalog wie für echte interne OLAT-Links
                    # (html_cleaner.py) - nicht jeder Moodle-Typ hat eine eigene
                    # View-Seite (z.B. 'label').
                    # 'st' explizit ausgeschlossen: Struktur-Knoten durchlaufen
                    # denselben Erfolgspfad (für ihr eigenes Label mit Intro-Text),
                    # zählen aber nicht als "Kurselement" - total_content_count
                    # weiter unten schließt 'st' ebenfalls aus, sonst wäre die
                    # ✅-Zählung größer als die Gesamtzahl (Zähler > Nenner).
                    transferred_elements.append({
                        'olat_type': olat_type, 'olat_name': raw_title,
                        'moodle_type': m_type, 'moodle_name': node_title,
                        'link': node_link,
                    })
                # Erst NACH erfolgreichem Abschluss als "verwendet" merken -
                # sonst würde eine Datei eines später abstürzenden Bausteins
                # weder in dessen Aktivität landen NOCH im Verwaiste-Dateien-
                # Ordner (used_filenames schließt sie dort aus).
                for attach in unique_attachments:
                    used_filenames.add(attach["name"])
            except Exception as e:
                print(f"[!] Fehler bei Baustein '{node_title}' ({olat_type}): "
                      f"{type(e).__name__}: {e} – übersprungen.")
                # 'st' zählt nie als Kurselement (siehe Kommentar beim Erfolgsfall
                # oben) - auch im Fehlerfall nicht, sonst driftet total_content_count
                # (schließt 'st' aus) gegen skipped_elements auseinander.
                if olat_type != 'st':
                    skipped_elements.append({'title': _format_location(node_title, parent_st_idents),
                                             'type': f"{olat_type}, Konvertierungsfehler", 'ident': node.get('ident')})
                shutil.rmtree(os.path.join(temp_dir, "activities", f"{m_type}_{i}"),
                              ignore_errors=True)
                continue

        _doc_exts = ('.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.txt', '.rtf')
        orphaned_files = {}
        for path, data in manifest.vfs.items():
            fname = os.path.basename(path.split('|')[-1])
            if (fname
                    and not fname.startswith('._oo_meta_')
                    and fname != '.DS_Store'
                    and 'oonode.zip' not in path
                    and fname.lower().endswith(_doc_exts)
                    and fname not in used_filenames):
                if fname in orphaned_files:
                    # Dedup läuft nur über den Dateinamen - bei gleichem Namen
                    # mit anderem Inhalt würde die zweite Datei sonst
                    # kommentarlos verschwinden.
                    if orphaned_files[fname] != data:
                        print(f"[!] Namenskonflikt bei verwaisten Dateien: '{fname}' "
                              f"existiert mehrfach mit unterschiedlichem Inhalt – "
                              f"nur die erste Version wird angehängt ({path} entfällt).")
                    continue
                orphaned_files[fname] = data

        _disambiguate_skipped_elements(skipped_elements)

        if (skipped_elements or orphaned_files or removed_links_log or flattened_structures
                or transferred_elements):
            # next_section_id statt max(sections)+1: Unterabschnitte liegen
            # bewusst in einem weit entfernten eigenen Nummernkreis (siehe
            # next_subsection_id oben) - max(sections) läge also fast immer
            # dort drin, das Systemprotokoll bekäme dann selbst eine
            # riesige Abschnittsnummer statt normal ans Ende der echten
            # Abschnittsfolge angehängt zu werden.
            next_section_id += 1
            protocol_section_id = next_section_id
            sections[protocol_section_id] = {
                "id": protocol_section_id,
                "title": "Systemprotokoll (Konvertierung)",
                "module_ids": [], "component": None, "itemid": None,
                "parentcmid": None, "modname": None,
            }
            total_content_count = sum(1 for n in nodes if n.get('type') != 'st')
            if len(transferred_elements) > total_content_count:
                # Darf strukturell nie vorkommen (Zähler > Nenner ergibt keinen
                # Sinn) - lauter Hinweis statt stillschweigend falscher Zahlen im
                # Systemprotokoll, egal wodurch die Inkonsistenz entstünde.
                print(f"[DEBUG] WARNUNG: Erfolgs-Zählung im Systemprotokoll ergibt "
                      f"{len(transferred_elements)} von {total_content_count} Kurselementen – "
                      f"das ist unmöglich (mehr übertragen als insgesamt vorhanden). "
                      f"Bitte Zähl-Logik in main.py prüfen, BEVOR diese .mbz verwendet wird.")
            write_protocol_activities(
                temp_dir, template_mapping, file_mgr, sections, processed_activities,
                skipped_elements, orphaned_files, removed_links_log, flattened_structures,
                transferred_elements, total_content_count,
                protocol_section_id, next_free_module_id, context_id_counter, now
            )

        # Tote interne Verweise entschärfen: link_map wurde vor der
        # Hauptschleife gebaut, einzelne Ziel-Bausteine können danach
        # abgestürzt sein - deren Platzhalter zeigen sonst ins Leere.
        valid_module_ids = {act_id for act_id, _, _, _ in processed_activities}
        _neutralize_dead_internal_links(temp_dir, valid_module_ids)

        for sec_id, sec_data in sections.items():
            sec_dir = os.path.join(temp_dir, "sections", f"section_{sec_id}")
            os.makedirs(sec_dir, exist_ok=True)
            write_xml(os.path.join(sec_dir, "inforef.xml"), "<inforef></inforef>")
            write_xml(os.path.join(sec_dir, "roles.xml"), "<roles></roles>")
            write_xml(os.path.join(sec_dir, "section.xml"),
                      generate_section_xml(sec_id, sec_id, now, sec_data["title"], sec_data["module_ids"],
                                          component=sec_data.get("component"), itemid=sec_data.get("itemid")))

        print("[DEBUG] Schreibe Metadaten...")
        write_xml(os.path.join(temp_dir, "files.xml"), file_mgr.generate_files_xml())
        write_xml(os.path.join(temp_dir, "moodle_backup.xml"),
                  generate_moodle_backup_xml(processed_activities, sections, now, backup_id,
                                             course_fullname, course_shortname,
                                             has_questions=bool(all_question_categories_xml)))
        create_empty_meta_files(temp_dir, question_categories_xml='\n'.join(all_question_categories_xml))

        validate_moodle_backup_integrity(temp_dir)
        validate_conversion_completeness(temp_dir, processed_activities, quiz_reports)

        print(f"[*] Packe Archiv: {output_mbz_path}")
        # Zielordner kann fehlen (z.B. wenn er über die GUI vorbelegt wurde,
        # aber auf diesem Rechner - anders als bei der Entwicklung - noch
        # nicht existiert, etwa ein umbenannter/fehlender Downloads-Ordner) -
        # tarfile.open() legt ihn nicht selbst an und würde sonst mit
        # FileNotFoundError abbrechen, nachdem die ganze Konvertierung
        # bereits gelaufen ist.
        output_dir = os.path.dirname(os.path.abspath(output_mbz_path))
        os.makedirs(output_dir, exist_ok=True)
        with tarfile.open(output_mbz_path, "w:gz") as tar:
            for dir_path, _dirs, files in os.walk(temp_dir):
                for file in files:
                    full_path = os.path.join(dir_path, file)
                    rel_path = os.path.relpath(full_path, temp_dir).replace("\\", "/")
                    tar.add(full_path, arcname=rel_path)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Konvertiert einen OpenOLAT-Kursexport (.zip) in ein Moodle-Backup (.mbz).")
    parser.add_argument("input_zip", nargs="?", default=OLAT_INPUT_FILE,
                        help="Pfad zum OLAT-Export (Standard: config.OLAT_INPUT_FILE)")
    parser.add_argument("output_mbz", nargs="?", default=MOODLE_OUTPUT_FILE,
                        help="Ziel-.mbz (Standard: config.MOODLE_OUTPUT_FILE)")
    args = parser.parse_args()
    if not args.input_zip:
        parser.error("Kein OLAT-Export angegeben (config.OLAT_INPUT_FILE ist leer) – "
                     "Pfad als erstes Argument übergeben.")
    convert_olat_to_moodle(args.input_zip, args.output_mbz)
