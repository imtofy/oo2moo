"""Fragetyp Lückentext mit Dropdown (Inline-Choice).

Verwandt mit qtype_cloze.py (beides zielt auf Moodles 'multianswer'),
aber mit Dropdown-Optionen statt Freitext-Lücken → {n:MULTICHOICE:...}
statt {n:SHORTANSWER:...}. Bewusst ein eigenes Modul (ein Tag, ein
Modul) statt in qtype_cloze.py integriert. Struktur wie dort (Eltern-
Entry + ein question_bank_entry je Lücke), Optionstexte werden über
Moodles Cloze-Maskierung escaped (helpers.escape_cloze_text), nicht
per HTML-Escaping.
"""

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from .helpers import (answer_xml, element_inner_html, process_html_and_images, strip_tags, escape_cloze_text,
                      warn_dropped_files, build_question_element, wrap_question_bank_entry,
                      extract_cloze_tokens, replace_cloze_tokens_with_placeholders)

_INLINECHOICE_PATTERN = re.compile(
    r'<inlineChoiceInteraction[^>]*>.*?</inlineChoiceInteraction>',
    re.DOTALL
)


def parse_inlinechoice(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Ersetzt jede Lücke durch ihr Cloze-Token {1:MULTICHOICE:opt1~=opt2~...}
    (führendes '=' markiert die korrekte Option)."""
    item_body = root.find('.//itemBody')
    if item_body is None:
        return None

    interactions = root.findall('.//inlineChoiceInteraction')
    if not interactions:
        return None

    blanks: List[Dict] = []
    for inter in interactions:
        rid = inter.get('responseIdentifier', '')

        options = []
        for ic in inter.findall('.//inlineChoice'):
            cid = ic.get('identifier', '')
            option_text = strip_tags(element_inner_html(ic))
            options.append({'id': cid, 'text': option_text})

        correct_id = None
        for response_decl in root.findall('.//responseDeclaration'):
            if response_decl.get('identifier', '') == rid:
                value_el = response_decl.find('.//correctResponse/value')
                if value_el is not None and value_el.text:
                    correct_id = value_el.text.strip()
                break

        blanks.append({'id': rid, 'options': options, 'correct_id': correct_id})

    raw_body_html = element_inner_html(item_body)
    blank_index = {'i': 0}

    def _replace_blank_with_token(_match):
        """Ersetzt eine inlineChoice-Lücke durch ihr MULTICHOICE-Cloze-Token."""
        i = blank_index['i']
        blank_index['i'] += 1
        blank = blanks[i]

        parts = []
        for opt in blank['options']:
            escaped = escape_cloze_text(opt['text'])
            prefix = '=' if opt['id'] == blank['correct_id'] else ''
            parts.append(f"{prefix}{escaped}")

        joined = '~'.join(parts)
        return f'{{1:MULTICHOICE:{joined}}}'

    cloze_html = _INLINECHOICE_PATTERN.sub(_replace_blank_with_token, raw_body_html)
    question_text, text_files = process_html_and_images(cloze_html, vfs)

    return {
        # 'cloze_dropdown' steht nicht in GENERATORS, sondern in
        # MULTI_ENTRY_GENERATORS (qti_pipeline.py) – eine Dropdown-Luecke
        # erzeugt wie Cloze mehrere question_bank_entries auf einmal.
        'qtype': 'cloze_dropdown',
        'title': root.get('title', 'Unbenannt'),
        'text': question_text,
        'text_files': text_files,
        'blanks': blanks,
    }


def _build_multichoice_subquestion(sub_qid: int, parent_qid: int, title: str, token: str,
                                    blank: Dict, id_gen) -> str:
    """Baut eine Dropdown-Subquestion (<plugin_qtype_multichoice_question>) für eine Lücke."""
    answer_blocks = []
    for opt in blank['options']:
        aid = id_gen.next()
        fraction = "1.0000000" if opt['id'] == blank['correct_id'] else "0.0000000"
        answer_blocks.append(answer_xml(aid, opt['text'], fraction))
    mc_id = id_gen.next()
    plugin_inner = f"""                  <answers>
{chr(10).join(answer_blocks)}
                  </answers>
                  <multichoice id="{mc_id}">
                    <layout>0</layout>
                    <single>1</single>
                    <shuffleanswers>0</shuffleanswers>
                    <correctfeedback></correctfeedback>
                    <correctfeedbackformat>1</correctfeedbackformat>
                    <partiallycorrectfeedback></partiallycorrectfeedback>
                    <partiallycorrectfeedbackformat>1</partiallycorrectfeedbackformat>
                    <incorrectfeedback></incorrectfeedback>
                    <incorrectfeedbackformat>1</incorrectfeedbackformat>
                    <answernumbering>0</answernumbering>
                    <shownumcorrect>0</shownumcorrect>
                    <showstandardinstruction>0</showstandardinstruction>
                  </multichoice>"""
    return build_question_element(sub_qid, title, token, 'multichoice', plugin_inner,
                                   parent=parent_qid, penalty="0.0000000")


def generate_inlinechoice_entries(question: Dict, id_gen, cat_id: int) -> Tuple[List[str], int]:
    """Analog zu qtype_cloze.generate_cloze_entries, aber jede Lücke ist ein
    MULTICHOICE-Dropdown statt SHORTANSWER/NUMERICAL. Gibt (alle
    question_bank_entry-Blöcke, entry_id der Elternfrage) zurück."""
    warn_dropped_files(question)

    tokens = extract_cloze_tokens(question['text'])
    parent_text = replace_cloze_tokens_with_placeholders(question['text'])

    if len(tokens) != len(question['blanks']):
        print(f"[!] '{question['title']}': {len(tokens)} Cloze-Token(s) im Text, aber "
              f"{len(question['blanks'])} Lücke(n) erkannt – nur die ersten "
              f"{min(len(tokens), len(question['blanks']))} werden verknüpft, der Rest "
              f"geht verloren (evtl. literale {{n:TYPE:...}}-Syntax im Fragetext?).")

    parent_qid = id_gen.next()
    sub_ids: List[int] = []
    sub_entries: List[str] = []

    for token, blank in zip(tokens, question['blanks']):
        sub_qid = id_gen.next()
        sub_ids.append(sub_qid)
        sub_question_xml = _build_multichoice_subquestion(
            sub_qid, parent_qid, question['title'], token, blank, id_gen)
        sub_entry_xml, _sub_entry_id = wrap_question_bank_entry(sub_question_xml, cat_id, id_gen)
        sub_entries.append(sub_entry_xml)

    sequence = ','.join(str(i) for i in sub_ids)
    ma_id = id_gen.next()
    parent_plugin_inner = f"""                  <answers>
                  </answers>
                  <multianswer id="{ma_id}">
                    <question>{parent_qid}</question>
                    <sequence>{sequence}</sequence>
                  </multianswer>"""
    parent_question_xml = build_question_element(
        parent_qid, question['title'], parent_text, 'multianswer', parent_plugin_inner,
        parent=0, penalty="0.3333333", defaultmark=f"{len(sub_ids)}.0000000")
    parent_entry_xml, parent_entry_id = wrap_question_bank_entry(parent_question_xml, cat_id, id_gen)

    return [parent_entry_xml] + sub_entries, parent_entry_id
