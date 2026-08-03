"""Fragetyp Hottext (anklickbare Begriffe im Fließtext).

Moodle hat ohne Plugin keinen "Wörter anklicken"-Typ, daher die Abbildung
auf multichoice (kein eigener Generator nötig): der Fließtext bleibt als
Kontext erhalten (hottext-Tags werden zu Inline-Text aufgelöst statt
entfernt, sonst ergäbe der Satz keinen Sinn mehr), und jede anklickbare
Phrase wird zusätzlich als eigene Checkbox-Option extrahiert – taucht
also bewusst zweimal auf, einmal im Text, einmal als Option.
"""

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from .helpers import correct_response_values, element_inner_html, process_html_and_images, calculate_choice_fractions

_HOTTEXT_INTERACTION_TAGS = re.compile(r'</?hottextInteraction[^>]*>')
_HOTTEXT_UNWRAP = re.compile(r'<hottext[^>]*>(.*?)</hottext>', re.DOTALL)


def parse_hottext(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Löst hottext-Tags zu Inline-Text auf und extrahiert jede Phrase zusätzlich
    als Checkbox-Option; gibt qtype='multichoice' zurück (siehe Moduldokstring)."""
    interaction = root.find('.//hottextInteraction')
    if interaction is None:
        return None

    raw_hottexts = interaction.findall('.//hottext')
    if not raw_hottexts:
        return None

    correct_ids = set(correct_response_values(root))

    item_body = root.find('.//itemBody')
    if item_body is None:
        return None

    raw_body_html = element_inner_html(item_body)
    stem_html = _HOTTEXT_INTERACTION_TAGS.sub('', raw_body_html)
    stem_html = _HOTTEXT_UNWRAP.sub(r'\1', stem_html)
    question_text, text_files = process_html_and_images(stem_html, vfs)

    choices: List[Dict] = []
    for ht in raw_hottexts:
        hid = ht.get('identifier', '')
        raw_html = element_inner_html(ht)
        clean_html, choice_files = process_html_and_images(raw_html, vfs)
        choices.append({
            'id': hid,
            'text': clean_html,
            'files': choice_files,
            'is_correct': hid in correct_ids,
        })

    choices, _single = calculate_choice_fractions(choices, single=False)

    return {
        # Kein eigener generate_hottext_xml: Moodle hat keinen Fragetyp für
        # Hottext, die Auswahl im Fließtext wird als Mehrfachauswahl
        # abgebildet und läuft deshalb über generate_multichoice_xml.
        'qtype': 'multichoice',
        'title': root.get('title', 'Unbenannt'),
        'text': question_text,
        'text_files': text_files,
        'choices': choices,
        'single': 'false',
    }
