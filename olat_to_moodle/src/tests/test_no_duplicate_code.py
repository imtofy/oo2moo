"""Prüft, dass derselbe Code nicht an zwei Stellen steht.

Verglichen werden Funktionsrümpfe in normalisierter Form: Docstring entfernt,
String- und Zahlenliterale vereinheitlicht. Damit fallen auch Kopien auf, bei
denen jemand nur die Texte ausgetauscht hat. True/False/None bleiben dagegen
unterscheidbar – sie tragen Bedeutung, nicht Beispieldaten (sonst gälten etwa
ein Zusage- und ein Absage-Handler als dasselbe).

Kleine Rümpfe bleiben außen vor: zwei Funktionen, die beide nur einen Wert
durchreichen, sind kein Duplikat, sondern zufällig gleich kurz.
"""

import ast
import collections
import hashlib
import os

# Mindestgröße eines Rumpfes in AST-Knoten. Darunter liegen nur Einzeiler
# (ein return, eine Zuweisung), deren Gleichheit nichts über Duplikate sagt.
MIN_BODY_NODES = 15

# Rümpfe, die mehrfach vorkommen dürfen, mit Begründung. Aktuell leer –
# jedes echte Duplikat wurde zusammengelegt statt hier eingetragen.
ALLOWED_DUPLICATE_BODIES: dict[str, str] = {}

SOURCE_ROOT = os.path.join(os.path.dirname(__file__), "..")
SKIPPED_DIRS = {"__pycache__", "moodle_musterkurs", "tests"}


class _NormalizeLiterals(ast.NodeTransformer):
    """Ersetzt Text- und Zahlenliterale durch einen Platzhalter, damit eine
    Kopie mit ausgetauschten Werten trotzdem als solche erkennbar bleibt."""

    def visit_Constant(self, node):
        if isinstance(node.value, (str, int, float, complex)) and not isinstance(node.value, bool):
            return ast.copy_location(ast.Constant(value="<literal>"), node)
        return node


def _body_signature(node):
    """(Fingerabdruck, Knotenzahl) des normalisierten Rumpfes ohne Docstring."""
    body = list(node.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    if not body:
        return None, 0
    module = _NormalizeLiterals().visit(ast.Module(body=body, type_ignores=[]))
    dump = ast.dump(module)
    return hashlib.sha1(dump.encode()).hexdigest(), sum(1 for _ in ast.walk(module))


def _bodies_by_signature():
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
                signature, size = _body_signature(node)
                if signature and size >= MIN_BODY_NODES:
                    relative = os.path.relpath(path, SOURCE_ROOT).replace(os.sep, "/")
                    found[signature].append(f"{relative}:{node.lineno} {node.name}()")
    return found


def test_no_function_body_appears_twice():
    duplicates = {signature: sites for signature, sites in _bodies_by_signature().items()
                  if len(sites) > 1 and signature not in ALLOWED_DUPLICATE_BODIES}

    assert not duplicates, (
        "Gleicher Code an mehreren Stellen:\n" +
        "\n".join("  " + " == ".join(sites) for sites in duplicates.values()))


def test_the_allowlist_has_no_stale_entries():
    # Ein Eintrag, dessen Duplikat längst zusammengelegt ist, würde ein neues
    # Duplikat desselben Rumpfes unbemerkt durchlassen.
    found = _bodies_by_signature()
    for signature, reason in ALLOWED_DUPLICATE_BODIES.items():
        assert len(found.get(signature, [])) > 1, f"Ausnahme ohne Duplikat: {reason}"


def test_booleans_are_not_normalised_away():
    # Sonst gälten ein Zusage- und ein Absage-Handler als derselbe Code.
    accept = ast.parse("def f():\n    self.result = True\n    self.master.quit()").body[0]
    reject = ast.parse("def f():\n    self.result = False\n    self.master.quit()").body[0]
    assert _body_signature(accept)[0] != _body_signature(reject)[0]


def test_swapped_texts_still_count_as_a_duplicate():
    # Der Sinn der Normalisierung: eine Kopie mit anderen Texten ist eine Kopie.
    first = ast.parse("def f(x):\n    y = 'eins'\n    return y + str(x)").body[0]
    second = ast.parse("def g(x):\n    y = 'zwei'\n    return y + str(x)").body[0]
    assert _body_signature(first)[0] == _body_signature(second)[0]
