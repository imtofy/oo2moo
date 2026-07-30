"""Tests für anonymizer.py - sicherheitsrelevant: hier darf NICHTS echtes
durchrutschen. sanitize_vfs() läuft vor jedem anderen Modul über den Export."""

from conversion.anonymizer import sanitize_vfs
from config import PLACEHOLDER_USERNAME


def test_current_format_username_is_replaced():
    vfs = {"datei.xml": "Autor: BAA0000 hat editiert.".encode('utf-8')}
    replaced = sanitize_vfs(vfs)
    text = vfs["datei.xml"].decode('utf-8')
    assert "BAA0000" not in text
    assert PLACEHOLDER_USERNAME in text
    assert replaced == 1


def test_legacy_u_format_username_is_replaced():
    vfs = {"datei.xml": "Nutzer u123456789 war online.".encode('utf-8')}
    sanitize_vfs(vfs)
    assert "u123456789" not in vfs["datei.xml"].decode('utf-8')


def test_admin_account_name_is_replaced():
    vfs = {"datei.xml": "Bearbeitet von mustermann-admin.".encode('utf-8')}
    sanitize_vfs(vfs)
    assert "mustermann-admin" not in vfs["datei.xml"].decode('utf-8')


def test_email_address_is_replaced():
    vfs = {"datei.xml": "Kontakt: max.mustermann@beispiel-hochschule.de".encode('utf-8')}
    sanitize_vfs(vfs)
    assert "max.mustermann@beispiel-hochschule.de" not in vfs["datei.xml"].decode('utf-8')


def test_multiple_different_matches_in_same_file_all_replaced():
    vfs = {"datei.xml": "BAA0000 und admin@example.com und u000000001".encode('utf-8')}
    replaced = sanitize_vfs(vfs)
    text = vfs["datei.xml"].decode('utf-8')
    assert replaced == 3
    assert "BAA0000" not in text
    assert "admin@example.com" not in text
    assert "u000000001" not in text


def test_non_text_files_are_never_touched():
    original = b'\x89PNG\r\n\x1a\n binary content with BAA0000 inside'
    vfs = {"bild.png": original}
    replaced = sanitize_vfs(vfs)
    assert vfs["bild.png"] == original  # unangetastet, auch wenn's zufaellig passen wuerde
    assert replaced == 0


def test_plain_text_without_matches_stays_unchanged():
    vfs = {"datei.xml": "Ganz normaler Text ohne Nutzerkennung.".encode('utf-8')}
    replaced = sanitize_vfs(vfs)
    assert vfs["datei.xml"].decode('utf-8') == "Ganz normaler Text ohne Nutzerkennung."
    assert replaced == 0


def test_pattern_does_not_partially_match_longer_digit_sequence():
    # \b am Ende von \d{4} darf NICHT mitten in einer längeren Ziffernfolge
    # matchen - sonst würde z.B. eine Bestellnummer faelschlich anonymisiert.
    vfs = {"datei.xml": "Bestellnummer BAA00001234 bleibt unberuehrt.".encode('utf-8')}
    replaced = sanitize_vfs(vfs)
    assert replaced == 0
    assert "BAA00001234" in vfs["datei.xml"].decode('utf-8')


def test_nested_path_with_pipe_separator_still_checked_by_extension():
    # CourseManifest markiert entpackte repo.zip/oonode.zip-Pfade mit '|' -
    # die Endungspruefung muss den Teil NACH dem letzten '|' nehmen.
    vfs = {"export/1/repo.zip|seite.html": "Autor BAA0000".encode('utf-8')}
    replaced = sanitize_vfs(vfs)
    assert replaced == 1


# --- Absichtlich kaputte/randständige Eingaben ---

def test_non_utf8_binary_data_in_text_extension_does_not_raise():
    # Datei heisst .xml, ist aber kein gueltiges UTF-8 (z.B. korrupter Export) -
    # darf nicht crashen, wird einfach uebersprungen.
    vfs = {"kaputt.xml": b'\xff\xfe\x00\x01 kein g\xfcltiges UTF-8'}
    replaced = sanitize_vfs(vfs)
    assert replaced == 0


def test_empty_vfs_returns_zero():
    assert sanitize_vfs({}) == 0


def test_uppercase_extension_is_still_recognized():
    vfs = {"DATEI.XML": "BAA0000".encode('utf-8')}
    # .lower() auf die Endung wird im Code bereits angewendet - hier nur
    # sicherstellen, dass das auch wirklich Groß-/Kleinschreibung unabhaengig
    # funktioniert, nicht nur zufaellig bei Kleinbuchstaben.
    replaced = sanitize_vfs(vfs)
    assert replaced == 1
