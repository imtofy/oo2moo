"""Tests für moodle_xml.py – patcht die aus dem Template kopierten
Aktivitäts-XMLs mit echten Werten. Arbeitet auf echten Dateien (tmp_path),
weil die Funktionen selbst Dateien lesen/schreiben."""

import xml.etree.ElementTree as ET

from conversion.moodle_xml import (
    modify_module_xml, modify_subsection_xml, modify_activity_xml,
    set_forum_announcement_type, rewrite_inforef_xml,
)


def _write(path, content):
    path.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n{content}', encoding='utf-8')
    return str(path)


def test_modify_module_xml_sets_id_section_and_timestamp(tmp_path):
    path = tmp_path / "module.xml"
    _write(path, '<module id="0"><sectionid>0</sectionid><added>0</added></module>')
    modify_module_xml(str(path), module_id=42, section_id=7, now=1700000000)
    root = ET.parse(path).getroot()
    assert root.get('id') == '42'
    assert root.findtext('sectionid') == '7'
    assert root.findtext('added') == '1700000000'


def test_modify_subsection_xml_uses_instance_id_not_module_id_as_activity_id(tmp_path):
    # id muss die Subsection-INSTANZ-ID sein, nicht die course_modules-ID,
    # sonst findet Moodles Restore die Verknüpfung zur section.xml nicht.
    path = tmp_path / "subsection.xml"
    _write(path, '<activity id="0" moduleid="0" contextid="0">'
                 '<subsection id="0"><name></name><timemodified>0</timemodified></subsection>'
                 '</activity>')
    modify_subsection_xml(str(path), subsection_instance_id=708, module_id=215149,
                          context_id=99, title="Meine Subsection", now=1700000000)
    root = ET.parse(path).getroot()
    assert root.get('id') == '708'
    assert root.get('moduleid') == '215149'
    sub = root.find('subsection')
    assert sub.get('id') == '708'
    assert sub.findtext('name') == 'Meine Subsection'
    assert sub.findtext('timemodified') == '1700000000'


def test_modify_activity_xml_page_separates_content_and_intro(tmp_path):
    path = tmp_path / "page.xml"
    _write(path, '<activity id="0" moduleid="0" contextid="0">'
                 '<page id="0"><name></name><intro></intro><content></content>'
                 '<timemodified>0</timemodified></page></activity>')
    modify_activity_xml(str(path), "page", 1, 10, "Meine Seite", 1700000000, "sp", False,
                       "<p>Echter Inhalt</p>", description_html="<p>Beschreibung</p>")
    root = ET.parse(path).getroot()
    page = root.find('page')
    assert page.findtext('content') == '<p>Echter Inhalt</p>'
    assert page.findtext('intro') == '<p>Beschreibung</p>'


def test_modify_activity_xml_non_page_puts_everything_into_intro(tmp_path):
    path = tmp_path / "label.xml"
    _write(path, '<activity id="0" moduleid="0" contextid="0">'
                 '<label id="0"><name></name><intro></intro></label></activity>')
    modify_activity_xml(str(path), "label", 1, 10, "Mein Label", 1700000000, "cal", False,
                       "<p>Kalender-Hinweis</p>")
    root = ET.parse(path).getroot()
    assert root.find('label').findtext('intro') == '<p>Kalender-Hinweis</p>'


def test_modify_activity_xml_fallback_adds_red_warning_before_content(tmp_path):
    path = tmp_path / "label.xml"
    _write(path, '<activity id="0" moduleid="0" contextid="0">'
                 '<label id="0"><name></name><intro></intro></label></activity>')
    modify_activity_xml(str(path), "label", 1, 10, "Unbekannt", 1700000000, "irgendwas", True,
                       "<p>Original</p>")
    intro = ET.parse(path).getroot().find('label').findtext('intro')
    assert intro.startswith('<p style="color:red;">')
    assert intro.endswith('<p>Original</p>')


def test_modify_activity_xml_url_falls_back_to_invalid_domain_when_empty(tmp_path):
    path = tmp_path / "url.xml"
    _write(path, '<activity id="0" moduleid="0" contextid="0">'
                 '<url id="0"><name></name><intro></intro></url></activity>')
    modify_activity_xml(str(path), "url", 1, 10, "Externe Seite", 1700000000, "tu", False,
                       "", node_url="")
    url_node = ET.parse(path).getroot().find('url').find('externalurl')
    assert url_node.text == "http://example.invalid/"


def test_modify_activity_xml_url_keeps_real_url(tmp_path):
    path = tmp_path / "url.xml"
    _write(path, '<activity id="0" moduleid="0" contextid="0">'
                 '<url id="0"><name></name><intro></intro></url></activity>')
    modify_activity_xml(str(path), "url", 1, 10, "Externe Seite", 1700000000, "tu", False,
                       "", node_url="https://example.org")
    url_node = ET.parse(path).getroot().find('url').find('externalurl')
    assert url_node.text == "https://example.org"


def test_set_forum_announcement_type_switches_to_news(tmp_path):
    path = tmp_path / "forum.xml"
    _write(path, '<activity><forum><type>general</type><forcesubscribe>1</forcesubscribe></forum></activity>')
    set_forum_announcement_type(str(path))
    forum = ET.parse(path).getroot().find('forum')
    assert forum.findtext('type') == 'news'
    assert forum.findtext('forcesubscribe') == '2'


def test_rewrite_inforef_xml_with_files_and_question_categories(tmp_path):
    path = tmp_path / "inforef.xml"
    rewrite_inforef_xml(str(path), file_ids=[1, 2], question_category_ids=[10, 11])
    root = ET.parse(path).getroot()
    file_ids = [handle.findtext('id') for handle in root.findall('.//fileref/file')]
    cat_ids = [content.findtext('id') for content in root.findall('.//question_categoryref/question_category')]
    assert file_ids == ['1', '2']
    assert cat_ids == ['10', '11']


def test_rewrite_inforef_xml_with_nothing_produces_minimal_valid_inforef(tmp_path):
    path = tmp_path / "inforef.xml"
    rewrite_inforef_xml(str(path), file_ids=[])
    root = ET.parse(path).getroot()
    assert root.find('fileref') is None
    assert root.find('question_categoryref') is None


# --- Absichtlich unpassende Eingaben (Fehlerbehandlung) ---

def test_modify_activity_xml_with_mismatched_modulename_does_not_raise(tmp_path):
    # Template hat <page>, wir behaupten aber modulename='resource' –
    # find() liefert None, die Funktion darf trotzdem nicht crashen.
    path = tmp_path / "page.xml"
    _write(path, '<activity id="0" moduleid="0" contextid="0">'
                 '<page id="0"><name></name><intro></intro><content></content></page></activity>')
    modify_activity_xml(str(path), "resource", 1, 10, "Titel", 1700000000, "document", False, "Inhalt")
    # Datei bleibt unverändert lesbar, kein Absturz.
    root = ET.parse(path).getroot()
    assert root.find('page').findtext('name') == ''
