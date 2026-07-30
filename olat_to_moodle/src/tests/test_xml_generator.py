"""Tests für xml_generator.py - vor allem generate_section_xml (summary-Feld)
und generate_moodle_backup_xml (dynamische blocks/questionbank-Schalter)."""

import xml.etree.ElementTree as ET

from conversion.xml_generator import generate_section_xml, generate_moodle_backup_xml, generate_course_xml


def test_section_xml_is_well_formed_and_round_trips_plain_fields():
    xml = generate_section_xml(5, 5, 1700000000, "Kommunikation", module_ids=[1, 2, 3])
    root = ET.fromstring(xml)
    assert root.findtext('number') == '5'
    assert root.findtext('name') == 'Kommunikation'
    assert root.findtext('sequence') == '1,2,3'
    assert root.findtext('component') == '$@NULL@$'
    assert root.findtext('itemid') == '$@NULL@$'


def test_section_xml_summary_html_survives_escape_unescape_round_trip():
    xml = generate_section_xml(1, 1, 1700000000, "Test", summary='<p>Text mit "Zitat" & Ampersand</p>')
    root = ET.fromstring(xml)
    assert root.findtext('summary') == '<p>Text mit "Zitat" & Ampersand</p>'


def test_section_xml_empty_summary_stays_empty():
    xml = generate_section_xml(1, 1, 1700000000, "Test")
    root = ET.fromstring(xml)
    assert root.findtext('summary') == ''


def test_section_xml_subsection_component_and_itemid_set():
    xml = generate_section_xml(10001, 10001, 1700000000, "Unterabschnitt",
                                component="mod_subsection", itemid=5)
    root = ET.fromstring(xml)
    assert root.findtext('component') == 'mod_subsection'
    assert root.findtext('itemid') == '5'


def test_section_xml_title_with_special_chars_stays_well_formed():
    # "&"/"<"/">" im Titel dürfen die XML-Struktur nicht kaputt machen.
    xml = generate_section_xml(1, 1, 1700000000, 'Kapitel 3 & <Anhang>')
    root = ET.fromstring(xml)  # wirft bei kaputtem XML von selbst
    assert root.findtext('name') == 'Kapitel 3 & <Anhang>'


def test_backup_xml_questionbank_setting_follows_has_questions_flag():
    xml_with = generate_moodle_backup_xml([], {}, 1700000000, "abc", has_questions=True)
    xml_without = generate_moodle_backup_xml([], {}, 1700000000, "abc", has_questions=False)
    assert _setting_value(xml_with, "questionbank") == "1"
    assert _setting_value(xml_without, "questionbank") == "0"


def test_backup_xml_blocks_setting_follows_has_blocks_flag():
    xml_with = generate_moodle_backup_xml([], {}, 1700000000, "abc", has_blocks=True)
    xml_without = generate_moodle_backup_xml([], {}, 1700000000, "abc", has_blocks=False)
    assert _setting_value(xml_with, "blocks") == "1"
    assert _setting_value(xml_without, "blocks") == "0"


def test_backup_xml_wiki_activity_gets_userinfo_1_others_get_0():
    processed = [(1, "wiki", 0, "Mein Wiki"), (2, "page", 0, "Meine Seite")]
    xml = generate_moodle_backup_xml(processed, {0: {"title": "Sektion"}}, 1700000000, "abc")
    assert _setting_value(xml, "wiki_1_userinfo") == "1"
    assert _setting_value(xml, "page_2_userinfo") == "0"


def test_backup_xml_activity_in_subsection_gets_insubsection_flag():
    sections = {5: {"title": "Unterabschnitt", "component": "mod_subsection"}}
    processed = [(1, "page", 5, "Seite in Subsection")]
    xml = generate_moodle_backup_xml(processed, sections, 1700000000, "abc")
    root = ET.fromstring(xml)
    activity = root.find(".//activity[moduleid='1']")
    assert activity.findtext('insubsection') == '1'


def test_backup_xml_activity_in_normal_section_has_empty_insubsection():
    sections = {1: {"title": "Normale Section"}}
    processed = [(1, "page", 1, "Seite")]
    xml = generate_moodle_backup_xml(processed, sections, 1700000000, "abc")
    root = ET.fromstring(xml)
    activity = root.find(".//activity[moduleid='1']")
    assert activity.findtext('insubsection') == ''


def test_course_xml_escapes_fullname_and_shortname():
    xml = generate_course_xml(1700000000, fullname='Kurs "A" & B', shortname='A&B')
    root = ET.fromstring(xml)
    assert root.findtext('fullname') == 'Kurs "A" & B'
    assert root.findtext('shortname') == 'A&B'


# --- Absichtlich leere/kaputte Eingaben ---

def test_backup_xml_with_no_sections_and_no_activities_is_still_well_formed():
    xml = generate_moodle_backup_xml([], {}, 1700000000, "abc")
    root = ET.fromstring(xml)
    assert root.find(".//sections") is not None
    assert root.find(".//activities") is not None


def test_section_xml_with_empty_module_ids_list_has_empty_sequence():
    xml = generate_section_xml(1, 1, 1700000000, "Leere Section", module_ids=[])
    root = ET.fromstring(xml)
    assert root.findtext('sequence') == ''


def _setting_value(xml: str, name: str) -> str:
    root = ET.fromstring(xml)
    for setting in root.findall(".//setting"):
        if setting.findtext('name') == name:
            return setting.findtext('value')
    raise AssertionError(f"Setting '{name}' nicht gefunden")
