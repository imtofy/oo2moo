"""Baut die kurs- und archivweiten XML-Dateien des Moodle-Backups.

Alles, was main.py NICHT pro Baustein einzeln erzeugt (course.xml,
section.xml, das äußere moodle_backup.xml mit Aktivitäts-/Settings-Liste),
sowie die Zuordnung von Moodle-Modulnamen zu ihren Template-Ordnern.
Braucht MOODLE_WWWROOT/MOODLE_SITE_HASH aus config.py.
"""

import os
import xml.etree.ElementTree as ET
from .file_manager import write_xml, escape_xml_text
from config import MOODLE_WWWROOT, MOODLE_SITE_HASH

DEFAULT_FULLNAME = "Imported OpenOLAT Course"
DEFAULT_SHORTNAME = "Imported_Course"


def get_template_mapping(template_dir):
    """Liest aus dem Musterkurs-Template heraus, welcher Ordner zu welchem
    Moodle-Modulnamen gehört (z.B. 'quiz' → .../activities/quiz_215336).

    Für 'forum' liegen im Musterkurs ZWEI Vorlagen (allgemeines Forum und
    Ankündigungen, type=news+forcesubscribe=1) – ohne die Sonderbehandlung
    unten würde je nach Zufall der Reihenfolge in moodle_backup.xml die
    Ankündigungen-Vorlage als Standard für ALLE Forum-Typen (fo/dialog/
    blog/info) landen. main.py schaltet 'info' danach gezielt per
    moodle_xml.set_forum_announcement_type() auf type=news um, die
    Standard-Vorlage muss also die allgemeine sein.
    """
    backup_xml = os.path.join(template_dir, "moodle_backup.xml")
    mapping = {}
    if not os.path.exists(backup_xml):
        print(f"[*] KRITISCH: Template moodle_backup.xml nicht gefunden in {template_dir}")
        return mapping
    tree = ET.parse(backup_xml)
    root = tree.getroot()
    forum_dirs = []
    for activity in root.findall(".//contents/activities/activity"):
        modname = activity.find("modulename").text
        directory = activity.find("directory").text
        full_dir = os.path.join(template_dir, directory)
        if modname == "forum":
            forum_dirs.append(full_dir)
        if modname not in mapping:
            mapping[modname] = full_dir

    for forum_dir in forum_dirs:
        forum_xml = os.path.join(forum_dir, "forum.xml")
        if not os.path.exists(forum_xml):
            continue
        type_node = ET.parse(forum_xml).getroot().find(".//type")
        if type_node is not None and type_node.text != "news":
            mapping["forum"] = forum_dir
            break

    return mapping


def generate_course_xml(now, fullname=DEFAULT_FULLNAME, shortname=DEFAULT_SHORTNAME):
    """Baut die course.xml (Kurs-Grunddaten: Name, Format, Zeitstempel)."""
    return f"""<course id="1" contextid="1">
  <shortname>{escape_xml_text(shortname)}</shortname>
  <fullname>{escape_xml_text(fullname)}</fullname>
  <idnumber></idnumber>
  <summary></summary>
  <summaryformat>1</summaryformat>
  <format>topics</format>
  <showgrades>1</showgrades>
  <newsitems>5</newsitems>
  <startdate>{now}</startdate>
  <enddate>0</enddate>
  <marker>0</marker>
  <maxbytes>0</maxbytes>
  <legacyfiles>0</legacyfiles>
  <showreports>0</showreports>
  <visible>1</visible>
  <groupmode>0</groupmode>
  <groupmodeforce>0</groupmodeforce>
  <defaultgroupingid>0</defaultgroupingid>
  <lang></lang>
  <theme></theme>
  <timecreated>{now}</timecreated>
  <timemodified>{now}</timemodified>
  <requested>0</requested>
  <enablecompletion>0</enablecompletion>
  <completionnotify>0</completionnotify>
  <showactivitydates>1</showactivitydates>
  <showcompletionconditions>1</showcompletionconditions>
  <category>
    <name>Miscellaneous</name>
    <description>$@NULL@$</description>
  </category>
</course>"""


def generate_section_xml(section_id, number, now, title, module_ids=None, component=None, itemid=None,
                         summary=""):
    """component/itemid nur bei einem Moodle-Unterabschnitt gesetzt
    (component='mod_subsection', itemid=Instanz-ID der subsection-Aktivität) –
    verknüpft diesen Abschnitt als deren Inhalt; normale Abschnitte bleiben NULL.

    summary ist bereits fertig aufbereitetes HTML (wie bei jeder Aktivität,
    siehe node_processor.build_node_content) – html.escape(quote=False) statt
    ElementTree, weil diese Funktion (anders als moodle_xml.py) die XML per
    f-String baut und deshalb & / < / > selbst maskieren muss, sonst würden
    echte HTML-Tags in der Beschreibung als XML-Kindelemente fehlinterpretiert."""
    sequence = ",".join(str(mid) for mid in module_ids) if module_ids else ""
    safe_title = escape_xml_text(title)
    safe_summary = escape_xml_text(summary) if summary else ""
    component_val = component if component else "$@NULL@$"
    itemid_val = itemid if itemid is not None else "$@NULL@$"
    return f"""<section id="{section_id}">
  <number>{number}</number>
  <name>{safe_title}</name>
  <summary>{safe_summary}</summary>
  <summaryformat>1</summaryformat>
  <sequence>{sequence}</sequence>
  <visible>1</visible>
  <availabilityjson>$@NULL@$</availabilityjson>
  <component>{component_val}</component>
  <itemid>{itemid_val}</itemid>
  <timemodified>{now}</timemodified>
</section>"""


def generate_moodle_backup_xml(processed_activities, sections, now, backup_id,
                                fullname=DEFAULT_FULLNAME, shortname=DEFAULT_SHORTNAME,
                                has_questions=False, has_blocks=False):
    """Baut die äußere moodle_backup.xml – das Inhaltsverzeichnis des ganzen Archivs.

    Die 'questionbank'-Einstellung ist entscheidend: steht sie auf 0,
    ignoriert Moodle die komplette Fragenbank-Restaurierung, unabhängig
    davon, was in questions.xml steht – deshalb wird sie hier dynamisch
    auf 1 gesetzt, sobald has_questions True ist. Analog 'blocks': steht sie
    auf 0, ignoriert Moodle jeden Ordner unter course/blocks/, egal was dort
    liegt – ein echter Export (Kurs mit manuell hinzugefügtem Kalender-Block)
    zeigt keine weitere Block-spezifische Einstellung, nur diesen einen
    globalen Schalter.
    """
    safe_fullname = escape_xml_text(fullname)
    safe_shortname = escape_xml_text(shortname)
    xml = f"""<moodle_backup>
  <information>
    <name>backup.mbz</name>
    <moodle_version>2025041400</moodle_version>
    <moodle_release>5.0</moodle_release>
    <backup_version>2025041400</backup_version>
    <backup_release>5.0</backup_release>
    <backup_date>{now}</backup_date>
    <mnet_remoteusers>0</mnet_remoteusers>
    <include_file_references_to_external_content>0</include_file_references_to_external_content>
    <original_wwwroot>{MOODLE_WWWROOT}</original_wwwroot>
    <original_site_identifier_hash>{MOODLE_SITE_HASH}</original_site_identifier_hash>
    <original_course_id>1</original_course_id>
    <original_course_format>topics</original_course_format>
    <original_course_fullname>{safe_fullname}</original_course_fullname>
    <original_course_shortname>{safe_shortname}</original_course_shortname>
    <original_course_startdate>{now}</original_course_startdate>
    <original_course_enddate>0</original_course_enddate>
    <original_course_contextid>1</original_course_contextid>
    <original_system_contextid>1</original_system_contextid>
    <details>
      <detail>
        <backup_id>{backup_id}</backup_id>
        <type>course</type>
        <format>moodle2</format>
        <interactive>1</interactive>
        <mode>10</mode>
        <execution>1</execution>
        <executiontime>0</executiontime>
      </detail>
    </details>
    <contents>
      <course><courseid>1</courseid><title>{safe_fullname}</title><directory>course</directory></course>
      <sections>"""

    for sec_id, sec_data in sections.items():
        safe_title = escape_xml_text(sec_data['title'])
        parentcmid = sec_data.get('parentcmid') or ''
        modname = sec_data.get('modname') or ''
        xml += (f"""<section><sectionid>{sec_id}</sectionid><title>{safe_title}</title>"""
                f"""<directory>sections/section_{sec_id}</directory>"""
                f"""<parentcmid>{parentcmid}</parentcmid><modname>{modname}</modname></section>""")

    xml += """</sections>
      <activities>"""

    for act_id, m_type, sec_id, act_title in processed_activities:
        safe_act_title = escape_xml_text(act_title)
        # Moodles Restore erkennt eine Aktivität nur dann als "in einem
        # Unterabschnitt" (SUBACTIVITY_LEVEL statt
        # ACTIVITY_LEVEL), wenn dieses Feld gesetzt ist – unabhängig davon,
        # ob ihre Sektion selbst schon korrekt als Unterabschnitt (component=
        # mod_subsection) markiert ist. Ohne insubsection versucht die
        # Unterabschnitts-Sektion (Ebene 17), eine Abhängigkeit auf die
        # Aktivität als Ebene 13 zu setzen – Moodle lehnt das als
        # "cannot_add_upper_level_dependency" ab, weil eine Abhängigkeit nie
        # auf eine HÖHERE Ebene zeigen darf.
        insubsection = 1 if sections.get(sec_id, {}).get("component") == "mod_subsection" else ""
        xml += (f"""<activity><moduleid>{act_id}</moduleid><sectionid>{sec_id}</sectionid>"""
                f"""<modulename>{m_type}</modulename><title>{safe_act_title}</title>"""
                f"""<directory>activities/{m_type}_{act_id}</directory>"""
                f"""<insubsection>{insubsection}</insubsection></activity>""")

    xml += f"""</activities>
    </contents>
    <settings>
      <setting><level>root</level><name>filename</name><value>backup.mbz</value></setting>
      <setting><level>root</level><name>users</name><value>0</value></setting>
      <setting><level>root</level><name>anonymize</name><value>0</value></setting>
      <setting><level>root</level><name>role_assignments</name><value>0</value></setting>
      <setting><level>root</level><name>activities</name><value>1</value></setting>
      <setting><level>root</level><name>blocks</name><value>{1 if has_blocks else 0}</value></setting>
      <setting><level>root</level><name>files</name><value>1</value></setting>
      <setting><level>root</level><name>filters</name><value>0</value></setting>
      <setting><level>root</level><name>comments</name><value>0</value></setting>
      <setting><level>root</level><name>badges</name><value>0</value></setting>
      <setting><level>root</level><name>calendarevents</name><value>0</value></setting>
      <setting><level>root</level><name>userscompletion</name><value>0</value></setting>
      <setting><level>root</level><name>logs</name><value>0</value></setting>
      <setting><level>root</level><name>grade_histories</name><value>0</value></setting>
      <setting><level>root</level><name>questionbank</name><value>{1 if has_questions else 0}</value></setting>
      <setting><level>root</level><name>groups</name><value>0</value></setting>
      <setting><level>root</level><name>competencies</name><value>0</value></setting>
      <setting><level>root</level><name>customfield</name><value>0</value></setting>
      <setting><level>root</level><name>contentbankcontent</name><value>0</value></setting>
      <setting><level>root</level><name>legacyfiles</name><value>0</value></setting>"""

    for sec_id in sections.keys():
        xml += f"""
      <setting><level>section</level><section>section_{sec_id}</section>""" \
               f"""<name>section_{sec_id}_included</name><value>1</value></setting>
      <setting><level>section</level><section>section_{sec_id}</section>""" \
               f"""<name>section_{sec_id}_userinfo</name><value>0</value></setting>"""

    for act_id, m_type, _, _ in processed_activities:
        setting_name = f"{m_type}_{act_id}"
        # Wiki ist der einzige Modultyp, bei dem Moodles eigenes Restore
        # (restore_wiki_stepslib.php) den kompletten Seiteninhalt hinter
        # userinfo versteckt – ohne userinfo=1 bliebe jede Seite unbeachtet,
        # egal was in wiki.xml steht. Enthält trotzdem keine echten OLAT-
        # Autor:innen (userid bleibt in wiki_builder.py überall 0).
        userinfo = 1 if m_type == "wiki" else 0
        xml += f"""
      <setting><level>activity</level><activity>{setting_name}</activity>""" \
               f"""<name>{setting_name}_included</name><value>1</value></setting>
      <setting><level>activity</level><activity>{setting_name}</activity>""" \
               f"""<name>{setting_name}_userinfo</name><value>{userinfo}</value></setting>"""

    xml += """
    </settings>
  </information>
</moodle_backup>"""
    return xml


def create_empty_meta_files(temp_dir, question_categories_xml: str = "",
                            gradebook_xml: str = ""):
    """Schreibt alle kursweiten Metadaten-Dateien, die keinen Baustein-eigenen
    Inhalt haben. question_categories_xml ist leer bei Kursen ohne Tests,
    dann bleibt questions.xml die leere Standardstruktur."""
    files = {
        "scales.xml": "<scales_definition></scales_definition>",
        "outcomes.xml": "<outcomes_definition></outcomes_definition>",
        "badges.xml": "<badges></badges>",
        "questions.xml": f"<question_categories>\n{question_categories_xml}\n</question_categories>"
                         if question_categories_xml else "<question_categories></question_categories>",
        "roles.xml": "<roles_definition></roles_definition>",
        "gradebook.xml": gradebook_xml or "<gradebook></gradebook>",
        "groups.xml": "<groups></groups>",
        "completion.xml": "<course_completion></course_completion>",
        "grade_history.xml": "<grade_history></grade_history>"
    }
    for name, content in files.items():
        write_xml(os.path.join(temp_dir, name), content)
