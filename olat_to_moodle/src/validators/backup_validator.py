"""Prüft das fertig geschriebene Backup-Verzeichnis auf kaputte Dateireferenzen.

Wird von main.py aufgerufen, nachdem alle XML-Dateien geschrieben sind, aber
bevor sie zu einer .mbz gepackt werden – findet fehlende physische Dateien
und @@PLUGINFILE@@-Verweise, die in files.xml keine Entsprechung haben,
BEVOR der Import in Moodle fehlschlägt.
"""

import os
import re
import html
import urllib.parse
import xml.etree.ElementTree as ET


def validate_moodle_backup_integrity(temp_dir: str):
    """Zwei Schritte: (1) jede in files.xml registrierte Datei muss physisch
    unter files/<hash[:2]>/<hash> liegen, und mindestens ein Verzeichnismarker
    (filename='.') muss existieren – sonst verwirft Moodle beim Restore ALLE
    Dateien. (2) jede Aktivitäts-XML nach @@PLUGINFILE@@-Referenzen
    durchsuchen und prüfen, ob der Dateiname im selben Kontext wie die
    Aktivität registriert ist – eine Datei kann in mehreren Kontexten
    vorkommen, zählt aber nur im richtigen, sonst zeigt Moodle ein kaputtes
    Bild trotz Eintrag in files.xml.

    Alle Funde werden nur geloggt (kein Abbruch), damit der Nutzer alle
    Probleme auf einmal sieht."""
    print("\n[DEBUG] Starte lokale Moodle-Struktur-Validierung...")

    files_xml_path = os.path.join(temp_dir, "files.xml")
    if not os.path.exists(files_xml_path):
        print("[FEHLER] files.xml existiert nicht – das Backup ist unbrauchbar.")
        return

    tree = ET.parse(files_xml_path)
    root = tree.getroot()

    # Dateiname → Menge der Kontext-IDs, unter denen er im WURZELPFAD eines
    # Dateibereichs registriert ist. Nur der zählt: ein @@PLUGINFILE@@-Verweis
    # ohne Pfadangabe löst immer dort auf, eine gleichnamige Datei in einem
    # Unterordner erfüllt ihn nicht.
    registered_files = {}
    # Moodle braucht pro (contextid, component, filearea, itemid, filepath)
    # GENAU einen Verzeichnis-Marker (filename='.'), sonst verwirft es beim
    # Restore alle Dateien GENAU DIESES Bereichs (siehe
    # file_manager.add_moodle_directory). Deshalb je Bereich vergleichen,
    # nicht global zählen – ein einzelner fehlender Marker fiele sonst nicht
    # auf, obwohl in Moodle die Dateien dieses Bereichs verschwinden.
    areas_with_marker = set()
    areas_with_files = {}

    def _area_of(node):
        """(contextid, component, filearea, itemid, filepath) eines Eintrags."""
        return tuple((node.findtext(tag) or '') for tag in
                     ('contextid', 'component', 'filearea', 'itemid', 'filepath'))

    for file_node in root.findall('file'):
        filename = file_node.find('filename').text
        contenthash = file_node.find('contenthash').text
        contextid = file_node.find('contextid').text

        if filename == '.':
            areas_with_marker.add(_area_of(file_node))
            continue

        if (file_node.findtext('filepath') or '/') == '/':
            registered_files.setdefault(filename, set()).add(contextid)
        areas_with_files.setdefault(_area_of(file_node), filename)

        expected_path = os.path.join(temp_dir, "files", contenthash[:2], contenthash)
        if not os.path.exists(expected_path):
            print(f"[FEHLER] Physische Datei fehlt: {expected_path} (Referenz: {filename})")

    for area, example in sorted(areas_with_files.items()):
        if area in areas_with_marker:
            continue
        contextid, component, filearea, itemid, filepath = area
        print(f"[FEHLER] Kein Verzeichnis-Marker für {component}/{filearea} "
              f"(Kontext {contextid}, itemid {itemid}, Pfad '{filepath}') – Moodle "
              f"verwirft beim Restore alle Dateien dieses Bereichs, z.B. '{example}'.")

    skip_files = {'module.xml', 'inforef.xml', 'roles.xml', 'grade_history.xml'}

    # Alle von Aktivitäten tatsächlich beanspruchten Kontext-IDs sammeln, um
    # danach verwaiste contexts/context_N-Ordner zu erkennen (entstehen z.B.,
    # wenn ein Baustein mitten in der Verarbeitung abstürzt: sein context.xml
    # ist schon geschrieben, die Aktivität aber verworfen).
    used_context_ids = set()

    # Blöcke (course/blocks/...) liegen NICHT unter activities/ – ohne diesen
    # eigenen Scan würde jeder Block-Kontext fälschlich als "verwaist"
    # gemeldet, obwohl block.xml ihn ganz normal referenziert.
    blocks_dir = os.path.join(temp_dir, "course", "blocks")
    if os.path.exists(blocks_dir):
        for block_folder in os.listdir(blocks_dir):
            block_xml_path = os.path.join(blocks_dir, block_folder, "block.xml")
            if not os.path.exists(block_xml_path):
                continue
            try:
                block_root = ET.parse(block_xml_path).getroot()
            except ET.ParseError:
                continue
            if block_root.get('contextid'):
                used_context_ids.add(block_root.get('contextid'))

    activities_dir = os.path.join(temp_dir, "activities")
    if not os.path.exists(activities_dir):
        print("[DEBUG] Validierung abgeschlossen.\n")
        return

    for act_folder in os.listdir(activities_dir):
        act_path = os.path.join(activities_dir, act_folder)
        if not os.path.isdir(act_path):
            continue

        # Kontext-ID der Aktivität aus dem contextid-Attribut ihres
        # <activity>-Wurzelelements (steht in genau einer der XML-Dateien
        # des Ordners, meist <modulename>.xml).
        act_contextid = None
        for xml_file in os.listdir(act_path):
            if not xml_file.endswith('.xml') or xml_file in skip_files:
                continue
            try:
                act_root = ET.parse(os.path.join(act_path, xml_file)).getroot()
            except ET.ParseError:
                continue
            if act_root.get('contextid'):
                act_contextid = act_root.get('contextid')
                break
        if act_contextid is not None:
            used_context_ids.add(act_contextid)

        for xml_file in os.listdir(act_path):
            if not xml_file.endswith('.xml') or xml_file in skip_files:
                continue

            xml_path = os.path.join(act_path, xml_file)
            try:
                with open(xml_path, 'r', encoding='utf-8') as handle:
                    content = handle.read()
            except Exception as e:
                print(f"[!] Lese-Fehler bei {xml_path}: {e}")
                continue

            for match in re.findall(r'@@PLUGINFILE@@/([^"\'<]+)', content):
                decoded = urllib.parse.unquote(html.unescape(match))
                contexts = registered_files.get(decoded)
                if not contexts:
                    print(f"[FEHLER] '{decoded}' in {act_folder}/{xml_file} fehlt in files.xml.")
                elif act_contextid is not None and act_contextid not in contexts:
                    print(f"[FEHLER] '{decoded}' in {act_folder}/{xml_file} ist in files.xml "
                          f"nur unter Kontext {sorted(contexts)} registriert, die Aktivität hat "
                          f"aber Kontext {act_contextid} – Datei wäre in Moodle unsichtbar.")

    # Verwaiste Kontexte: ein contexts/context_N-Ordner ohne zugehörige
    # Aktivität. context_1 ist der Kurs-Kontext (contextlevel=50) und gehört
    # zu keiner Aktivität – der bleibt außen vor.
    contexts_dir = os.path.join(temp_dir, "contexts")
    if os.path.exists(contexts_dir):
        for ctx_folder in os.listdir(contexts_dir):
            if not ctx_folder.startswith("context_"):
                continue
            ctx_id = ctx_folder[len("context_"):]
            if ctx_id == "1" or ctx_id in used_context_ids:
                continue
            print(f"[!] Verwaister Kontext '{ctx_folder}' – keine Aktivität "
                  f"nutzt Kontext {ctx_id} (vermutlich abgestürzter Baustein).")

    print("[DEBUG] Validierung abgeschlossen.\n")
