"""Fragetyp Sortieraufgabe.

Moodle hat keinen nativen Sortier-Typ – jedes Element wird stattdessen
mit seiner Zielposition ("Position 1", ...) als Zuordnungsfrage gepaart.
Dadurch prüft Moodle jede Zuordnung einzeln statt der Reihenfolge als
Ganzes, Teilpunkte sind möglich, wo OLAT strenger werten würde – gleiche
Abweichung wie bei qtype_matching.py.
"""

import xml.etree.ElementTree as ET
from typing import Dict, Optional, Tuple

from .helpers import (build_match_question_xml, extract_question_text, element_inner_html,
                      process_html_and_images, IdGenerator)


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
            value_elem.text.strip()
            for value_elem in response_decl.findall('.//correctResponse/value')
            if value_elem.text
        ]

    if not correct_order:
        correct_order = [choice.get('identifier', '') for choice in raw_choices]

    question_text, text_files = extract_question_text(root, vfs, 'orderInteraction')

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


def generate_order_xml(question: Dict, id_gen: IdGenerator) -> str:
    """Baut einen match-Block (Backup-Format) für eine Sortieraufgabe (Element → Position N).

    NICHT deckungsgleich mit generate_matching_xml(): die Rückmeldungen
    benennen hier die Reihenfolge, dort die Antwort. Der Unterschied steckt
    allein in feedback_subject und ist im erzeugten XML nur an drei Stellen
    sichtbar – beim Zusammenfassen beider Aufrufe fällt er leicht weg."""
    return build_match_question_xml(question, id_gen, feedback_subject="Die Reihenfolge")
