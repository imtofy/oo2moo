"""Wandelt OLATs Wiki-Syntax (MediaWiki-artig) in HTML um.

Bewusst als eigenständiges Modul: die Umwandlung ist eine Annäherung
(OLATs Wiki-Markup ist nicht vollständig dokumentiert, echte Exporte zeigen
auch uneinheitliche/fehlerhafte Syntax), lässt sich dadurch aber einfach
aus wiki_builder.py wieder herauslösen oder ersetzen, ohne den Rest der
Extraktion anzufassen.

Unterstützt: '''fett''', ''kursiv'', ==Überschrift== (Ebene 2-5), '* '-Listen,
'# '-nummerierte Listen, [[Seite]]/[[Seite|Text]]-interne Links. Interne
Links werden NICHT zu echten Verweisen aufgelöst (dafür müsste die ganze
Seitenstruktur vorab bekannt sein) – nur ihr Anzeigetext bleibt stehen,
damit zumindest kein rohes Klammer-Markup sichtbar ist.
"""

import html as html_lib
import re

_BOLD = re.compile(r"'''(.+?)'''")
_ITALIC = re.compile(r"''(.+?)''")
_HEADING = re.compile(r'^(={2,5})\s*(.+?)\s*=+\s*$')
_INTERNAL_LINK = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')
# Führende Marker bestimmen die Ebene: '*' → Aufzählung, '#' → nummeriert,
# ein Marker je Ebene ('** Punkt' ist zweite Ebene). Der Whitespace danach ist
# Pflicht, sonst würde ein fett gesetzter Zeilenanfang ('''Text''') als
# Listenpunkt gelesen.
_LIST_ITEM = re.compile(r'^([*#]+)\s+(.*)$')


def _inline_markup(text: str) -> str:
    """Wandelt Inline-Markup (fett/kursiv/interne Links) einer bereits
    HTML-escapten Zeile um – Reihenfolge wichtig: Links vor Fett/Kursiv,
    sonst würde z.B. ein Apostroph im Linktext als Kursiv-Markierung
    fehlinterpretiert."""
    text = _INTERNAL_LINK.sub(lambda match: match.group(2) or match.group(1), text)
    text = _BOLD.sub(r'<strong>\1</strong>', text)
    text = _ITALIC.sub(r'<em>\1</em>', text)
    return text


def _list_tag(marker: str) -> str:
    """'*' → <ul>, '#' → <ol> (maßgeblich ist der letzte Marker der Ebene)."""
    return 'ul' if marker == '*' else 'ol'


def to_html(wikitext: str) -> str:
    """Wandelt eine komplette OLAT-Wiki-Seite in HTML um. Erkennt bewusst
    nur die oben dokumentierten Muster – alles andere (z.B. Tabellen-Syntax
    '{| ... |}') bleibt als escapter Fließtext stehen statt kaputt zu
    rendern oder eine Exception zu werfen."""
    if not wikitext.strip():
        return ''

    html_parts = []
    # Offene Listen, äußerste zuerst – je Eintrag das Tag ('ul'/'ol'), damit
    # beim Schließen dasselbe herauskommt, das geöffnet wurde.
    open_lists: list = []
    # True, wenn die innerste offene Liste einen noch nicht geschlossenen
    # <li>-Eintrag hat. Eine Unterliste gehört INNERHALB dieses <li> – als
    # Geschwister neben <li> wäre das ungültiges HTML.
    item_open = False

    def close_lists(bis_tiefe: int = 0):
        """Schließt alle Listen tiefer als bis_tiefe samt ihrer <li>."""
        nonlocal item_open
        while len(open_lists) > bis_tiefe:
            if item_open:
                html_parts.append('</li>')
            html_parts.append(f'</{open_lists.pop()}>')
            # Nach dem Schließen stehen wir wieder im <li> der Elternliste,
            # das beim Verschachteln offen geblieben ist.
            item_open = bool(open_lists)

    for raw_line in wikitext.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            close_lists()
            continue

        heading_match = _HEADING.match(line)
        list_match = _LIST_ITEM.match(line)

        if heading_match:
            close_lists()
            level = len(heading_match.group(1))
            title = _inline_markup(html_lib.escape(heading_match.group(2), quote=False))
            html_parts.append(f'<h{level}>{title}</h{level}>')
        elif list_match:
            marker, text = list_match.group(1), list_match.group(2)
            depth = len(marker)
            tag = _list_tag(marker[-1])

            close_lists(depth)
            # Gleiche Ebene, andere Listenart ('* a' gefolgt von '# b'):
            # die alte Liste beenden und eine neue aufmachen.
            if len(open_lists) == depth and depth and open_lists[-1] != tag:
                close_lists(depth - 1)
            # Tiefer geworden: fehlende Ebenen aufmachen. Springt der Text
            # eine Ebene über (von * direkt zu ***), entstehen die
            # Zwischenebenen mit derselben Listenart – und brauchen ein
            # leeres <li> als Träger, weil eine Unterliste nur INNERHALB
            # eines <li> stehen darf.
            while len(open_lists) < depth:
                if open_lists and not item_open:
                    html_parts.append('<li>')
                    item_open = True
                html_parts.append(f'<{tag}>')
                open_lists.append(tag)
                item_open = False

            if item_open:
                html_parts.append('</li>')
            html_parts.append(f'<li>{_inline_markup(html_lib.escape(text, quote=False))}')
            item_open = True
        else:
            close_lists()
            html_parts.append(f'<p>{_inline_markup(html_lib.escape(line, quote=False))}</p>')

    close_lists()
    return ''.join(html_parts)
