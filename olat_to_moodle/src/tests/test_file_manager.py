"""Tests für file_manager.py – Content-addressed Speicherung + files.xml-Bau."""

import os
import hashlib
import xml.etree.ElementTree as ET

from conversion.file_manager import FileManager, write_xml


def test_write_xml_adds_header(tmp_path):
    path = tmp_path / "out.xml"
    write_xml(str(path), "<root></root>")
    content = path.read_text(encoding='utf-8')
    assert content.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
    assert content.count('<?xml') == 1


def test_add_moodle_file_writes_content_addressed_physical_file(tmp_path):
    fm = FileManager(str(tmp_path))
    data = b"Testinhalt einer Datei"
    file_id = fm.add_moodle_file(data, "test.txt", contextid=10, component="mod_page",
                                 filearea="content", itemid=0, now=1700000000)
    expected_hash = hashlib.sha1(data).hexdigest()
    expected_path = os.path.join(str(tmp_path), "files", expected_hash[:2], expected_hash)
    assert os.path.exists(expected_path)
    assert open(expected_path, "rb").read() == data
    assert file_id == 1


def test_add_moodle_file_same_content_twice_writes_physical_file_only_once(tmp_path):
    fm = FileManager(str(tmp_path))
    data = b"Identischer Inhalt"
    id1 = fm.add_moodle_file(data, "a.txt", 1, "mod_page", "content", 0, 1700000000)
    id2 = fm.add_moodle_file(data, "b.txt", 2, "mod_folder", "content", 0, 1700000000)
    # Zwei getrennte files.xml-Einträge (unterschiedlicher Kontext/Name),
    # aber dieselbe physische Datei auf der Platte (Dedup über den Hash).
    assert id1 != id2
    expected_hash = hashlib.sha1(data).hexdigest()
    file_dir = os.path.join(str(tmp_path), "files", expected_hash[:2])
    assert len(os.listdir(file_dir)) == 1


def test_add_moodle_directory_returns_same_id_for_repeated_same_key(tmp_path):
    fm = FileManager(str(tmp_path))
    id1 = fm.add_moodle_directory(contextid=1, component="mod_folder", filearea="content",
                                  itemid=0, now=1700000000, filepath="/unterordner/")
    id2 = fm.add_moodle_directory(contextid=1, component="mod_folder", filearea="content",
                                  itemid=0, now=1700000000, filepath="/unterordner/")
    assert id1 == id2


def test_add_moodle_directory_different_filepath_gets_different_id(tmp_path):
    fm = FileManager(str(tmp_path))
    id1 = fm.add_moodle_directory(1, "mod_folder", "content", 0, 1700000000, filepath="/a/")
    id2 = fm.add_moodle_directory(1, "mod_folder", "content", 0, 1700000000, filepath="/b/")
    assert id1 != id2


def test_generate_files_xml_lists_directory_and_file_entries(tmp_path):
    fm = FileManager(str(tmp_path))
    fm.add_moodle_directory(1, "mod_folder", "content", 0, 1700000000)
    fm.add_moodle_file(b"Inhalt", "dokument.pdf", 1, "mod_folder", "content", 0, 1700000000)
    xml = fm.generate_files_xml()
    root = ET.fromstring(xml)
    files = root.findall('file')
    assert len(files) == 2
    filenames = {handle.findtext('filename') for handle in files}
    assert filenames == {'.', 'dokument.pdf'}


def test_generate_files_xml_guesses_mimetype_from_extension(tmp_path):
    fm = FileManager(str(tmp_path))
    fm.add_moodle_file(b"%PDF-1.4", "dokument.pdf", 1, "mod_resource", "content", 0, 1700000000)
    xml = fm.generate_files_xml()
    root = ET.fromstring(xml)
    assert root.find('file').findtext('mimetype') == 'application/pdf'


def test_generate_files_xml_falls_back_to_octet_stream_for_unknown_extension(tmp_path):
    fm = FileManager(str(tmp_path))
    fm.add_moodle_file(b"???", "datei.seltsameendung123", 1, "mod_resource", "content", 0, 1700000000)
    xml = fm.generate_files_xml()
    root = ET.fromstring(xml)
    assert root.find('file').findtext('mimetype') == 'application/octet-stream'


def test_generate_files_xml_escapes_special_characters_in_filename(tmp_path):
    fm = FileManager(str(tmp_path))
    fm.add_moodle_file(b"x", 'Datei & "Name".txt', 1, "mod_resource", "content", 0, 1700000000)
    xml = fm.generate_files_xml()
    root = ET.fromstring(xml)  # wirft bei kaputtem XML von selbst
    assert root.find('file').findtext('filename') == 'Datei & "Name".txt'


# --- Absichtlich leere/randständige Eingaben ---

def test_generate_files_xml_with_nothing_registered_is_still_valid_xml():
    fm = FileManager("irrelevant")  # keine Datei-Operation, kein echtes Verzeichnis nötig
    xml = fm.generate_files_xml()
    root = ET.fromstring(xml)
    assert root.findall('file') == []


def test_add_moodle_file_with_empty_content_does_not_raise(tmp_path):
    fm = FileManager(str(tmp_path))
    file_id = fm.add_moodle_file(b"", "leer.txt", 1, "mod_resource", "content", 0, 1700000000)
    assert file_id == 1


def test_file_area_names_counts_up_for_every_further_conflict():
    from conversion.file_manager import FileAreaNames

    names = FileAreaNames()
    assert names.assign("b.png", b"EINS") == "b.png"
    assert names.assign("b.png", b"ZWEI") == "b_1.png"
    assert names.assign("b.png", b"DREI") == "b_2.png"
    assert names.assign("b.png", b"VIER") == "b_3.png"
    # Gleicher Inhalt wie die erste Datei -> derselbe Name, kein neuer Eintrag.
    assert names.assign("b.png", b"EINS") == "b.png"


def test_file_area_names_handles_files_without_extension():
    from conversion.file_manager import FileAreaNames

    names = FileAreaNames()
    assert names.assign("liesmich", b"A") == "liesmich"
    assert names.assign("liesmich", b"B") == "liesmich_1"


def test_file_area_names_keeps_areas_apart():
    # Pro Dateibereich eine eigene Instanz – derselbe Name in zwei Bereichen
    # ist kein Konflikt (z.B. dasselbe Bild in zwei Buchkapiteln).
    from conversion.file_manager import FileAreaNames

    chapter_1, chapter_2 = FileAreaNames(), FileAreaNames()
    assert chapter_1.assign("bild.png", b"A") == "bild.png"
    assert chapter_2.assign("bild.png", b"B") == "bild.png"


def test_file_area_names_renames_every_further_reference_in_html():
    from conversion.file_manager import FileAreaNames

    names = FileAreaNames()
    html = ('<img src="@@PLUGINFILE@@/b.png">'
            '<img src="@@PLUGINFILE@@/b.png">'
            '<img src="@@PLUGINFILE@@/b.png">')
    for daten in (b"EINS", b"ZWEI", b"DREI"):
        _name, html = names.assign_in_html("b.png", daten, html)
    assert html == ('<img src="@@PLUGINFILE@@/b.png">'
                    '<img src="@@PLUGINFILE@@/b_1.png">'
                    '<img src="@@PLUGINFILE@@/b_2.png">')


def test_unique_filename_keeps_compound_extensions_together():
    from conversion.file_manager import unique_filename

    taken = {"archiv.tar.gz", "sicherung.TAR.GZ", "bericht.pdf", "liesmich"}
    assert unique_filename("archiv.tar.gz", taken) == "archiv_1.tar.gz"
    # Groß-/Kleinschreibung der Endung darf keine Rolle spielen.
    assert unique_filename("sicherung.TAR.GZ", taken) == "sicherung_1.TAR.GZ"
    assert unique_filename("bericht.pdf", taken) == "bericht_1.pdf"
    assert unique_filename("liesmich", taken) == "liesmich_1"
    # Ein Name mit Punkten, aber ohne bekannte Doppelendung, trennt am letzten.
    assert unique_filename("a.b.c.png", {"a.b.c.png"}) == "a.b.c_1.png"
