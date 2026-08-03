"""Tests für LaTeX-Formeln in Fragetexten.

Fragetexte laufen nicht durch sanitize_for_moodle(), sondern über die eigene
QTI-Kette (process_html_and_images). Ohne dieselbe Umschreibung stünde der
LaTeX-Quelltext dort weiterhin roh im Kurs – genau das war in der
'Numerische Eingabe'-Frage des Musterkurses zu sehen."""

from qti.helpers import process_html_and_images


def _clean(html):
    return process_html_and_images(html, {})[0]


def test_formula_in_question_text_gets_moodle_delimiters():
    html = ('<p><span class="math" title="20%2B">20+\\frac{44}{1+\\frac{1}{1}}=</span>'
            '<textEntryInteraction responseIdentifier="RESPONSE_1"/></p>')
    result = _clean(html)

    # Das abschließende '=' gehört zur Formel und muss mit hineinwandern.
    assert "\\(20+\\frac{44}{1+\\frac{1}{1}}=\\)" in result
    assert 'class="math"' not in result


def test_interaction_element_survives_the_rewrite():
    # Die Lücke selbst darf nicht verlorengehen – sonst hat die Frage kein
    # Eingabefeld mehr.
    html = '<p><span class="math">x</span><textEntryInteraction responseIdentifier="R1"/></p>'
    assert "textEntryInteraction" in _clean(html)


def test_question_without_a_formula_is_unchanged():
    html = '<p>Wie viele Bundesländer hat Deutschland?</p>'
    assert _clean(html) == html


def test_image_rewriting_still_works_alongside_formulas():
    # Beide Umschreibungen greifen im selben Durchlauf.
    html = '<p><span class="math">a</span><img src="bild.png"></p>'
    result, files = process_html_and_images(html, {"bild.png": b"bilddaten"})

    assert "\\(a\\)" in result
    assert "@@PLUGINFILE@@/bild.png" in result
    assert [entry["name"] for entry in files] == ["bild.png"]
