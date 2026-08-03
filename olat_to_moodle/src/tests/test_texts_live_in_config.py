"""Prüft, dass im Kurs sichtbare Meldungen in config.py stehen.

Wer die Wortwahl einer Warnung ändern will, soll an einer Stelle nachsehen
müssen, nicht in vier Modulen. Erkannt werden Zeichenketten, die eine
Meldung an Lehrende oder Lernende enthalten – also HTML-Fließtext mit
'Achtung:' oder 'Hinweis:'.

XML-Bausteine des Moodle-Backup-Formats sind ausdrücklich NICHT gemeint:
das ist Moodles Dateiformat und kein Text, den jemand anpassen würde.
"""

import ast
import os

# Module, die eigene Anzeigetexte enthalten dürfen, mit Begründung.
# conversion_report.py baut das Systemprotokoll als zusammenhängendes
# HTML-Dokument; dort sind Überschriften, Layout und Fließtext so
# verschränkt, dass einzelne Sätze in config.py den Zusammenhang zerreißen
# würden statt ihn zugänglich zu machen.
ALLOWED_MODULES = {"conversion_report.py"}

SOURCE_ROOT = os.path.join(os.path.dirname(__file__), "..")
SKIPPED_DIRS = {"__pycache__", "moodle_musterkurs", "tests"}
MESSAGE_MARKERS = ("Achtung:", "Hinweis:")


def _inline_messages():
    """[(Datei, Zeile, Textanfang)] für Meldungen außerhalb von config.py."""
    findings = []
    for dirpath, dirnames, filenames in os.walk(SOURCE_ROOT):
        dirnames[:] = [name for name in dirnames if name not in SKIPPED_DIRS]
        for filename in sorted(filenames):
            if not filename.endswith(".py") or filename in ALLOWED_MODULES | {"config.py"}:
                continue
            path = os.path.join(dirpath, filename)
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())

            docstrings = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            }

            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if id(node) in docstrings:
                    continue
                if "<" not in node.value:
                    continue
                if any(marker in node.value for marker in MESSAGE_MARKERS):
                    relative = os.path.relpath(path, SOURCE_ROOT).replace(os.sep, "/")
                    findings.append((relative, node.lineno, node.value.strip()[:60]))
    return findings


def test_no_message_text_outside_config():
    findings = _inline_messages()
    assert not findings, (
        "Diese Meldungen gehören nach config.py:\n" +
        "\n".join(f"  {path}:{line}  {text}..." for path, line, text in findings))


def test_the_allowlist_has_no_stale_entries():
    # Ein Modul, das längst keine eigenen Texte mehr hat, würde als Ausnahme
    # neue Texte unbemerkt durchlassen.
    for filename in ALLOWED_MODULES:
        matches = [os.path.join(dirpath, name)
                   for dirpath, _, names in os.walk(SOURCE_ROOT)
                   for name in names if name == filename]
        assert matches, f"Ausnahme für nicht vorhandenes Modul: {filename}"
