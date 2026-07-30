"""Tests für wiki_markup.to_html() - OLATs MediaWiki-artige Wiki-Syntax → HTML."""

from conversion.wiki_markup import to_html


def test_empty_input_returns_empty_string():
    assert to_html("") == ""
    assert to_html("   \n  ") == ""


def test_bold_and_italic():
    assert to_html("'''fett'''") == "<p><strong>fett</strong></p>"
    assert to_html("''kursiv''") == "<p><em>kursiv</em></p>"


def test_heading_levels():
    assert to_html("==Überschrift==") == "<h2>Überschrift</h2>"
    assert to_html("=====Tiefste Ebene=====") == "<h5>Tiefste Ebene</h5>"


def test_internal_link_with_display_text():
    assert to_html("[[Zielseite|Anzeigetext]]") == "<p>Anzeigetext</p>"


def test_internal_link_without_display_text_uses_page_name():
    assert to_html("[[Zielseite]]") == "<p>Zielseite</p>"


def test_bullet_list():
    html = to_html("* Erstens\n* Zweitens")
    assert html == "<ul><li>Erstens</li><li>Zweitens</li></ul>"


def test_numbered_list():
    html = to_html("# Erstens\n# Zweitens")
    assert html == "<ol><li>Erstens</li><li>Zweitens</li></ol>"


def test_switching_from_bullet_to_numbered_list_flushes_first_list():
    html = to_html("* Punkt\n# Nummer")
    assert html == "<ul><li>Punkt</li></ul><ol><li>Nummer</li></ol>"


def test_plain_paragraph_html_escaped():
    html = to_html("Ein Text mit <script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_blank_line_separates_paragraphs():
    html = to_html("Erster Absatz\n\nZweiter Absatz")
    assert html == "<p>Erster Absatz</p><p>Zweiter Absatz</p>"


# --- Absichtlich unsauberes/unbekanntes Markup (darf nicht crashen) ---

def test_unclosed_bold_markup_is_left_mostly_as_is_not_crashing():
    # Kein schließendes ''' - darf keine Exception werfen, das Sternchen-
    # Markup bleibt einfach als Text stehen.
    html = to_html("''Angefangener Fettdruck ohne Ende")
    assert html.startswith("<p>")
    assert "Angefangener Fettdruck ohne Ende" in html


def test_unknown_table_syntax_passes_through_as_escaped_text():
    # OLAT-Tabellen-Syntax ('{| ... |}') wird bewusst NICHT unterstützt -
    # muss als reiner (escapter) Text durchgereicht werden, nicht crashen.
    html = to_html("{| class=\"wikitable\" |}")
    assert "{|" in html
    assert "<table" not in html


def test_only_whitespace_lines_produce_no_output():
    assert to_html("\n\n   \n\t\n") == ""
