"""Baut die Bewertungs-Einträge eines Moodle-Backups (Bewertungen/Gradebook).

Moodle verteilt sie auf zwei Orte, beide werden hier erzeugt:
  – gradebook.xml im Backup-Wurzelverzeichnis: die Kurs-Kategorie und das
    Kurs-Gesamtergebnis (itemtype='course').
  – grades.xml je Aktivität: das grade_item genau dieser Aktivität
    (itemtype='mod').

Ohne diese Einträge legt Moodle beim Restore KEINE Bewertungsspalten an:
restore_gradebook_structure_step liest sie ausschließlich aus dem Backup, und
grade_grab_course_grades() – die Funktion, die fehlende Items nachträglich
erzeugen würde – wird beim Restore nicht aufgerufen (lib/gradelib.php, nur aus
grade_recover_history_grades und grade_course_reset). Die Spalte entstünde
sonst erst beim ersten Versuch bzw. der ersten Abgabe.

Bewertet wird nur, was in Moodle auch ein grade_item hat – gegen einen echten
Export abgeglichen: quiz, assign und scorm ja; feedback, choice, forum, page,
folder, book, url, wiki, label nein.
"""

import os
import xml.etree.ElementTree as ET

from .file_manager import write_xml

from .file_manager import escape_xml_text

# Moodle-Modulname → Feld in dessen Aktivitäts-XML, das die Höchstpunktzahl
# trägt. Der Wert wird von dort GELESEN, nicht geraten: eine Abweichung
# zwischen grade_item.grademax und der Aktivität selbst führt zu falsch
# skalierten Noten.
GRADED_MODULES = {
    'quiz': 'grade',
    'assign': 'grade',
    'scorm': 'maxgrade',
}

# Standard-Kategorie eines frisch angelegten Moodle-Kurses: Aggregation 13
# (natürliche Gewichtung), Name '?' – so heißt sie in jedem echten Export,
# Moodle zeigt stattdessen den Kursnamen an.
_COURSE_CATEGORY_AGGREGATION = 13


def _grade_item_xml(item_id: int, now: int, itemtype: str, iteminstance: int,
                    grademax: float, sortorder: int, categoryid=None,
                    itemname=None, itemmodule=None) -> str:
    """Ein <grade_item> – gemeinsam für das Kurs-Gesamtergebnis und die
    Aktivitäts-Einträge, die sich nur in wenigen Feldern unterscheiden.

    aggregationcoef2 bleibt 0: bei weightoverride=0 rechnet Moodle die
    Gewichte beim Restore selbst aus."""
    return f"""    <grade_item id="{item_id}">
      <categoryid>{categoryid if categoryid is not None else '$@NULL@$'}</categoryid>
      <itemname>{escape_xml_text(itemname) if itemname else '$@NULL@$'}</itemname>
      <itemtype>{itemtype}</itemtype>
      <itemmodule>{itemmodule or '$@NULL@$'}</itemmodule>
      <iteminstance>{iteminstance}</iteminstance>
      <itemnumber>{'0' if itemtype == 'mod' else '$@NULL@$'}</itemnumber>
      <iteminfo>$@NULL@$</iteminfo>
      <idnumber></idnumber>
      <calculation>$@NULL@$</calculation>
      <gradetype>1</gradetype>
      <grademax>{grademax:.5f}</grademax>
      <grademin>0.00000</grademin>
      <scaleid>$@NULL@$</scaleid>
      <outcomeid>$@NULL@$</outcomeid>
      <gradepass>0.00000</gradepass>
      <multfactor>1.00000</multfactor>
      <plusfactor>0.00000</plusfactor>
      <aggregationcoef>0.00000</aggregationcoef>
      <aggregationcoef2>0.00000</aggregationcoef2>
      <weightoverride>0</weightoverride>
      <sortorder>{sortorder}</sortorder>
      <display>0</display>
      <decimals>$@NULL@$</decimals>
      <hidden>0</hidden>
      <locked>0</locked>
      <locktime>0</locktime>
      <needsupdate>0</needsupdate>
      <timecreated>{now}</timecreated>
      <timemodified>{now}</timemodified>
      <grade_grades>
      </grade_grades>
    </grade_item>"""


def build_activity_grades_xml(category_id: int, item_id: int, now: int,
                              modulename: str, module_id: int, title: str,
                              grademax: float, sortorder: int) -> str:
    """Die grades.xml EINER bewerteten Aktivität.

    iteminstance ist die Instanz-ID der Aktivität – in diesem Konverter
    identisch mit der Modul-ID (siehe main.py, das beide gleich vergibt)."""
    return f"""<activity_gradebook>
  <grade_items>
{_grade_item_xml(item_id, now, 'mod', module_id, grademax, sortorder,
                 categoryid=category_id, itemname=title, itemmodule=modulename)}
  </grade_items>
  <grade_letters>
  </grade_letters>
</activity_gradebook>"""


def build_gradebook_xml(category_id: int, course_item_id: int, now: int,
                        course_grademax: float) -> str:
    """Die kursweite gradebook.xml: eine Kategorie plus das Gesamtergebnis.

    course_grademax ist die Summe der Höchstpunktzahlen aller bewerteten
    Aktivitäten – so zeigt Moodle dieselbe Gesamtpunktzahl an, die der Kurs
    tatsächlich hergibt."""
    return f"""<gradebook>
  <attributes>
  </attributes>
  <grade_categories>
    <grade_category id="{category_id}">
      <parent>$@NULL@$</parent>
      <depth>1</depth>
      <path>/{category_id}/</path>
      <fullname>?</fullname>
      <aggregation>{_COURSE_CATEGORY_AGGREGATION}</aggregation>
      <keephigh>0</keephigh>
      <droplow>0</droplow>
      <aggregateonlygraded>1</aggregateonlygraded>
      <aggregateoutcomes>0</aggregateoutcomes>
      <timecreated>{now}</timecreated>
      <timemodified>{now}</timemodified>
      <hidden>0</hidden>
    </grade_category>
  </grade_categories>
  <grade_items>
{_grade_item_xml(course_item_id, now, 'course', category_id, course_grademax, 1)}
  </grade_items>
  <grade_letters>
  </grade_letters>
  <grade_settings>
  </grade_settings>
</gradebook>"""


def write_activity_grades(temp_dir: str, processed_activities: list, now: int) -> str:
    """Schreibt die grades.xml jeder bewerteten Aktivität und gibt die
    kursweite gradebook.xml dazu zurück.

    Die Höchstpunktzahl wird aus der bereits geschriebenen Aktivitäts-XML
    GELESEN (siehe GRADED_MODULES) – ein geratener Wert
    würde die Noten falsch skalieren. Ist das Feld nicht lesbar, bleibt die
    Aktivität ohne Bewertungseintrag, statt eine falsche Zahl zu setzen.

    Enthält der Kurs überhaupt nichts Bewertbares, kommt ein leerer String
    zurück – dann bleibt gradebook.xml bei der leeren Struktur. Ein
    Kurs-Gesamtergebnis über 0 Punkte wäre in der Bewertungsübersicht nur
    eine irreführende Null."""
    category_id = 1
    next_id = 2
    sortorder = 2  # 1 gehört dem Kurs-Gesamtergebnis
    total = 0.0

    for module_id, m_type, _sec_id, title in processed_activities:
        field = GRADED_MODULES.get(m_type)
        if field is None:
            continue
        activity_xml = os.path.join(temp_dir, "activities", f"{m_type}_{module_id}", f"{m_type}.xml")
        try:
            value = ET.parse(activity_xml).getroot().findtext(f'.//{field}')
            grademax = float(value)
        except (OSError, ET.ParseError, TypeError, ValueError):
            print(f"[!] '{title}': Höchstpunktzahl nicht lesbar – Aktivität bekommt "
                  f"keinen Eintrag in den Bewertungen.")
            continue

        write_xml(os.path.join(temp_dir, "activities", f"{m_type}_{module_id}", "grades.xml"),
                  build_activity_grades_xml(
                      category_id, next_id, now, m_type, module_id, title, grademax, sortorder))
        next_id += 1
        sortorder += 1
        total += grademax

    if next_id == 2:
        return ""
    return build_gradebook_xml(category_id, next_id, now, total)
