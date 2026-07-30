"""Wandelt OLATs Wiki-Syntax (MediaWiki-artig) in HTML um.

Bewusst als eigenständiges Modul: die Umwandlung ist eine Annäherung
(OLATs Wiki-Markup ist nicht vollständig dokumentiert, echte Exporte zeigen
auch uneinheitliche/fehlerhafte Syntax), lässt sich dadurch aber einfach
aus wiki_builder.py wieder herauslösen oder ersetzen, ohne den Rest der
Extraktion anzufassen.

Unterstützt: '''fett''', ''kursiv'', ==Überschrift== (Ebene 2-5), '* '-Listen,
'# '-nummerierte Listen, [[Seite]]/[[Seite|Text]]-interne Links. Interne
Links werden NICHT zu echten Verweisen aufgelöst (dafür müsste die ganze
Seitenstruktur vorab bekannt sein) - nur ihr Anzeigetext bleibt stehen,
damit zumindest kein rohes Klammer-Markup sichtbar ist.
"""

import html as html_lib
import re

_BOLD = re.compile(r"'''(.+?)'''")
_ITALIC = re.compile(r"''(.+?)''")
_HEADING = re.compile(r'^(={2,5})\s*(.+?)\s*=+\s*$')
_INTERNAL_LINK = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')
_BULLET_ITEM = re.compile(r'^\*\s+(.*)$')
_NUMBERED_ITEM = re.compile(r'^#\s+(.*)$')


def _inline_markup(text: str) -> str:
    """Wandelt Inline-Markup (fett/kursiv/interne Links) einer bereits
    HTML-escapten Zeile um - Reihenfolge wichtig: Links vor Fett/Kursiv,
    sonst würde z.B. ein Apostroph im Linktext als Kursiv-Markierung
    fehlinterpretiert."""
    text = _INTERNAL_LINK.sub(lambda m: m.group(2) or m.group(1), text)
    text = _BOLD.sub(r'<strong>\1</strong>', text)
    text = _ITALIC.sub(r'<em>\1</em>', text)
    return text


def _flush_list(lines: list, tag: str) -> str:
    """Baut ein <ul>/<ol> aus gesammelten Listeneinträgen."""
    if not lines:
        return ''
    items = ''.join(f'<li>{_inline_markup(html_lib.escape(li, quote=False))}</li>' for li in lines)
    return f'<{tag}>{items}</{tag}>'


def to_html(wikitext: str) -> str:
    """Wandelt eine komplette OLAT-Wiki-Seite in HTML um. Erkennt bewusst
    nur die oben dokumentierten Muster - alles andere (z.B. Tabellen-Syntax
    '{| ... |}') bleibt als escapter Fließtext stehen statt kaputt zu
    rendern oder eine Exception zu werfen."""
    if not wikitext.strip():
        return ''

    html_parts = []
    bullet_buffer: list = []
    numbered_buffer: list = []

    def flush_buffers():
        if bullet_buffer:
            html_parts.append(_flush_list(bullet_buffer, 'ul'))
            bullet_buffer.clear()
        if numbered_buffer:
            html_parts.append(_flush_list(numbered_buffer, 'ol'))
            numbered_buffer.clear()

    for raw_line in wikitext.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            flush_buffers()
            continue

        heading_match = _HEADING.match(line)
        bullet_match = _BULLET_ITEM.match(line)
        numbered_match = _NUMBERED_ITEM.match(line)

        if heading_match:
            flush_buffers()
            level = len(heading_match.group(1))
            title = _inline_markup(html_lib.escape(heading_match.group(2), quote=False))
            html_parts.append(f'<h{level}>{title}</h{level}>')
        elif bullet_match:
            numbered_buffer and flush_buffers()
            bullet_buffer.append(bullet_match.group(1))
        elif numbered_match:
            bullet_buffer and flush_buffers()
            numbered_buffer.append(numbered_match.group(1))
        else:
            flush_buffers()
            html_parts.append(f'<p>{_inline_markup(html_lib.escape(line, quote=False))}</p>')

    flush_buffers()
    return ''.join(html_parts)
