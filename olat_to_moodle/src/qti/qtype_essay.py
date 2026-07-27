"""Fragetyp Freitext (Essay) - optional mit Dateianhang.

OLATs "Freitext" kann zusätzlich zum Textfeld (extendedTextInteraction)
eine Upload-Checkbox haben (dann exportiert OLAT ein zweites
uploadInteraction im selben Item); die eigenständige "Datei hochladen"-
Frage exportiert NUR das uploadInteraction, oft sogar ganz ohne
Fragetext. Moodles Essay-Typ kann Textfeld und Anhang unabhängig
schalten, deshalb werden beide Fälle hier gemeinsam behandelt.

Bei reinem Upload bleibt das Textfeld trotzdem sichtbar (nur
responserequired=0, nicht responseformat=noinline) - sonst wüssten
Studierende ohne eigenen Fragetext nicht, was verlangt wird. Stattdessen
steht ein Hinweistext vorausgefüllt im responsetemplate.
"""

import xml.etree.ElementTree as ET
from typing import Dict, Optional

from .helpers import element_inner_html, process_html_and_images, build_question_xml, IdGenerator

_UPLOAD_ONLY_HINT = "Bitte laden Sie hier Ihre Datei hoch (kein Fließtext erforderlich)."


def parse_essay(root: ET.Element, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """None, wenn weder Text- noch Upload-Interaktion vorhanden ist."""
    text_interaction = root.find('.//extendedTextInteraction')
    upload_interaction = root.find('.//uploadInteraction')
    if text_interaction is None and upload_interaction is None:
        return None

    expected_lines = text_interaction.get('expectedLines') if text_interaction is not None else None
    try:
        response_lines = int(expected_lines) if expected_lines else 15
    except ValueError:
        response_lines = 15

    text_parts = []
    item_body = root.find('.//itemBody')
    if item_body is not None:
        for elem in item_body:
            if elem.tag not in ('extendedTextInteraction', 'uploadInteraction'):
                text_parts.append(element_inner_html(elem))

    question_html = '\n'.join(filter(None, text_parts))
    question_text, text_files = process_html_and_images(question_html, vfs)

    return {
        'qtype': 'essay',
        'title': root.get('title', 'Unbenannt'),
        'text': question_text,
        'text_files': text_files,
        'response_lines': response_lines,
        'has_text_response': text_interaction is not None,
        'allow_attachments': upload_interaction is not None,
    }


def generate_essay_xml(q: Dict, id_gen: IdGenerator) -> str:
    """responseformat bleibt immer 'editor' (Feld sichtbar), siehe Moduldokstring."""
    essay_id = id_gen.next()

    has_text = q.get('has_text_response', True)
    allow_attachments = q.get('allow_attachments', False)
    response_required = '1' if has_text else '0'
    attachments = '1' if allow_attachments else '0'
    attachments_required = '1' if allow_attachments else '0'
    response_template = '' if has_text else _UPLOAD_ONLY_HINT

    plugin_inner = f"""                  <essay id="{essay_id}">
                    <responseformat>editor</responseformat>
                    <responserequired>{response_required}</responserequired>
                    <responsefieldlines>{q['response_lines']}</responsefieldlines>
                    <minwordlimit>$@NULL@$</minwordlimit>
                    <maxwordlimit>$@NULL@$</maxwordlimit>
                    <attachments>{attachments}</attachments>
                    <attachmentsrequired>{attachments_required}</attachmentsrequired>
                    <graderinfo></graderinfo>
                    <graderinfoformat>1</graderinfoformat>
                    <responsetemplate>{response_template}</responsetemplate>
                    <responsetemplateformat>1</responsetemplateformat>
                    <filetypeslist></filetypeslist>
                    <maxbytes>0</maxbytes>
                  </essay>"""

    return build_question_xml(q, id_gen, 'essay', plugin_inner, penalty="0.0000000")
