"""Tests für die qti/qtype_*.py-Fragetyp-Parser.

Jeder parse_X() bekommt denselben rohen <assessmentItem>-XML-Baum und muss
entweder eine erkannte Frage (Dict) oder None (Fallback auf den nächsten
Fragetyp in der Erkennungskette, siehe qti_pipeline.py) liefern – nie eine
Exception."""

import xml.etree.ElementTree as ET

from qti.qtype_truefalse import parse_truefalse
from qti.qtype_multichoice import parse_multichoice
from qti.qtype_shortanswer import parse_shortanswer
from qti.qtype_essay import parse_essay
from qti.qtype_kprim import parse_kprim
from qti.qtype_matching import parse_matching
from qti.qtype_order import parse_order
from qti.qtype_hottext import parse_hottext
from qti.qtype_hotspot import parse_hotspot
from qti.qtype_inlinechoice import parse_inlinechoice
from qti.qtype_cloze import parse_cloze
from qti.qtype_matrix import parse_matrix
from qti.qtype_drawing import parse_drawing


_EMPTY_ITEM = ET.fromstring('<assessmentItem title="Leer"><itemBody></itemBody></assessmentItem>')

# Jeder Parser bekommt (root, vfs) – vfs bleibt für diese Tests immer leer.
ALL_PARSERS = [
    parse_essay, parse_kprim, parse_matching, parse_order, parse_hottext,
    parse_hotspot, parse_inlinechoice, parse_cloze, parse_matrix, parse_drawing,
]


def _true_false_item(true_text="Wahr", false_text="Falsch", cardinality="single"):
    xml = f"""<assessmentItem title="Wahr-Falsch-Frage">
      <responseDeclaration identifier="RESPONSE" cardinality="{cardinality}">
        <correctResponse><value>a</value></correctResponse>
      </responseDeclaration>
      <itemBody>
        <p>Aussage korrekt?</p>
        <choiceInteraction responseIdentifier="RESPONSE">
          <simpleChoice identifier="a">{true_text}</simpleChoice>
          <simpleChoice identifier="b">{false_text}</simpleChoice>
        </choiceInteraction>
      </itemBody>
    </assessmentItem>"""
    return ET.fromstring(xml)


def _multichoice_item(cardinality="multiple", correct=("a", "c")):
    correct_values = "".join(f"<value>{value}</value>" for value in correct)
    xml = f"""<assessmentItem title="Multiple-Choice-Frage">
      <responseDeclaration identifier="RESPONSE" cardinality="{cardinality}">
        <correctResponse>{correct_values}</correctResponse>
      </responseDeclaration>
      <itemBody>
        <p>Welche Aussagen stimmen?</p>
        <choiceInteraction responseIdentifier="RESPONSE">
          <simpleChoice identifier="a">Option A</simpleChoice>
          <simpleChoice identifier="b">Option B</simpleChoice>
          <simpleChoice identifier="c">Option C</simpleChoice>
        </choiceInteraction>
      </itemBody>
    </assessmentItem>"""
    return ET.fromstring(xml)


def _shortanswer_item(num_entries=1):
    entries = "<textEntryInteraction responseIdentifier=\"RESPONSE\"/>" * num_entries
    xml = f"""<assessmentItem title="Lueckentext">
      <responseDeclaration identifier="RESPONSE" cardinality="single">
        <correctResponse><value>Musterantwort</value></correctResponse>
      </responseDeclaration>
      <itemBody><p>Das Lösungswort ist {entries}.</p></itemBody>
    </assessmentItem>"""
    return ET.fromstring(xml)


# --- qtype_truefalse ---

def test_truefalse_recognizes_matching_label_pair():
    result = parse_truefalse(_true_false_item("Wahr", "Falsch"), {})
    assert result is not None
    assert result['qtype'] == 'truefalse'
    assert result['correct'] is True  # 'a' (Wahr) ist in correctResponse


def test_truefalse_returns_none_for_non_matching_labels():
    # Zwei Optionen, aber keine erkennbaren Wahr/Falsch-Labels -> Fallback
    # auf generisches Multiple-Choice.
    result = parse_truefalse(_true_false_item("Option 1", "Option 2"), {})
    assert result is None


def test_truefalse_returns_none_for_multiple_cardinality():
    result = parse_truefalse(_true_false_item(cardinality="multiple"), {})
    assert result is None


# --- qtype_multichoice ---

def test_multichoice_recognizes_multiple_cardinality_and_splits_fractions():
    result = parse_multichoice(_multichoice_item(cardinality="multiple", correct=("a", "c")), {})
    assert result['single'] == 'false'
    correct_fractions = {choice['id']: choice['fraction'] for choice in result['choices'] if choice['is_correct']}
    assert correct_fractions['a'] == correct_fractions['c']


def test_multichoice_recognizes_single_cardinality():
    result = parse_multichoice(_multichoice_item(cardinality="single", correct=("a",)), {})
    assert result['single'] == 'true'
    by_id = {choice['id']: choice['fraction'] for choice in result['choices']}
    assert by_id['a'] == "100.0"
    assert by_id['b'] == "0.0"


def test_multichoice_returns_none_without_choice_interaction():
    result = parse_multichoice(_EMPTY_ITEM, {})
    assert result is None


# --- qtype_shortanswer ---

def test_shortanswer_recognizes_single_text_entry():
    result = parse_shortanswer(_shortanswer_item(num_entries=1), {})
    assert result is not None
    assert result['qtype'] == 'shortanswer'
    assert result['answers'] == ['Musterantwort']


def test_shortanswer_returns_none_for_multiple_text_entries():
    # Mehrere Lücken -> gehört zu qtype_cloze.py, nicht shortanswer.
    result = parse_shortanswer(_shortanswer_item(num_entries=2), {})
    assert result is None


def test_shortanswer_returns_none_without_item_body():
    bare = ET.fromstring('<assessmentItem title="x"></assessmentItem>')
    assert parse_shortanswer(bare, {}) is None


# --- Alle übrigen Fragetyp-Parser: müssen auf einem leeren/unpassenden
# assessmentItem sauber None liefern statt zu crashen (Fallback-Kette). ---

def test_all_remaining_parsers_return_none_gracefully_on_empty_item():
    for parser in ALL_PARSERS:
        assert parser(_EMPTY_ITEM, {}) is None, f"{parser.__name__} sollte None liefern, keine Exception"


def test_all_remaining_parsers_return_none_on_completely_unrelated_item():
    # Ein assessmentItem, das eher zu Multiple-Choice passt (choiceInteraction
    # mit 3 Optionen) – keiner der anderen, spezielleren Parser darf das an
    # sich reißen.
    unrelated = _multichoice_item()
    for parser in ALL_PARSERS:
        assert parser(unrelated, {}) is None, f"{parser.__name__} griff fälschlich bei fremdem Fragetyp"
