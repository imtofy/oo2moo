"""Fragetyp Hotspot (Bildmarkierung) → Moodles ddmarker ('Drag & Drop Markierung').

Nur KORREKTE hotspotChoice-Bereiche werden übernommen: ddmarker kennt
keine Distraktor-Zonen (jede Drop-Zone muss bedient werden können), also
werden falsche Bereiche verworfen (mit Log) statt den Test unlösbar zu
machen.

Koordinaten-Mapping (QTI kommagetrennt → Moodle ddmarker semikolon-Punkte):
    circle: "x,y,r"          → "x,y;r"
    rect:   "x1,y1,x2,y2"    → "x1,y1;x2,y2"   (Shape: "rectangle")
    poly:   "x1,y1,x2,y2,.." → "x1,y1;x2,y2;.." (Shape: "polygon")

QTI liefert keine Textbezeichnung pro Bereich, nur Koordinaten - drags
bekommen daher generische Labels ("Bereich N"), ggf. beim Merge von Hand
nachbessern. Das Hintergrundbild wird automatisch via
qti_pipeline._embed_question_images in die files.xml eingebettet
(component=qtype_ddmarker, filearea=bgimage) - fehlt es im Archiv, bleibt
die Frage bildlos (mit Warnung).
"""

import os
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from .helpers import element_inner_html, process_html_and_images, build_question_xml

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

    correct_ids = set()
    response_decl = root.find('.//responseDeclaration')
    if response_decl is not None:
        for value in response_decl.findall('.//correctResponse/value'):
            if value.text:
                correct_ids.add(value.text.strip())

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


def _convert_coords(shape: str, qti_coords: str) -> str:
    """Wandelt QTI-Hotspot-Koordinaten (kommagetrennt) in Moodle-ddmarker-
    Koordinaten (semikolongetrennte Punkte) um - siehe Modul-Docstring."""
    parts = [p.strip() for p in qti_coords.split(',')]
    if shape == 'circle':
        x, y, r = parts[0], parts[1], parts[2]
        return f"{x},{y};{r}"
    points = [f"{parts[i]},{parts[i + 1]}" for i in range(0, len(parts) - 1, 2)]
    return ';'.join(points)


def generate_hotspot_xml(q: Dict, id_gen) -> str:
    """Nur die korrekt markierten Bereiche werden zu Drag/Drop-Paaren (siehe Moduldokstring)."""
    correct_regions = [r for r in q['regions'] if r['is_correct']]
    dropped = len(q['regions']) - len(correct_regions)
    if dropped:
        print(f"[*] '{q['title']}': {dropped} nicht-korrekte(r) Hotspot-Bereich(e) "
              f"verworfen (Drag & Drop Markierungen kennen keine Distraktor-Zonen).")

    if q.get('image_data') is None:
        print(f"[!] '{q['title']}': Hintergrundbild '{q.get('image_filename')}' "
              f"nicht im Archiv gefunden – die Frage ist ohne Bild in Moodle unbrauchbar.")
    else:
        print(f"[*] '{q['title']}': Hintergrundbild '{q['image_filename']}' wird "
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
                    <correctfeedback>&lt;p&gt;Die Antwort ist richtig.&lt;/p&gt;</correctfeedback>
                    <correctfeedbackformat>1</correctfeedbackformat>
                    <partiallycorrectfeedback>&lt;p&gt;Die Antwort ist teilweise richtig.&lt;/p&gt;\
</partiallycorrectfeedback>
                    <partiallycorrectfeedbackformat>1</partiallycorrectfeedbackformat>
                    <incorrectfeedback>&lt;p&gt;Die Antwort ist falsch.&lt;/p&gt;</incorrectfeedback>
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

    return build_question_xml(q, id_gen, 'ddmarker', plugin_inner, penalty="0.3333333")
