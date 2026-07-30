"""Tests für block_builder.py - Schema gegen einen echten Moodle-5.2-Export
verifiziert (Kurs mit manuell hinzugefügtem Kalender-Block, wieder exportiert)."""

import xml.etree.ElementTree as ET

from conversion.block_builder import build_calendar_block_xml


def test_calendar_block_xml_has_expected_fields():
    xml = build_calendar_block_xml(block_id=44, context_id=1916, now=1700000000)
    root = ET.fromstring(xml)
    assert root.get('id') == '44'
    assert root.get('contextid') == '1916'
    assert root.findtext('blockname') == 'calendar_month'
    # Ein Block hängt immer am Kurs-Kontext, nie an einer Aktivität/Section.
    assert root.findtext('parentcontextid') == '1'
    assert root.findtext('defaultregion') == 'side-pre'
    assert root.findtext('timecreated') == '1700000000'
    assert root.findtext('timemodified') == '1700000000'


def test_calendar_block_xml_is_well_formed_for_different_ids():
    # Kein Absturz/keine Kollision bei anderen ID-Kombinationen.
    xml = build_calendar_block_xml(block_id=1, context_id=2, now=0)
    ET.fromstring(xml)
