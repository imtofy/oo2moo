"""Tests für validate_moodle_backup_integrity() – vor allem die Prüfung der
Verzeichnis-Marker, weil ein fehlender Marker in Moodle dazu führt, dass die
Dateien seines Bereichs beim Restore kommentarlos verschwinden."""

import hashlib
import os

from validators.backup_validator import validate_moodle_backup_integrity

_LEER = hashlib.sha1(b"").hexdigest()


def _entry(name, contextid, component, filearea, itemid=0, filepath="/"):
    return (f'<file id="1"><contenthash>{_LEER}</contenthash>'
            f'<contextid>{contextid}</contextid><component>{component}</component>'
            f'<filearea>{filearea}</filearea><itemid>{itemid}</itemid>'
            f'<filename>{name}</filename><filepath>{filepath}</filepath></file>')


def _backup(tmp_path, *entries):
    """Legt ein Minimal-Backup an: files.xml plus die physische Leerdatei,
    auf die alle Einträge über ihren contenthash zeigen."""
    folder = tmp_path / "files" / _LEER[:2]
    folder.mkdir(parents=True)
    (folder / _LEER).write_bytes(b"")
    (tmp_path / "files.xml").write_text(
        "<files>" + "".join(entries) + "</files>", encoding="utf-8")
    return str(tmp_path)


def test_area_with_marker_is_accepted(tmp_path, capsys):
    validate_moodle_backup_integrity(_backup(
        tmp_path,
        _entry(".", 5, "mod_page", "content"),
        _entry("bild.png", 5, "mod_page", "content")))
    assert "[FEHLER]" not in capsys.readouterr().out


def test_area_without_marker_is_reported(tmp_path, capsys):
    # Entscheidend: ein ANDERER Bereich hat einen Marker. Eine global zählende
    # Prüfung würde diesen Fall durchwinken, geprüft wird pro Bereich.
    validate_moodle_backup_integrity(_backup(
        tmp_path,
        _entry(".", 5, "mod_page", "content"),
        _entry("bild.png", 5, "mod_page", "content"),
        _entry("paket.js", 9, "mod_scorm", "content")))
    output = capsys.readouterr().out
    assert output.count("[FEHLER]") == 1
    assert "mod_scorm/content" in output
    assert "paket.js" in output


def test_subdirectory_needs_its_own_marker(tmp_path, capsys):
    # Jeder Unterordner ist ein eigener Bereich – der Marker des Wurzelpfads
    # deckt ihn nicht mit ab.
    validate_moodle_backup_integrity(_backup(
        tmp_path,
        _entry(".", 5, "mod_scorm", "content"),
        _entry("start.html", 5, "mod_scorm", "content"),
        _entry("foto.jpg", 5, "mod_scorm", "content", filepath="/mobile/")))
    output = capsys.readouterr().out
    assert output.count("[FEHLER]") == 1
    assert "/mobile/" in output


def test_missing_physical_file_is_reported(tmp_path, capsys):
    # In files.xml registriert, aber unter files/<hash[:2]>/<hash> nicht da.
    path = _backup(tmp_path, _entry(".", 5, "mod_page", "content"),
                   _entry("bild.png", 5, "mod_page", "content"))
    os.remove(os.path.join(path, "files", _LEER[:2], _LEER))
    validate_moodle_backup_integrity(path)
    assert "Physische Datei fehlt" in capsys.readouterr().out


def test_pluginfile_reference_needs_the_file_in_the_root_path(tmp_path, capsys):
    # Ein @@PLUGINFILE@@-Verweis ohne Pfadangabe löst im Wurzelpfad des
    # Dateibereichs auf – eine gleichnamige Datei im Unterordner erfüllt ihn
    # nicht und darf die Prüfung nicht besänftigen.
    path = _backup(
        tmp_path,
        _entry(".", 5, "mod_page", "content"),
        _entry(".", 5, "mod_page", "content", filepath="/unterordner/"),
        _entry("bild.png", 5, "mod_page", "content", filepath="/unterordner/"))
    activity = tmp_path / "activities" / "page_7"
    activity.mkdir(parents=True)
    (activity / "page.xml").write_text(
        '<activity contextid="5"><page><content>'
        '&lt;img src="@@PLUGINFILE@@/bild.png"&gt;</content></page></activity>',
        encoding="utf-8")

    validate_moodle_backup_integrity(path)

    output = capsys.readouterr().out
    assert "bild.png" in output and "fehlt in files.xml" in output
