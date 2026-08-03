"""Prüft, dass nicht zwei verschiedene Funktionen denselben Namen tragen.

Gleicher Name bei unterschiedlicher Implementierung ist eine Falle: beim
Lesen einer Aufrufstelle lässt sich nicht mehr erkennen, welche der beiden
gemeint ist, und beim Suchen im Projekt kommen Treffer aus beiden. Gleicher
Name bei gleichem Rumpf ist dagegen unkritisch – das ist derselbe Code an
zwei Stellen und fällt unter die Duplikat-Prüfung, nicht hierher.

Der Test lässt bewusst nur benannte Ausnahmen zu, damit eine neue Kollision
auffällt, statt sich einzuschleichen."""

import ast
import collections
import hashlib
import os

# Namen, die mehrfach vorkommen dürfen, mit Begründung:
#   __init__ und andere Sonder-Methoden gehören zum Sprachprotokoll – jede
#   Klasse bringt ihre eigene mit, ein gemeinsamer Name ist hier bedeutungslos.
#   _toggle_theme: Lizenz-Gate und Hauptfenster schalten dasselbe um, hängen
#   aber an unterschiedlichen Widgets und laufen zu verschiedenen Zeitpunkten
#   (das Gate läuft, bevor das Hauptfenster existiert).
ALLOWED_DUPLICATE_NAMES = {"_toggle_theme"}

SOURCE_ROOT = os.path.join(os.path.dirname(__file__), "..")
SKIPPED_DIRS = {"__pycache__", "moodle_musterkurs", "tests"}


def _function_definitions():
    """{Funktionsname: [(Datei, Zeile, Rumpf-Fingerabdruck)]} für den
    gesamten Produktivcode."""
    found = collections.defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(SOURCE_ROOT):
        dirnames[:] = [name for name in dirnames if name not in SKIPPED_DIRS]
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("__") and node.name.endswith("__"):
                    continue
                body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
                relative = os.path.relpath(path, SOURCE_ROOT).replace(os.sep, "/")
                found[node.name].append(
                    (relative, node.lineno, hashlib.sha1(body.encode()).hexdigest()))
    return found


def test_no_two_functions_share_a_name_with_different_bodies():
    collisions = {}
    for name, sites in _function_definitions().items():
        if name in ALLOWED_DUPLICATE_NAMES or len(sites) < 2:
            continue
        if len({fingerprint for _, _, fingerprint in sites}) > 1:
            collisions[name] = [f"{path}:{line}" for path, line, _ in sites]

    assert not collisions, (
        "Gleichnamige Funktionen mit unterschiedlicher Implementierung:\n" +
        "\n".join(f"  '{name}': {', '.join(sites)}" for name, sites in sorted(collisions.items())))


def test_the_allowlist_has_no_stale_entries():
    # Ein Eintrag, dessen Kollision längst behoben ist, würde eine neue
    # Kollision desselben Namens unbemerkt durchlassen.
    definitions = _function_definitions()
    for name in ALLOWED_DUPLICATE_NAMES:
        sites = definitions.get(name, [])
        assert len(sites) > 1, f"'{name}' steht auf der Ausnahmeliste, kommt aber nur {len(sites)}x vor"
