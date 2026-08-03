"""Fragetyp Zuordnung.

Nur 2-spaltige matchInteraction (mehr Spalten werden übersprungen).
Moodles interner Fragetyp heißt 'match', nicht 'matching' – unser Dict
führt intern weiter qtype='matching', nur build_question_xml bekommt
qtype_name='match'.
"""

import xml.etree.ElementTree as ET
from typing import Dict, Optional

from .helpers import (build_match_question_xml, correct_response_pairs, extract_question_text,
                      element_inner_html, process_html_and_images, strip_tags, IdGenerator)


def parse_matching(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Ziel-Optionen ohne Paar (Distraktoren) werden als Antwortoption ohne
    Frage mit aufgenommen – sonst sähen Studierende in Moodle nur die
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

    pairs = correct_response_pairs(root)

    question_text, text_files = extract_question_text(root, vfs, 'matchInteraction')

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


def generate_matching_xml(question: Dict, id_gen: IdGenerator) -> str:
    """Erzeugt den <question>-Block (Backup-Format) für eine Zuordnungs-Frage."""
    return build_match_question_xml(question, id_gen)
