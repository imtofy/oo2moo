"""Fragetyp Lückentext mit mehreren Lücken (Cloze / Moodle-intern 'multianswer').

Ab 2 textEntryInteraction-Lücken zuständig (1 Lücke → qtype_shortanswer.py).
baseType float/integer wird zur NUMERICAL-Lücke, sonst SHORTANSWER.

Laut echter Moodle-5.0-Referenz braucht die Elternfrage (multianswer) UND
jede Lücke einen EIGENEN question_bank_entry in derselben Kategorie - die
Elternfrage verlinkt die Lücken nur über <multianswer><sequence>. Deshalb
liefert generate_cloze_entries() (anders als die übrigen Generatoren) eine
Liste fertiger question_bank_entry-Blöcke statt eines einzelnen
<question>-Fragments, siehe qti_pipeline.py's MULTI_ENTRY_GENERATORS.
"""

import re
import html as html_lib
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from .helpers import (element_inner_html, process_html_and_images, escape_cloze_text, _TAG_PATTERN,
                      warn_dropped_files, build_question_element, wrap_question_bank_entry,
                      extract_cloze_tokens, replace_cloze_tokens_with_placeholders)


def parse_cloze(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Toleranz bei NUMERICAL-Lücken bleibt immer 0 - OLAT liefert nur einen
    exakten Wert, keinen Toleranzbereich."""
    item_body = root.find('.//itemBody')
    if item_body is None:
        return None

    interactions = root.findall('.//textEntryInteraction')
    if len(interactions) < 2:
        return None

    correct_by_id: Dict[str, List[str]] = {}
    basetype_by_id: Dict[str, str] = {}
    for response_decl in root.findall('.//responseDeclaration'):
        rid = response_decl.get('identifier', '')
        basetype_by_id[rid] = response_decl.get('baseType', 'string')
        values = [v.text.strip() for v in response_decl.findall('.//correctResponse/value')
                  if v.text]
        if values:
            correct_by_id[rid] = values

    blanks = [{'id': inter.get('responseIdentifier', ''),
               'answers': correct_by_id.get(inter.get('responseIdentifier', ''), []),
               'basetype': basetype_by_id.get(inter.get('responseIdentifier', ''), 'string')}
              for inter in interactions]

    raw_body_html = element_inner_html(item_body)
    blank_index = {'i': 0}

    def cloze_replacer(_match):
        """Ersetzt einen Lücken-Platzhalter im HTML durch die Moodle-Cloze-Syntax der entsprechenden Lücke."""
        i = blank_index['i']
        blank_index['i'] += 1
        blank = blanks[i]
        answers = blank['answers'] or ['']
        if blank['basetype'] in ('float', 'integer'):
            value = escape_cloze_text(answers[0])
            return f'{{1:NUMERICAL:={value}:0}}'
        primary = escape_cloze_text(answers[0])
        alt = ''.join(f'~={escape_cloze_text(a)}' for a in answers[1:])
        return f'{{1:SHORTANSWER:={primary}{alt}}}'

    cloze_html = re.sub(_TAG_PATTERN, cloze_replacer, raw_body_html)
    question_text, text_files = process_html_and_images(cloze_html, vfs)

    return {
        'qtype': 'cloze',
        'title': root.get('title', 'Unbenannt'),
        'text': question_text,
        'text_files': text_files,
        'blanks': blanks,
    }


def _build_numerical_subquestion(sub_qid: int, parent_qid: int, title: str, token: str,
                                  blank: Dict, id_gen) -> str:
    """Baut eine numerische Subquestion (<plugin_qtype_numerical_question>) für eine Cloze-Lücke."""
    answer_id = id_gen.next()
    value = blank['answers'][0] if blank['answers'] else '0'
    option_id = id_gen.next()
    record_id = id_gen.next()
    plugin_inner = f"""                  <answers>
                    <answer id="{answer_id}">
                      <answertext>{html_lib.escape(value)}</answertext>
                      <answerformat>0</answerformat>
                      <fraction>1.0000000</fraction>
                      <feedback></feedback>
                      <feedbackformat>1</feedbackformat>
                    </answer>
                  </answers>
                  <numerical_units>
                  </numerical_units>
                  <numerical_options>
                    <numerical_option id="{option_id}">
                      <showunits>3</showunits>
                      <unitsleft>0</unitsleft>
                      <unitgradingtype>0</unitgradingtype>
                      <unitpenalty>1.0000000</unitpenalty>
                    </numerical_option>
                  </numerical_options>
                  <numerical_records>
                    <numerical_record id="{record_id}">
                      <answer>{answer_id}</answer>
                      <tolerance>0</tolerance>
                    </numerical_record>
                  </numerical_records>"""
    return build_question_element(sub_qid, title, token, 'numerical', plugin_inner,
                                   parent=parent_qid, penalty="0.0000000")


def _build_shortanswer_subquestion(sub_qid: int, parent_qid: int, title: str, token: str,
                                    blank: Dict, id_gen) -> str:
    """Baut eine Freitext-Subquestion (<plugin_qtype_shortanswer_question>) für eine Cloze-Lücke."""
    answers = blank['answers'] or ['']
    answer_blocks = []
    for ans in answers:
        aid = id_gen.next()
        answer_blocks.append(f"""                    <answer id="{aid}">
                      <answertext>{html_lib.escape(ans)}</answertext>
                      <answerformat>0</answerformat>
                      <fraction>1.0000000</fraction>
                      <feedback></feedback>
                      <feedbackformat>1</feedbackformat>
                    </answer>""")
    sa_id = id_gen.next()
    plugin_inner = f"""                  <answers>
{chr(10).join(answer_blocks)}
                  </answers>
                  <shortanswer id="{sa_id}">
                    <usecase>0</usecase>
                  </shortanswer>"""
    return build_question_element(sub_qid, title, token, 'shortanswer', plugin_inner,
                                   parent=parent_qid, penalty="0.0000000")


def generate_cloze_entries(q: Dict, id_gen, cat_id: int) -> Tuple[List[str], int]:
    """Gibt (alle question_bank_entry-Blöcke, entry_id der Elternfrage) zurück -
    nur die Elternfrage referenziert quiz.xml direkt als Slot, Subquestions
    hängen nur über <sequence> dran (siehe Moduldokstring)."""
    warn_dropped_files(q)

    tokens = extract_cloze_tokens(q['text'])
    parent_text = replace_cloze_tokens_with_placeholders(q['text'])

    if len(tokens) != len(q['blanks']):
        print(f"[!] '{q['title']}': {len(tokens)} Cloze-Token(s) im Text, aber "
              f"{len(q['blanks'])} Lücke(n) erkannt – nur die ersten "
              f"{min(len(tokens), len(q['blanks']))} werden verknüpft, der Rest "
              f"geht verloren (evtl. literale {{n:TYPE:...}}-Syntax im Fragetext?).")

    parent_qid = id_gen.next()
    sub_ids: List[int] = []
    sub_entries: List[str] = []

    for token, blank in zip(tokens, q['blanks']):
        sub_qid = id_gen.next()
        sub_ids.append(sub_qid)

        if blank['basetype'] in ('float', 'integer'):
            sub_question_xml = _build_numerical_subquestion(
                sub_qid, parent_qid, q['title'], token, blank, id_gen)
        else:
            sub_question_xml = _build_shortanswer_subquestion(
                sub_qid, parent_qid, q['title'], token, blank, id_gen)

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
        parent_qid, q['title'], parent_text, 'multianswer', parent_plugin_inner,
        parent=0, penalty="0.3333333", defaultmark=f"{len(sub_ids)}.0000000")
    parent_entry_xml, parent_entry_id = wrap_question_bank_entry(parent_question_xml, cat_id, id_gen)

    return [parent_entry_xml] + sub_entries, parent_entry_id
