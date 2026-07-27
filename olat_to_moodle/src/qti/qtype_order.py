"""Fragetyp Sortieraufgabe.

Moodle hat keinen nativen Sortier-Typ - jedes Element wird stattdessen
mit seiner Zielposition ("Position 1", ...) als Zuordnungsfrage gepaart.
Dadurch prüft Moodle jede Zuordnung einzeln statt der Reihenfolge als
Ganzes, Teilpunkte sind möglich, wo OLAT strenger werten würde - gleiche
Abweichung wie bei qtype_matching.py.
"""

import html as html_lib
import xml.etree.ElementTree as ET
from typing import Dict, Optional, Tuple

from .helpers import element_inner_html, process_html_and_images, build_question_xml, IdGenerator


def parse_order(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Ohne responseDeclaration gilt die Dokumentreihenfolge als "korrekt"."""
    interaction = root.find('.//orderInteraction')
    if interaction is None:
        return None

    raw_choices = interaction.findall('.//simpleChoice')
    if not raw_choices:
        return None

    choice_lookup: Dict[str, Tuple[str, list]] = {}
    for choice in raw_choices:
        cid = choice.get('identifier', '')
        raw_html = element_inner_html(choice)
        clean_html, files = process_html_and_images(raw_html, vfs)
        choice_lookup[cid] = (clean_html, files)

    correct_order = []
    response_decl = root.find('.//responseDeclaration')
    if response_decl is not None:
        correct_order = [
            v.text.strip()
            for v in response_decl.findall('.//correctResponse/value')
            if v.text
        ]

    if not correct_order:
        correct_order = [c.get('identifier', '') for c in raw_choices]

    text_parts = []
    item_body = root.find('.//itemBody')
    if item_body is not None:
        for elem in item_body:
            if elem.tag != 'orderInteraction':
                text_parts.append(element_inner_html(elem))

    question_html = '\n'.join(filter(None, text_parts))
    question_text, text_files = process_html_and_images(question_html, vfs)

    subquestions = []
    for pos, cid in enumerate(correct_order, start=1):
        entry = choice_lookup.get(cid)
        if entry and entry[0]:
            subquestions.append({
                'text': entry[0],
                'files': entry[1],
                'answer': f'Position {pos}',
            })

    if not subquestions:
        return None

    return {
        'qtype': 'order',
        'title': root.get('title', 'Unbenannt'),
        'text': question_text,
        'text_files': text_files,
        'subquestions': subquestions,
    }


def generate_order_xml(q: Dict, id_gen: IdGenerator) -> str:
    """Baut einen match-Block (Backup-Format) für eine Sortieraufgabe (Element → Position N)."""
    mo_id = id_gen.next()

    match_blocks = []
    for sub in q['subquestions']:
        match_id = id_gen.next()
        safe_text = html_lib.escape(sub['text'])
        safe_answer = html_lib.escape(sub['answer'])
        match_blocks.append(f"""                    <match id="{match_id}">
                      <questiontext>{safe_text}</questiontext>
                      <questiontextformat>1</questiontextformat>
                      <answertext>{safe_answer}</answertext>
                    </match>""")
    matches_block = '\n'.join(match_blocks)

    plugin_inner = f"""                  <matchoptions id="{mo_id}">
                    <shuffleanswers>1</shuffleanswers>
                    <correctfeedback>&lt;p&gt;Die Reihenfolge ist richtig.&lt;/p&gt;</correctfeedback>
                    <correctfeedbackformat>1</correctfeedbackformat>
                    <partiallycorrectfeedback>&lt;p&gt;Die Reihenfolge ist teilweise richtig.&lt;/p&gt;\
</partiallycorrectfeedback>
                    <partiallycorrectfeedbackformat>1</partiallycorrectfeedbackformat>
                    <incorrectfeedback>&lt;p&gt;Die Reihenfolge ist falsch.&lt;/p&gt;</incorrectfeedback>
                    <incorrectfeedbackformat>1</incorrectfeedbackformat>
                    <shownumcorrect>1</shownumcorrect>
                  </matchoptions>
                  <matches>
{matches_block}
                  </matches>"""

    return build_question_xml(q, id_gen, 'match', plugin_inner, penalty="0.3333333")
