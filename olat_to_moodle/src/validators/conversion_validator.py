"""Soll-Ist-Validierung: prüft, ob im fertigen Backup wirklich alles
angekommen ist, was aus dem OLAT-Kurs kommen sollte - Datenverlust-Prüfung,
nicht Datei-Referenz-Prüfung (das macht backup_validator.py).

Kernfrage laut Projektvorgabe: OLAT-Kurs auslesen → Mapping → was ist das
erwartbare Ergebnis? Fragen sind grundsätzlich optional, ABER wenn ein
OLAT-Test Fragen enthält, MÜSSEN sie im Quiz landen - fehlen sie, ist das der
schwerwiegendste Bug (ein leeres Quiz ist strukturell wohlgeformt und würde
von den anderen Validatoren durchgewunken).

Bewusst als Gegenprobe gebaut: das "Ist" wird frisch aus den geschriebenen
XML-Dateien gelesen, nicht aus den Laufzeit-Listen der Konvertierung - so
fällt auch ein Fehler auf, bei dem die interne Buchhaltung eine Aktivität als
gebaut führt, die Datei aber fehlt/leer ist.
"""

import os
import xml.etree.ElementTree as ET


def _count_question_instances(temp_dir: str, module_id: int) -> int:
    """Zählt <question_instance> in der geschriebenen quiz.xml eines Quiz-
    Bausteins. -1, wenn die Datei fehlt/nicht lesbar ist (getrennt vom
    legitimen 0 = Quiz ohne Fragen)."""
    quiz_xml = os.path.join(temp_dir, "activities", f"quiz_{module_id}", "quiz.xml")
    if not os.path.exists(quiz_xml):
        return -1
    try:
        root = ET.parse(quiz_xml).getroot()
    except ET.ParseError:
        return -1
    return len(root.findall(".//question_instances/question_instance"))


def _validate_question_completeness(temp_dir: str, quiz_reports: list) -> None:
    """Pro OLAT-Test: erkannte Fragen (Soll) gegen die im geschriebenen Quiz
    tatsächlich vorhandenen (Ist) abgleichen. Unterscheidet dokumentierten
    Verlust (Fragetyp ohne Moodle-Äquivalent → Warnung) von echtem Verlust
    (Fragen verschwinden unerklärt → Fehler)."""
    for rep in quiz_reports:
        title = rep['title']
        recognized = rep['recognized']
        emitted = rep['emitted']
        unsupported = rep['unsupported']

        if not rep['resolved']:
            print(f"[DEBUG] VOLLSTÄNDIGKEIT: Test '{title}': QTI-Paket nicht auflösbar – "
                  f"alle Fragen fehlen im Quiz.")
            continue

        # Ist aus der geschriebenen Datei (Gegenprobe zur Pipeline-Zählung).
        actual_instances = _count_question_instances(temp_dir, rep['module_id'])
        if actual_instances == -1:
            print(f"[DEBUG] VOLLSTÄNDIGKEIT: Test '{title}': quiz.xml fehlt oder ist "
                  f"nicht lesbar – Quiz-Inhalt nicht prüfbar.")
            continue

        if actual_instances != emitted:
            print(f"[DEBUG] VOLLSTÄNDIGKEIT: Test '{title}': Pipeline erzeugte {emitted} "
                  f"Fragen-Slot(s), im geschriebenen Quiz stehen aber {actual_instances} "
                  f"– Verlust beim Schreiben der quiz.xml.")

        # recognized == emitted + unsupported gilt in der Pipeline per
        # Konstruktion; hier trotzdem geprüft, damit eine künftige Änderung,
        # die eine Frage still verschluckt, sofort auffällt.
        unexplained = recognized - emitted - unsupported
        if unexplained > 0:
            print(f"[DEBUG] VOLLSTÄNDIGKEIT: Test '{title}': {recognized} Frage(n) erkannt, "
                  f"aber nur {emitted} gebaut und {unsupported} als nicht unterstützt "
                  f"gemeldet – {unexplained} unerklärt verschwunden.")

        if unsupported > 0:
            print(f"[DEBUG] VOLLSTÄNDIGKEIT: Test '{title}': {unsupported} von {recognized} "
                  f"Frage(n) ohne Moodle-Äquivalent übersprungen (z.B. Matrix/Zeichnen) "
                  f"– bewusster, dokumentierter Verlust.")
        elif recognized == 0:
            print(f"[DEBUG] VOLLSTÄNDIGKEIT: Test '{title}': keine unterstützten Fragen im "
                  f"QTI-Paket – Quiz bleibt leer (in OLAT evtl. leerer Test).")


def _validate_question_bank(temp_dir: str, quiz_reports: list) -> None:
    """Globale Gegenprobe: die Summe aller in Quizzen als Slot gebauten Fragen
    muss der Zahl echter Top-Level-Fragen (<parent>0</parent>) in questions.xml
    entsprechen - sonst referenziert ein Quiz eine Frage, die in der Fragenbank
    fehlt (Moodle bricht den Restore mit 'invalid question' ab) oder umgekehrt."""
    questions_path = os.path.join(temp_dir, "questions.xml")
    if not os.path.exists(questions_path):
        return
    try:
        root = ET.parse(questions_path).getroot()
    except ET.ParseError:
        print("[DEBUG] VOLLSTÄNDIGKEIT: questions.xml nicht lesbar.")
        return

    top_level = sum(1 for q in root.iter('question')
                    if (q.findtext('parent') or '').strip() == '0')
    expected = sum(rep['emitted'] for rep in quiz_reports)

    if top_level != expected:
        print(f"[DEBUG] VOLLSTÄNDIGKEIT: {expected} Fragen-Slot(s) über alle Quizze, aber "
              f"{top_level} Top-Level-Frage(n) in der Fragenbank (questions.xml) – "
              f"Fragenbank und Quiz-Referenzen stimmen nicht überein.")


def _validate_activity_files(temp_dir: str, processed_activities: list) -> None:
    """Gegenprobe interne Buchhaltung → Datei-Realität: jede als gebaut
    geführte Aktivität muss ihren Ordner + ihre Haupt-XML real besitzen UND im
    moodle_backup.xml gelistet sein (sonst importiert Moodle sie nicht)."""
    backup_activities = set()
    backup_xml = os.path.join(temp_dir, "moodle_backup.xml")
    if os.path.exists(backup_xml):
        try:
            root = ET.parse(backup_xml).getroot()
            for act in root.findall(".//contents/activities/activity"):
                mid = (act.findtext('moduleid') or '').strip()
                mod = (act.findtext('modulename') or '').strip()
                if mid and mod:
                    backup_activities.add((mod, mid))
        except ET.ParseError:
            print("[DEBUG] VOLLSTÄNDIGKEIT: moodle_backup.xml nicht lesbar.")
            return

    for act_id, m_type, _sec_id, title in processed_activities:
        act_xml = os.path.join(temp_dir, "activities", f"{m_type}_{act_id}", f"{m_type}.xml")
        if not os.path.exists(act_xml):
            print(f"[DEBUG] VOLLSTÄNDIGKEIT: Aktivität '{title}' ({m_type}_{act_id}) als gebaut "
                  f"geführt, aber {m_type}.xml fehlt auf der Platte.")
            continue
        if (m_type, str(act_id)) not in backup_activities:
            print(f"[DEBUG] VOLLSTÄNDIGKEIT: Aktivität '{title}' ({m_type}_{act_id}) fehlt in "
                  f"moodle_backup.xml – Moodle würde sie beim Restore ignorieren.")


def validate_conversion_completeness(temp_dir: str, processed_activities: list,
                                     quiz_reports: list) -> None:
    """Haupt-Einstieg. Meldet nur (kein Abbruch), gleiche Konvention wie die
    übrigen Validatoren. Ein unerwarteter Fehler hier darf den fertigen
    Konvertierungslauf nicht kippen - deshalb komplett in try/except."""
    print("\n[DEBUG] Starte Soll-Ist-Validierung (Datenvollständigkeit)...")
    try:
        _validate_question_completeness(temp_dir, quiz_reports)
        _validate_question_bank(temp_dir, quiz_reports)
        _validate_activity_files(temp_dir, processed_activities)
    except Exception as e:
        print(f"[DEBUG] Soll-Ist-Validierung mit unerwartetem Fehler abgebrochen: "
              f"{type(e).__name__}: {e}")
    print("[DEBUG] Soll-Ist-Validierung abgeschlossen.\n")
