"""Tests für main._resolve_moodle_type() – die Entscheidung, ob ein
'document'-Baustein eine Datei-Ressource oder ein Verzeichnis wird.

Entscheidend ist die Richtung der Prüfung: gefragt wird, ob Moodle die Datei
anzeigen KANN, nicht ob sie zu einer Liste bekannter Problemformate gehört.
Eine unbekannte Endung muss deshalb ohne Zutun im Verzeichnis landen."""

import main


def _type_of(filename, olat_type="document"):
    return main._resolve_moodle_type(olat_type, {'html_file': filename})


def test_displayable_formats_stay_a_file_resource():
    for filename in ("bild.png", "foto.JPG", "grafik.svg", "handout.pdf",
                     "clip.mp4", "aufnahme.mp3", "seite.html", "notiz.txt"):
        assert _type_of(filename) == "resource", filename


def test_office_formats_become_a_folder():
    for filename in ("skript.docx", "tabelle.xlsx", "folien.pptx",
                     "alt.doc", "alt.xls", "alt.ppt", "text.rtf"):
        assert _type_of(filename) == "folder", filename


def test_unknown_extension_becomes_a_folder_without_being_listed():
    # Der eigentliche Zweck der Positivliste: diese Endungen stehen nirgends
    # im Code, als Ressource würde Moodle ihr XML als Rohtext ausgeben.
    assert _type_of("Diagramm.drawio") == "folder"
    assert _type_of("Whiteboard.dwb") == "folder"
    assert _type_of("beliebig.gibtesnicht") == "folder"


def test_file_without_extension_becomes_a_folder():
    assert _type_of("LIESMICH") == "folder"
    assert _type_of("") == "folder"


def test_extension_check_ignores_case():
    assert _type_of("BILD.PNG") == "resource"
    assert _type_of("SKRIPT.DOCX") == "folder"


def test_other_block_types_are_unaffected():
    # Die Sonderregel gilt nur für 'document' – ein Ordner-Baustein mit
    # gleichnamiger Datei darf nicht plötzlich anders behandelt werden.
    assert _type_of("Diagramm.drawio", olat_type="bc") == "folder"
    assert _type_of("egal.drawio", olat_type="sp") == "page"
    assert _type_of("egal.drawio", olat_type="scorm") == "scorm"
