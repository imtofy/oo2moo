"""Fragetyp Zuordnung.

Nur 2-spaltige matchInteraction (mehr Spalten werden übersprungen).
Moodles interner Fragetyp heißt 'match', nicht 'matching' - unser Dict
führt intern weiter qtype='matching', nur build_question_xml bekommt
qtype_name='match'.
"""

import html as html_lib
import xml.etree.ElementTree as ET
from typing import Dict, Optional

from .helpers import element_inner_html, process_html_and_images, strip_tags, build_question_xml, IdGenerator


def parse_matching(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Ziel-Optionen ohne Paar (Distraktoren) werden als Antwortoption ohne
    Frage mit aufgenommen - sonst sähen Studierende in Moodle nur die
    richtigen Antworten und die Frage wäre leichter als im Original."""
    interaction = root.find('.//matchInteraction')
    if interaction is None:
        return None

    match_sets = interaction.findall('.//simpleMatchSet')
    if len(match_sets) != 2:
        return None

    source_choices = match_sets[0].findall('.//simpleAssociableChoice')
    target_choices = match_sets[1].findall('.//simpleAssociableChoice')

    target_lookup: Dict[str, str] = {}
    for tc in target_choices:
        tid = tc.get('identifier', '')
        raw_html = element_inner_html(tc)
        clean_html, _ = process_html_and_images(raw_html, vfs)
        target_lookup[tid] = strip_tags(clean_html)

    pairs = {}
    response_decl = root.find('.//responseDeclaration')
    if response_decl is not None:
        for value in response_decl.findall('.//correctResponse/value'):
            if value.text and ' ' in value.text.strip():
                src_id, tgt_id = value.text.strip().split(' ', 1)
                pairs[src_id] = tgt_id

    text_parts = []
    item_body = root.find('.//itemBody')
    if item_body is not None:
        for elem in item_body:
            if elem.tag != 'matchInteraction':
                text_parts.append(element_inner_html(elem))

    question_html = '\n'.join(filter(None, text_parts))
    question_text, text_files = process_html_and_images(question_html, vfs)

    subquestions = []
    for sc in source_choices:
        sid = sc.get('identifier', '')
        raw_html = element_inner_html(sc)
        clean_html, sc_files = process_html_and_images(raw_html, vfs)

        matched_target_id = pairs.get(sid)
        matched_text = target_lookup.get(matched_target_id, '')

        if not matched_text:
            continue

        subquestions.append({
            'text': clean_html,
            'files': sc_files,
            'answer': matched_text,
        })

    if not subquestions:
        return None

    used_target_ids = set(pairs.values())
    for tc in target_choices:
        tid = tc.get('identifier', '')
        if tid in used_target_ids:
            continue
        distractor_text = target_lookup.get(tid, '')
        if distractor_text:
            subquestions.append({
                'text': '',
                'files': [],
                'answer': distractor_text,
            })

    return {
        'qtype': 'matching',
        'title': root.get('title', 'Unbenannt'),
        'text': question_text,
        'text_files': text_files,
        'subquestions': subquestions,
    }


def generate_matching_xml(q: Dict, id_gen: IdGenerator) -> str:
    """Erzeugt den <question>-Block (Backup-Format) für eine Zuordnungs-Frage."""
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
                    <correctfeedback>&lt;p&gt;Die Antwort ist richtig.&lt;/p&gt;</correctfeedback>
                    <correctfeedbackformat>1</correctfeedbackformat>
                    <partiallycorrectfeedback>&lt;p&gt;Die Antwort ist teilweise richtig.&lt;/p&gt;\
</partiallycorrectfeedback>
                    <partiallycorrectfeedbackformat>1</partiallycorrectfeedbackformat>
                    <incorrectfeedback>&lt;p&gt;Die Antwort ist falsch.&lt;/p&gt;</incorrectfeedback>
                    <incorrectfeedbackformat>1</incorrectfeedbackformat>
                    <shownumcorrect>1</shownumcorrect>
                  </matchoptions>
                  <matches>
{matches_block}
                  </matches>"""

    return build_question_xml(q, id_gen, 'match', plugin_inner, penalty="0.3333333")
