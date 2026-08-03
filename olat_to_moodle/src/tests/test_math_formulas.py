"""Tests für die Übernahme von LaTeX-Formeln aus OLAT.

OLAT markiert Formeln mit <span class="math"> und rendert sie über MathJax.
Moodle erkennt LaTeX nur an eigenen Trennzeichen (\\( … \\) für den Fließtext,
siehe filter/mathjaxloader). Ohne Umschreibung zeigt Moodle den rohen
Quelltext der Formel statt der gesetzten Formel."""

from conversion.html_cleaner import sanitize_for_moodle


def _clean(html):
    return sanitize_for_moodle(html)[0]


def test_math_span_becomes_moodle_delimiters():
    html = '<p><span class="math" title="20%2B1">20+\\frac{44}{1}</span></p>'
    result = _clean(html)

    assert "\\(20+\\frac{44}{1}\\)" in result
    assert 'class="math"' not in result


def test_formula_content_is_kept_verbatim():
    # Backslashes und geschweifte Klammern müssen die Bereinigung unverändert
    # überstehen – sie sind die Formel selbst.
    html = '<span class="math">\\sqrt{x_1}</span>'
    assert "\\(\\sqrt{x_1}\\)" in _clean(html)


def test_comparison_operator_stays_html_escaped():
    # '<' muss in HTML als &lt; stehen, sonst begänne dort ein Tag. Der
    # Browser wandelt es zurück, bevor MathJax die Formel liest.
    assert "\\(a &lt; b\\)" in _clean('<span class="math">a &lt; b</span>')


def test_several_formulas_in_one_text():
    html = '<p><span class="math">x^2</span> und <span class="math">y^2</span></p>'
    result = _clean(html)
    assert "\\(x^2\\)" in result and "\\(y^2\\)" in result


def test_span_without_math_class_is_untouched():
    html = '<p><span class="hinweis">kein LaTeX</span></p>'
    result = _clean(html)
    assert "\\(" not in result
    assert "kein LaTeX" in result


def test_empty_math_span_is_dropped():
    # Ein leerer Formel-Container ergäbe '\\(\\)' – in Moodle ein sichtbarer
    # Rest ohne Inhalt.
    assert "\\(" not in _clean('<p><span class="math"></span>Text</p>')


def test_math_span_with_nested_markup_uses_its_text():
    html = '<span class="math"><em>a</em>+b</span>'
    result = _clean(html)
    assert "\\(a+b\\)" in result
    assert "<em>" not in result
