"""Tests für gradebook_builder.py und gradebook_builder.write_activity_grades().

Ohne diese Einträge legt Moodle beim Restore keine Bewertungsspalten an – die
Aktivitäten funktionieren, der Notenüberblick bleibt aber leer."""

import os
import xml.etree.ElementTree as ET

from conversion import gradebook_builder


def test_course_item_carries_the_sum_of_all_activities():
    xml = gradebook_builder.build_gradebook_xml(
        category_id=1, course_item_id=9, now=1700000000, course_grademax=130.0)
    root = ET.fromstring(xml)

    category = root.find('.//grade_category')
    assert category.get('id') == "1"
    assert category.findtext('path') == "/1/"
    assert category.findtext('parent') == "$@NULL@$"

    item = root.find('.//grade_item')
    assert item.findtext('itemtype') == "course"
    assert item.findtext('grademax') == "130.00000"
    # Das Kurs-Item hängt an keiner Kategorie, sondern IST ihre Auswertung.
    assert item.findtext('categoryid') == "$@NULL@$"
    assert item.findtext('iteminstance') == "1"


def test_activity_item_links_module_and_category():
    xml = gradebook_builder.build_activity_grades_xml(
        category_id=1, item_id=5, now=1700000000, modulename="quiz",
        module_id=42, title="Abschlusstest", grademax=25.0, sortorder=3)
    item = ET.fromstring(xml).find('.//grade_item')

    assert item.findtext('itemtype') == "mod"
    assert item.findtext('itemmodule') == "quiz"
    assert item.findtext('iteminstance') == "42"
    assert item.findtext('categoryid') == "1"
    assert item.findtext('itemname') == "Abschlusstest"
    assert item.findtext('grademax') == "25.00000"
    # itemnumber 0 ist die Hauptbewertung der Aktivität.
    assert item.findtext('itemnumber') == "0"


def _activity(tmp_path, m_type, module_id, field, value):
    folder = tmp_path / "activities" / f"{m_type}_{module_id}"
    folder.mkdir(parents=True)
    (folder / f"{m_type}.xml").write_text(
        f'<activity><{m_type}><{field}>{value}</{field}></{m_type}></activity>', encoding="utf-8")


def test_only_graded_module_types_get_an_entry(tmp_path):
    _activity(tmp_path, "quiz", 1, "grade", "20.00000")
    _activity(tmp_path, "page", 2, "grade", "99")      # page ist nicht bewertet
    _activity(tmp_path, "scorm", 3, "maxgrade", "100")

    gradebook = gradebook_builder.write_activity_grades(
        str(tmp_path), [(1, "quiz", 0, "Test"), (2, "page", 0, "Seite"), (3, "scorm", 0, "Paket")], 1700000000)

    assert (tmp_path / "activities" / "quiz_1" / "grades.xml").exists()
    assert not (tmp_path / "activities" / "page_2" / "grades.xml").exists()
    assert (tmp_path / "activities" / "scorm_3" / "grades.xml").exists()
    # Kurs-Gesamtergebnis = Summe der bewerteten Aktivitäten.
    assert ET.fromstring(gradebook).find('.//grade_item').findtext('grademax') == "120.00000"


def test_grademax_is_read_from_the_activity_not_guessed(tmp_path):
    # Wird der Wert in der Aktivität geändert, muss die Bewertung folgen –
    # ein fest verdrahteter Wert würde die Noten falsch skalieren.
    _activity(tmp_path, "quiz", 1, "grade", "37.50000")
    gradebook_builder.write_activity_grades(str(tmp_path), [(1, "quiz", 0, "Test")], 1700000000)
    item = ET.parse(tmp_path / "activities" / "quiz_1" / "grades.xml").getroot().find('.//grade_item')
    assert item.findtext('grademax') == "37.50000"


def test_unreadable_grade_is_reported_and_skipped(tmp_path, capsys):
    folder = tmp_path / "activities" / "quiz_1"
    folder.mkdir(parents=True)
    (folder / "quiz.xml").write_text('<activity><quiz></quiz></activity>', encoding="utf-8")

    gradebook = gradebook_builder.write_activity_grades(str(tmp_path), [(1, "quiz", 0, "Kaputt")], 1700000000)

    assert "Höchstpunktzahl nicht lesbar" in capsys.readouterr().out
    assert not (folder / "grades.xml").exists()
    # Keine bewertete Aktivität übrig -> gar kein Gradebook (siehe unten).
    assert gradebook == ""


def test_course_without_graded_activities_gets_no_gradebook(tmp_path):
    # Ein Kurs-Gesamtergebnis über 0 Punkte wäre in der Bewertungsübersicht
    # nur eine irreführende Null – dann lieber die leere Struktur behalten.
    _activity(tmp_path, "page", 1, "grade", "99")
    assert gradebook_builder.write_activity_grades(str(tmp_path), [(1, "page", 0, "Seite")], 1700000000) == ""


def test_empty_gradebook_falls_back_to_the_empty_structure(tmp_path):
    # create_empty_meta_files muss mit dem leeren String umgehen können.
    from conversion.xml_generator import create_empty_meta_files

    create_empty_meta_files(str(tmp_path), gradebook_xml="")
    content = (tmp_path / "gradebook.xml").read_text(encoding="utf-8")
    assert "<gradebook></gradebook>" in content


def test_sortorder_is_unique_across_activities(tmp_path):
    for i, (m_type, field, value) in enumerate(
            [("quiz", "grade", "10"), ("assign", "grade", "100"), ("scorm", "maxgrade", "100")], start=1):
        _activity(tmp_path, m_type, i, field, value)

    gradebook_builder.write_activity_grades(
        str(tmp_path), [(1, "quiz", 0, "A"), (2, "assign", 0, "B"), (3, "scorm", 0, "C")], 1700000000)

    sortorders = []
    for i, m_type in enumerate(["quiz", "assign", "scorm"], start=1):
        path = os.path.join(str(tmp_path), "activities", f"{m_type}_{i}", "grades.xml")
        sortorders.append(ET.parse(path).getroot().find('.//grade_item').findtext('sortorder'))
    assert len(set(sortorders)) == 3
    assert "1" not in sortorders  # 1 gehört dem Kurs-Gesamtergebnis
