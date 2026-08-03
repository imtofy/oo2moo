"""Fragetyp Zeichnen – nur Erkennung, kein Generator.

Kein generate_drawing_xml(), absichtlich: Standard-Moodle hat kein
Zeichenwerkzeug ohne Drittanbieter-Plugin. Wird darum wie qtype_matrix.py
nur erkannt und dann automatisch übersprungen+geloggt.
"""

import xml.etree.ElementTree as ET
from typing import Dict, Optional


def parse_drawing(root: ET.Element, _vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Erkennt ein drawingInteraction-Item, ohne Generator dahinter."""
    interaction = root.find('.//drawingInteraction')
    if interaction is None:
        return None

    title = root.get('title', 'Unbenannt')
    print(f"[!] Zeichnen-Frage '{title}' erkannt – wir haben aktuell kein "
          f"unterstützendes Modul dafür (Standard-Moodle hat kein natives "
          f"Zeichenwerkzeug, das erfordert ein Drittanbieter-Plugin), wird übersprungen.")

    return {
        'qtype': 'drawing',
        'title': title,
        'text': '',
        'text_files': [],
    }
