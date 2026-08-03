"""Fragetyp Kprim (Vier-Aussagen-Wahr/Falsch-Bewertung).

OLAT exportiert das als <matchInteraction class="match_krpim">, nicht als
choiceInteraction: 4 Aussagen in simpleMatchSet[0], feste Ziele
"correct"/"wrong" in simpleMatchSet[1]. Das <mapping> mit OLATs eigenem
Scoring wird nicht übernommen – Moodle bekommt stattdessen feste
±25%-Fractions pro Option (multichoice, single=0).

Das weicht vom Original ab: OLAT rechnet z.B. 4/4 richtig=100%, jede
Falschmarkierung zieht individuell ab; Moodle kennt nur 4/4=100%,
3/4=75%, 3/4+1 Fehlklick=50%. Ein Fehlklick UND eine übersehene richtige
Aussage ergeben in Moodle also 50% statt des OLAT-spezifischen Werts –
bekannter, unvermeidbarer Informationsverlust ohne Kprim-Plugin.
"""

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from .helpers import (answer_xml, correct_response_pairs, extract_question_text, element_inner_html, process_html_and_images,
                     format_fraction_decimal, build_question_xml, IdGenerator)


def parse_kprim(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Braucht ein matchInteraction mit class="match_krpim" und genau 4 Aussagen."""
    interaction = root.find('.//matchInteraction')
    if interaction is None:
        return None

    if 'match_krpim' not in (interaction.get('class') or ''):
        return None

    match_sets = interaction.findall('.//simpleMatchSet')
    if len(match_sets) != 2:
        return None

    statement_choices = match_sets[0].findall('.//simpleAssociableChoice')
    if len(statement_choices) != 4:
        return None

    truth_by_id: Dict[str, str] = correct_response_pairs(root)

    question_text, text_files = extract_question_text(root, vfs, 'matchInteraction')

    choices: List[Dict] = []
    for sc in statement_choices:
        sid = sc.get('identifier', '')
        raw_html = element_inner_html(sc)
        clean_html, choice_files = process_html_and_images(raw_html, vfs)
        is_correct = truth_by_id.get(sid) == 'correct'

        choices.append({
            'id': sid,
            'text': clean_html,
            'files': choice_files,
            'is_correct': is_correct,
            'fraction': "25.0" if is_correct else "-25.0",
        })

    return {
        'qtype': 'kprim',
        'title': root.get('title', 'Unbenannt'),
        'text': question_text,
        'text_files': text_files,
        'choices': choices,
    }


def generate_kprim_xml(question: Dict, id_gen: IdGenerator) -> str:
    """Baut einen multichoice-Block (Multiple Answer, ±25%-Fractions) für eine Kprim-Frage.

    penalty=0: das ±25%-Fraction-Schema ersetzt die übliche Versuchs-
    Abzugslogik vollständig – ein zusätzlicher penalty-Abzug würde das
    Scoring doppelt bestrafen.
    """
    answer_blocks = []
    for choice in question['choices']:
        aid = id_gen.next()
        decimal_fraction = format_fraction_decimal(choice['fraction'])
        answer_blocks.append(answer_xml(aid, choice['text'], decimal_fraction))
    answers_block = '\n'.join(answer_blocks)

    mc_id = id_gen.next()

    plugin_inner = f"""                  <answers>
{answers_block}
                  </answers>
                  <multichoice id="{mc_id}">
                    <layout>0</layout>
                    <single>0</single>
                    <shuffleanswers>1</shuffleanswers>
                    <correctfeedback>&lt;p&gt;Die Antwort ist richtig.&lt;/p&gt;</correctfeedback>
                    <correctfeedbackformat>1</correctfeedbackformat>
                    <partiallycorrectfeedback>&lt;p&gt;Die Antwort ist teilweise richtig \
(Kprim: &amp;plusmn;25&amp;nbsp;% pro Aussage).&lt;/p&gt;</partiallycorrectfeedback>
                    <partiallycorrectfeedbackformat>1</partiallycorrectfeedbackformat>
                    <incorrectfeedback>&lt;p&gt;Die Antwort ist falsch.&lt;/p&gt;</incorrectfeedback>
                    <incorrectfeedbackformat>1</incorrectfeedbackformat>
                    <answernumbering>abc</answernumbering>
                    <shownumcorrect>1</shownumcorrect>
                    <showstandardinstruction>1</showstandardinstruction>
                  </multichoice>"""

    return build_question_xml(question, id_gen, 'multichoice', plugin_inner, penalty="0.0000000")
