"""Fragetyp Hotspot (Bildmarkierung) → Moodles ddmarker ('Drag & Drop Markierung').

Nur KORREKTE hotspotChoice-Bereiche werden übernommen: ddmarker kennt
keine Distraktor-Zonen (jede Drop-Zone muss bedient werden können), also
werden falsche Bereiche verworfen (mit Log) statt den Test unlösbar zu
machen.

Koordinaten-Mapping (QTI kommagetrennt → Moodle ddmarker semikolon-Punkte):
    circle: "x,y,r"          → "x,y;r"
    rect:   "x1,y1,x2,y2"    → "x1,y1;x2,y2"   (Shape: "rectangle")
    poly:   "x1,y1,x2,y2,.." → "x1,y1;x2,y2;.." (Shape: "polygon")

QTI liefert keine Textbezeichnung pro Bereich, nur Koordinaten – drags
bekommen daher generische Labels ("Bereich N"), ggf. beim Merge von Hand
nachbessern. Das Hintergrundbild wird automatisch via
qti_pipeline._embed_question_images in die files.xml eingebettet
(component=qtype_ddmarker, filearea=bgimage) – fehlt es im Archiv, bleibt
die Frage bildlos (mit Warnung).
"""

import os
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from config import (HOTSPOT_MIN_RADIUS, HOTSPOT_REGIONS_LOST_MARKER,
                    HOTSPOT_REGIONS_LOST_WARNING, QUESTION_FEEDBACK_CORRECT,
                    QUESTION_FEEDBACK_PARTIAL, QUESTION_FEEDBACK_INCORRECT)
from .helpers import correct_response_values, element_inner_html, process_html_and_images, build_question_xml

_SHAPE_MAP = {'circle': 'circle', 'rect': 'rectangle', 'poly': 'polygon'}


def parse_hotspot(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Das Hintergrundbild steht als QTI <object data="..."/>, nicht als
    <img src="...">, daher eigene VFS-Suche per Dateiname statt process_html_and_images."""
    item_body = root.find('.//itemBody')
    if item_body is None:
        return None

    interaction = item_body.find('.//hotspotInteraction')
    if interaction is None:
        return None

    hotspot_choices = interaction.findall('.//hotspotChoice')
    if not hotspot_choices:
        return None

    correct_ids = set(correct_response_values(root))

    image_filename = ''
    image_data = None
    obj = interaction.find('.//object')
    if obj is not None:
        image_filename = obj.get('data', '')
        if image_filename:
            basename = os.path.basename(image_filename)
            for path, data in vfs.items():
                if os.path.basename(path) == basename:
                    image_data = data
                    break

    regions: List[Dict] = []
    for hc in hotspot_choices:
        regions.append({
            'id': hc.get('identifier', ''),
            'shape': hc.get('shape', ''),
            'coords': hc.get('coords', ''),
            'is_correct': hc.get('identifier', '') in correct_ids,
        })

    text_parts = []
    for elem in item_body:
        if elem.tag != 'hotspotInteraction':
            text_parts.append(element_inner_html(elem))
    question_html = '\n'.join(filter(None, text_parts))
    question_text, text_files = process_html_and_images(question_html, vfs)

    title = root.get('title', 'Unbenannt')
    print(f"[*] Hotspot-Frage '{title}' erkannt (Bildmarkierung, "
          f"{len(regions)} Bereiche, Bild='{image_filename}') – wird als "
          f"Drag & Drop Markierung konvertiert.")

    return {
        'qtype': 'hotspot',
        'title': title,
        'text': question_text,
        'text_files': text_files,
        'image_filename': image_filename,
        'image_data': image_data,
        'regions': regions,
    }


def _usable_radius(qti_radius: str) -> str:
    """Hebt einen zu kleinen Kreisradius auf HOTSPOT_MIN_RADIUS an.

    In OLAT wird ein Bereich angeklickt, dafür genügen wenige Pixel. In
    Moodle wird die Markierung frei auf dem Bild abgelegt – derselbe Radius
    ist dann kaum zu treffen und eine richtig gemeinte Antwort zählt als
    falsch. Größere Bereiche bleiben unverändert: ein fester Faktor würde
    einen ohnehin großzügigen Bereich über das Bild hinaus aufblähen.

    Nicht-numerische Angaben bleiben unangetastet – lieber der
    Originalwert als eine erfundene Zahl."""
    try:
        radius = int(float(qti_radius))
    except (TypeError, ValueError):
        return qti_radius
    return str(max(radius, HOTSPOT_MIN_RADIUS))


def _convert_coords(shape: str, qti_coords: str) -> str:
    """Wandelt QTI-Hotspot-Koordinaten (kommagetrennt) in Moodle-ddmarker-
    Koordinaten (semikolongetrennte Punkte) um – siehe Modul-Docstring."""
    parts = [part.strip() for part in qti_coords.split(',')]
    if shape == 'circle':
        center_x, center_y, radius = parts[0], parts[1], parts[2]
        return f"{center_x},{center_y};{_usable_radius(radius)}"
    points = [f"{parts[i]},{parts[i + 1]}" for i in range(0, len(parts) - 1, 2)]
    return ';'.join(points)


def generate_hotspot_xml(question: Dict, id_gen) -> str:
    """Nur die korrekt markierten Bereiche werden zu Drag/Drop-Paaren (siehe Moduldokstring)."""
    correct_regions = [region for region in question['regions'] if region['is_correct']]
    dropped = len(question['regions']) - len(correct_regions)
    # Für alle Meldungen der Originaltitel: die Markierung unten ist für den
    # Kurs gedacht, im Protokoll soll der Baustein unter dem Namen auftauchen,
    # den er in OLAT trägt.
    title = question['title']
    if dropped:
        print(f"[*] '{title}': {dropped} nicht-korrekte(r) Hotspot-Bereich(e) "
              f"verworfen (Drag & Drop Markierungen kennen keine Distraktor-Zonen).")
        # Verlust auch nach dem Import sichtbar halten – im Kurs selbst, nicht
        # nur im Protokoll dieses Laufs (siehe config.HOTSPOT_REGIONS_LOST_*).
        # Am ursprünglichen Dict, nicht an der Kopie darunter: der Aufrufer
        # (qti_quiz_builder) liest ihn dort aus und setzt ihn in die
        # Test-Beschreibung.
        question['activity_notice'] = HOTSPOT_REGIONS_LOST_WARNING.format(
            dropped=dropped, min_radius=HOTSPOT_MIN_RADIUS)
        question = dict(question)
        question['title'] = (f"{HOTSPOT_REGIONS_LOST_MARKER} {question['title']} "
                             f"{HOTSPOT_REGIONS_LOST_MARKER}")
        # Der Hinweis gehört NICHT in den Fragetext: Moodle zeigt in der
        # Fragenliste Name und Textanfang nebeneinander, dort stünde die
        # Warnung dann mitten in der Übersicht. Er wandert stattdessen in die
        # Beschreibung des Tests, die qti_quiz_builder aus 'activity_notice'
        # zusammensetzt. Der Fragename behält die Markierung.

    if question.get('image_data') is None:
        print(f"[!] '{title}': Hintergrundbild '{question.get('image_filename')}' "
              f"nicht im Archiv gefunden – die Frage ist ohne Bild in Moodle unbrauchbar.")
    else:
        print(f"[*] '{title}': Hintergrundbild '{question['image_filename']}' wird "
              f"automatisch mit eingebettet.")

    drag_blocks = []
    drop_blocks = []
    for idx, region in enumerate(correct_regions, start=1):
        drag_id = id_gen.next()
        drag_blocks.append(f"""                    <drag id="{drag_id}">
                      <no>{idx}</no>
                      <infinite>0</infinite>
                      <label>Bereich {idx}</label>
                      <noofdrags>1</noofdrags>
                    </drag>""")

        drop_id = id_gen.next()
        shape = _SHAPE_MAP.get(region['shape'], region['shape'])
        coords = _convert_coords(shape, region['coords'])
        drop_blocks.append(f"""                    <drop id="{drop_id}">
                      <no>{idx}</no>
                      <shape>{shape}</shape>
                      <coords>{coords}</coords>
                      <choice>{idx}</choice>
                    </drop>""")

    dd_id = id_gen.next()
    plugin_inner = f"""                  <ddmarker id="{dd_id}">
                    <shuffleanswers>1</shuffleanswers>
                    <correctfeedback>&lt;p&gt;{QUESTION_FEEDBACK_CORRECT.format(subject='Die Antwort')}&lt;/p&gt;</correctfeedback>
                    <correctfeedbackformat>1</correctfeedbackformat>
                    <partiallycorrectfeedback>&lt;p&gt;{QUESTION_FEEDBACK_PARTIAL.format(subject='Die Antwort')}&lt;/p&gt;\
</partiallycorrectfeedback>
                    <partiallycorrectfeedbackformat>1</partiallycorrectfeedbackformat>
                    <incorrectfeedback>&lt;p&gt;{QUESTION_FEEDBACK_INCORRECT.format(subject='Die Antwort')}&lt;/p&gt;</incorrectfeedback>
                    <incorrectfeedbackformat>1</incorrectfeedbackformat>
                    <shownumcorrect>1</shownumcorrect>
                    <showmisplaced>0</showmisplaced>
                  </ddmarker>
                  <drags>
{chr(10).join(drag_blocks)}
                  </drags>
                  <drops>
{chr(10).join(drop_blocks)}
                  </drops>"""

    return build_question_xml(question, id_gen, 'ddmarker', plugin_inner, penalty="0.3333333")
