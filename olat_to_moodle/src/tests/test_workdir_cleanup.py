"""Tests für main._remove_stale_workdirs() – das Aufräumen von
Arbeitsverzeichnissen, die ein abgebrochener Lauf hinterlassen hat.

Die Konvertierung läuft in einem Daemon-Thread: wird das Fenster mittendrin
geschlossen, beendet Python den Prozess, ohne den Kontextmanager von
tempfile.TemporaryDirectory noch abzuschließen."""

import os
import tempfile

import main


def test_removes_only_its_own_leftovers(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    leftover = tmp_path / f"{main._WORKDIR_PREFIX}abc123"
    (leftover / "files").mkdir(parents=True)
    (leftover / "files" / "inhalt.bin").write_bytes(b"x" * 1024)
    unrelated = tmp_path / "irgendetwas_anderes"
    unrelated.mkdir()
    lose_datei = tmp_path / f"{main._WORKDIR_PREFIX}keine_mappe.txt"
    lose_datei.write_text("kein Verzeichnis", encoding="utf-8")

    main._remove_stale_workdirs()

    assert not leftover.exists()
    assert unrelated.exists()
    assert lose_datei.exists()


def test_survives_an_unreadable_temp_directory(monkeypatch):
    # Kein Zugriff auf %TEMP% darf den Programmstart nicht verhindern.
    monkeypatch.setattr(tempfile, "gettempdir", lambda: "/gibt/es/nicht")
    monkeypatch.setattr(os, "listdir", lambda _p: (_ for _ in ()).throw(OSError("kein Zugriff")))
    main._remove_stale_workdirs()


def test_locked_directory_is_skipped_without_error(tmp_path, monkeypatch):
    # Ein noch laufender Zweitprozess hält sein Verzeichnis gesperrt – das
    # Löschen scheitert dann und muss folgenlos bleiben.
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    (tmp_path / f"{main._WORKDIR_PREFIX}gesperrt").mkdir()

    def rmtree_schlaegt_fehl(_path, ignore_errors=False):
        if not ignore_errors:
            raise OSError("gesperrt")

    monkeypatch.setattr(main.shutil, "rmtree", rmtree_schlaegt_fehl)
    main._remove_stale_workdirs()
