"""Fragetyp Wahr/Falsch.

QTI kennt kein eigenes True/False-Tag, OLAT exportiert es als normale
2-Optionen-choiceInteraction – wir erkennen das Muster heuristisch über
die Antworttexte (TRUE_LABELS/FALSE_LABELS in config.py). Passt das
Muster nicht, gibt der Parser None zurück und qtype_multichoice.py
übernimmt automatisch.
"""

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from .helpers import element_inner_html, process_html_and_images, strip_tags, build_question_xml, IdGenerator
from config import TRUE_LABELS, FALSE_LABELS


def _looks_like_true_false(choices: List[Dict]) -> Optional[bool]:
    """Prüft die Texte gegen TRUE_LABELS/FALSE_LABELS unabhängig von der
    Reihenfolge im XML – was richtig ist, entscheidet die correctResponse,
    nicht die Position. None bei unklarem Muster oder uneindeutiger
    correctResponse (Fallback auf generisches Multiple-Choice)."""
    if len(choices) != 2:
        return None

    # Ab hier ist len(choices) == 2 garantiert (Abbruch oben), der
    # Indexzugriff unten braucht deshalb keine weitere Prüfung.
    texts = [strip_tags(choice['text']).strip().lower().rstrip('.') for choice in choices]

    if texts[0] in TRUE_LABELS and texts[1] in FALSE_LABELS:
        true_choice, false_choice = choices[0], choices[1]
    elif texts[1] in TRUE_LABELS and texts[0] in FALSE_LABELS:
        true_choice, false_choice = choices[1], choices[0]
    else:
        return None

    if true_choice['is_correct'] == false_choice['is_correct']:
        return None

    return true_choice['is_correct']


def parse_truefalse(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """None (Fallback auf qtype_multichoice), wenn kein eindeutiges Wahr/Falsch-Muster erkannt wird."""
    interaction = root.find('.//choiceInteraction')
    if interaction is None:
        return None

    response_decl = root.find('.//responseDeclaration')
    if response_decl is not None and response_decl.get('cardinality', 'single') != 'single':
        return None

    correct_ids = set()
    if response_decl is not None:
        for value in response_decl.findall('.//correctResponse/value'):
            if value.text:
                correct_ids.add(value.text.strip())

    choices = []
    for choice in interaction.findall('.//simpleChoice'):
        identifier = choice.get('identifier', '')
        raw_choice_html = element_inner_html(choice)
        clean_choice_html, _ = process_html_and_images(raw_choice_html, vfs)
        choices.append({
            'id': identifier,
            'text': clean_choice_html,
            'is_correct': identifier in correct_ids,
        })

    tf_result = _looks_like_true_false(choices)
    if tf_result is None:
        return None

    text_parts = []
    item_body = root.find('.//itemBody')
    if item_body is not None:
        for elem in item_body:
            if elem.tag != 'choiceInteraction':
                text_parts.append(element_inner_html(elem))

    question_html = '\n'.join(filter(None, text_parts))
    question_text, text_files = process_html_and_images(question_html, vfs)

    return {
        'qtype': 'truefalse',
        'title': root.get('title', 'Unbenannt'),
        'text': question_text,
        'text_files': text_files,
        'correct': tf_result,
    }


def generate_truefalse_xml(question: Dict, id_gen: IdGenerator) -> str:
    """Baut den <question>-Block (Backup-Format) für eine Wahr/Falsch-Frage."""
    wahr_id = id_gen.next()
    falsch_id = id_gen.next()
    tf_id = id_gen.next()

    wahr_fraction = "1.0000000" if question['correct'] else "0.0000000"
    falsch_fraction = "0.0000000" if question['correct'] else "1.0000000"

    plugin_inner = f"""                  <answers>
                    <answer id="{wahr_id}">
                      <answertext>Wahr</answertext>
                      <answerformat>0</answerformat>
                      <fraction>{wahr_fraction}</fraction>
                      <feedback></feedback>
                      <feedbackformat>1</feedbackformat>
                    </answer>
                    <answer id="{falsch_id}">
                      <answertext>Falsch</answertext>
                      <answerformat>0</answerformat>
                      <fraction>{falsch_fraction}</fraction>
                      <feedback></feedback>
                      <feedbackformat>1</feedbackformat>
                    </answer>
                  </answers>
                  <truefalse id="{tf_id}">
                    <trueanswer>{wahr_id}</trueanswer>
                    <falseanswer>{falsch_id}</falseanswer>
                    <showstandardinstruction>0</showstandardinstruction>
                  </truefalse>"""

    return build_question_xml(question, id_gen, 'truefalse', plugin_inner, penalty="1.0000000")
