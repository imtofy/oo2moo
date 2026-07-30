"""Tests für qti/helpers.py - gemeinsame Bausteine, die jedes qtype_*.py-
Modul verwendet (ID-Vergabe, Fraction-Berechnung, HTML-Bereinigung)."""

from qti.helpers import (
    IdGenerator, strip_tags, element_inner_html, calculate_choice_fractions,
    is_qti_item, escape_cloze_text, format_fraction_decimal, process_html_and_images,
)
import xml.etree.ElementTree as ET


def test_id_generator_counts_up_sequentially_from_default_start():
    gen = IdGenerator()
    assert [gen.next(), gen.next(), gen.next()] == [1, 2, 3]


def test_id_generator_respects_custom_start():
    gen = IdGenerator(start=100)
    assert gen.next() == 100


def test_strip_tags_removes_all_html():
    assert strip_tags("<p>Text <strong>fett</strong></p>") == "Text fett"


def test_strip_tags_handles_none_and_empty():
    assert strip_tags(None) == ""
    assert strip_tags("") == ""


def test_element_inner_html_keeps_child_tags():
    elem = ET.fromstring("<div>Text <b>fett</b> Ende</div>")
    assert element_inner_html(elem) == "Text <b>fett</b> Ende"


def test_calculate_choice_fractions_single_choice_gives_100_to_correct_only():
    choices = [{'is_correct': True}, {'is_correct': False}, {'is_correct': False}]
    result = calculate_choice_fractions(choices, single=True)
    assert result[0]['fraction'] == "100.0"
    assert result[1]['fraction'] == "0.0"
    assert result[2]['fraction'] == "0.0"


def test_calculate_choice_fractions_multi_choice_splits_evenly():
    choices = [{'is_correct': True}, {'is_correct': True}, {'is_correct': False}, {'is_correct': False}]
    result = calculate_choice_fractions(choices, single=False)
    assert result[0]['fraction'] == result[1]['fraction']
    assert float(result[0]['fraction']) > 0
    assert float(result[2]['fraction']) < 0  # Malus auf falsche Antworten


def test_calculate_choice_fractions_no_correct_answer_gives_zero_to_all():
    choices = [{'is_correct': False}, {'is_correct': False}]
    result = calculate_choice_fractions(choices, single=False)
    assert all(c['fraction'] == "0.0" for c in result)


def test_is_qti_item_matches_real_tag_not_ref_variant():
    assert is_qti_item('<assessmentItem title="x">') is True
    assert is_qti_item('<assessmentItemRef identifier="x"/>') is False


def test_escape_cloze_text_escapes_special_characters():
    assert escape_cloze_text("a{b}c=d#e~f") == r"a\{b\}c\=d\#e\~f"


def test_format_fraction_decimal_converts_percentage_to_moodle_decimal():
    assert format_fraction_decimal("100.0") == "1.0000000"
    assert format_fraction_decimal("-50.0") == "-0.5000000"


def test_process_html_and_images_rewrites_known_file_to_pluginfile():
    vfs = {"bild.png": b"fake-image-data"}
    html, files = process_html_and_images('<img src="bild.png">', vfs)
    assert '@@PLUGINFILE@@/bild.png' in html
    assert files[0]['name'] == 'bild.png'


def test_process_html_and_images_leaves_unknown_src_untouched():
    html, files = process_html_and_images('<img src="unbekannt.png">', {})
    assert 'unbekannt.png' in html
    assert '@@PLUGINFILE@@' not in html
    assert files == []


def test_process_html_and_images_leaves_absolute_url_untouched():
    html, files = process_html_and_images('<img src="https://example.com/bild.png">', {})
    assert html == '<img src="https://example.com/bild.png">'
    assert files == []
