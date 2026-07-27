"""Fragetyp Multiple Choice (Single & Multiple Answer).

Bewertungsanteile werden gleichmäßig auf alle richtigen/falschen Antworten
verteilt (helpers.calculate_choice_fractions) - OLAT exportiert keine
individuellen Gewichtungen, Gleichverteilung ist die korrekte Abbildung.
"""

import html as html_lib
import xml.etree.ElementTree as ET
from typing import Dict, Optional

from .helpers import (element_inner_html, process_html_and_images,
                     calculate_choice_fractions, format_fraction_decimal,
                     build_question_xml, IdGenerator)


def parse_multichoice(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """cardinality der responseDeclaration entscheidet single vs. multiple."""
    interaction = root.find('.//choiceInteraction')
    if interaction is None:
        return None

    correct_ids = set()
    is_single = True

    response_decl = root.find('.//responseDeclaration')
    if response_decl is not None:
        cardinality = response_decl.get('cardinality', 'single')
        is_single = cardinality == 'single'
        for value in response_decl.findall('.//correctResponse/value'):
            if value.text:
                correct_ids.add(value.text.strip())

    text_parts = []
    item_body = root.find('.//itemBody')
    if item_body is not None:
        for elem in item_body:
            if elem.tag != 'choiceInteraction':
                text_parts.append(element_inner_html(elem))

    question_html = '\n'.join(filter(None, text_parts))
    question_text, text_files = process_html_and_images(question_html, vfs)

    choices = []
    for choice in interaction.findall('.//simpleChoice'):
        identifier = choice.get('identifier', '')
        raw_choice_html = element_inner_html(choice)
        clean_choice_html, choice_files = process_html_and_images(raw_choice_html, vfs)

        choices.append({
            'id': identifier,
            'text': clean_choice_html,
            'files': choice_files,
            'is_correct': identifier in correct_ids,
        })

    choices = calculate_choice_fractions(choices, is_single)

    return {
        'qtype': 'multichoice',
        'title': root.get('title', 'Unbenannt'),
        'text': question_text,
        'text_files': text_files,
        'choices': choices,
        'single': 'true' if is_single else 'false',
    }


def generate_multichoice_xml(q: Dict, id_gen: IdGenerator) -> str:
    """Baut den <question>-Block (Backup-Format) für eine Multiple-Choice-Frage."""
    answer_blocks = []
    for choice in q['choices']:
        aid = id_gen.next()
        safe_text = html_lib.escape(choice['text'])
        decimal_fraction = format_fraction_decimal(choice['fraction'])
        answer_blocks.append(f"""                    <answer id="{aid}">
                      <answertext>{safe_text}</answertext>
                      <answerformat>1</answerformat>
                      <fraction>{decimal_fraction}</fraction>
                      <feedback></feedback>
                      <feedbackformat>1</feedbackformat>
                    </answer>""")
    answers_block = '\n'.join(answer_blocks)

    mc_id = id_gen.next()
    single_flag = "1" if q['single'] == 'true' else "0"

    plugin_inner = f"""                  <answers>
{answers_block}
                  </answers>
                  <multichoice id="{mc_id}">
                    <layout>0</layout>
                    <single>{single_flag}</single>
                    <shuffleanswers>1</shuffleanswers>
                    <correctfeedback>&lt;p&gt;Die Antwort ist richtig.&lt;/p&gt;</correctfeedback>
                    <correctfeedbackformat>1</correctfeedbackformat>
                    <partiallycorrectfeedback>&lt;p&gt;Die Antwort ist teilweise richtig.&lt;/p&gt;\
</partiallycorrectfeedback>
                    <partiallycorrectfeedbackformat>1</partiallycorrectfeedbackformat>
                    <incorrectfeedback>&lt;p&gt;Die Antwort ist falsch.&lt;/p&gt;</incorrectfeedback>
                    <incorrectfeedbackformat>1</incorrectfeedbackformat>
                    <answernumbering>abc</answernumbering>
                    <shownumcorrect>1</shownumcorrect>
                    <showstandardinstruction>1</showstandardinstruction>
                  </multichoice>"""

    return build_question_xml(q, id_gen, 'multichoice', plugin_inner, penalty="0.3333333")
