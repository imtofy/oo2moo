"""Fragetyp Kurzantwort / Einzel-Lücke.

Nur bei GENAU einer textEntryInteraction zuständig – mehrere Lücken
gehen an qtype_cloze.py.
"""

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from .helpers import answer_xml, element_inner_html, process_html_and_images, build_question_xml, IdGenerator, _TAG_PATTERN


def parse_shortanswer(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Ersetzt die Lücke im Fragetext durch "_____", damit der Text auch ohne
    interaktives Eingabefeld verständlich bleibt."""
    item_body = root.find('.//itemBody')
    if item_body is None:
        return None

    interactions = root.findall('.//textEntryInteraction')
    if len(interactions) != 1:
        return None

    rid = interactions[0].get('responseIdentifier', '')
    answers: List[str] = []
    for response_decl in root.findall('.//responseDeclaration'):
        if response_decl.get('identifier', '') == rid:
            answers = [value_elem.text.strip() for value_elem in response_decl.findall('.//correctResponse/value')
                       if value_elem.text]
            break

    raw_body_html = element_inner_html(item_body)
    cleaned_html = re.sub(_TAG_PATTERN, '_____', raw_body_html)
    question_text, text_files = process_html_and_images(cleaned_html, vfs)

    return {
        'qtype': 'shortanswer',
        'title': root.get('title', 'Unbenannt'),
        'text': question_text,
        'text_files': text_files,
        'answers': answers if answers else [''],
    }


def generate_shortanswer_xml(question: Dict, id_gen: IdGenerator) -> str:
    """Baut den <question>-Block (Backup-Format) für eine Kurzantwort-Frage."""
    answer_blocks = []
    answers = question['answers'] or ['']
    for ans in answers:
        aid = id_gen.next()
        answer_blocks.append(answer_xml(aid, ans, "1.0000000", answerformat=0))
    answers_block = '\n'.join(answer_blocks)

    sa_id = id_gen.next()

    plugin_inner = f"""                  <answers>
{answers_block}
                  </answers>
                  <shortanswer id="{sa_id}">
                    <usecase>0</usecase>
                  </shortanswer>"""

    return build_question_xml(question, id_gen, 'shortanswer', plugin_inner, penalty="0.3333333")
