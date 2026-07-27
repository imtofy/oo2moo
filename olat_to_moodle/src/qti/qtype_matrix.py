"""Fragetyp Matrix (n:m-Relation) - nur Erkennung, bewusst kein Generator.

<matchInteraction class="match_matrix"> erlaubt echte n:m-Zuordnungen
(eine Quelle darf mit mehreren Zielen korrekt gepaart sein), nicht nur
1:1 wie normales matching. Moodle hat ohne Plugin keinen n:m-Fragetyp,
und jede Notlösung würde das Scoring gegenüber dem Original verändern -
deshalb nur Erkennung + Skip+Log statt einer stillen Annahme im Parser,
kein Generator.

Muss in der Parser-Kette VOR parse_matching() stehen, sonst stutzt
parse_matching die n:m-Paare unbemerkt auf 1:1 zusammen.
"""

import xml.etree.ElementTree as ET
from typing import Dict, Optional


def parse_matrix(root: ET.Element, _vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Erkennt ein matchInteraction-Item mit class="match_matrix", ohne Generator dahinter."""
    interaction = root.find('.//matchInteraction')
    if interaction is None:
        return None

    if 'match_matrix' not in (interaction.get('class') or ''):
        return None

    title = root.get('title', 'Unbenannt')
    print(f"[!] Matrix-Frage '{title}' erkannt (n:m-Relation) – Moodle bietet ohne "
          f"Zusatz-Plugin keinen passenden Fragetyp dafür, wird übersprungen. "
          f"Bitte manuell nachbauen.")

    return {
        'qtype': 'matrix',
        'title': title,
        'text': '',
        'text_files': [],
    }
