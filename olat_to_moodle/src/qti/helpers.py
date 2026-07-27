"""Gemeinsame Bausteine für die QTI-Fragen-Pipeline (qti_pipeline.py + alle qtype_*.py).

Bündelt alles, was mehrere Fragetyp-Module gleich brauchen: XML-Vorverarbeitung
(Namespaces entfernen, HTML aus QTI-Elementen extrahieren), Bild-Einbettung als
Base64, Moodle-Fraction-Berechnung, den Cloze-Escaping-Mechanismus und die
XML-Bausteine, aus denen jede Frage/jeder question_bank_entry zusammengesetzt
wird. Braucht ALLOWED_MOODLE_FRACTIONS und STAMP_HOST aus config.py.
"""

import os
import re
import time
import random
import string
import base64
import html as html_lib
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple

from config import ALLOWED_MOODLE_FRACTIONS, STAMP_HOST

# Ein Lückentext-Platzhalter in QTI (<textEntryInteraction/>), egal ob mit
# oder ohne schließendem Tag - wird von qtype_shortanswer.py und
# qtype_cloze.py per re.sub() durch die passende Moodle-Cloze-Syntax ersetzt.
_TAG_PATTERN = r'<textEntryInteraction[^>]*/?>(?:</textEntryInteraction>)?'


def escape_cloze_text(text: str) -> str:
    """Maskiert \\ ~ = # { } per vorangestelltem Backslash - NICHT html.escape(),
    Moodle interpretiert Text in {n:TYPE:...} als Cloze-Syntax, nicht HTML.
    Der Backslash wird zuerst maskiert, sonst würden die danach eingefügten
    Escape-Backslashes ein zweites Mal escaped."""
    for ch in ('\\', '~', '=', '#', '{', '}'):
        text = text.replace(ch, '\\' + ch)
    return text


def calculate_choice_fractions(choices: List[Dict], single: bool) -> List[Dict]:
    """Bei single=True bekommt die richtige Option 100%, alle anderen 0%. Bei
    single=False wird 100% gleichmäßig auf alle richtigen verteilt und der
    Malus symmetrisch auf alle falschen, gerundet auf den nächsten von
    Moodle akzeptierten Wert (get_closest_fraction). Mutiert choices direkt."""
    correct_count = sum(1 for c in choices if c['is_correct'])
    wrong_count = len(choices) - correct_count

    if single and correct_count != 1:
        print(f"[!] Single-Choice-Frage mit {correct_count} als korrekt markierten "
              f"Antworten – Moodle erwartet genau eine 100%-Antwort, Ergebnis prüfen.")

    for choice in choices:
        if single:
            choice['fraction'] = "100.0" if choice['is_correct'] else "0.0"
        else:
            if correct_count == 0:
                choice['fraction'] = "0.0"
            elif choice['is_correct']:
                choice['fraction'] = get_closest_fraction(100.0 / correct_count)
            else:
                calc = -100.0 / wrong_count if wrong_count > 0 else 0.0
                choice['fraction'] = get_closest_fraction(calc)
    return choices


def strip_namespaces(xml_string: str) -> str:
    """Entfernt xmlns-Deklarationen und Tag-/Attribut-Präfixe aus einem XML-String,
    damit ET.fromstring() Tags ohne Namespace-Umweg ansprechen kann."""
    xml_string = re.sub(r'\s+xmlns(?::[a-zA-Z0-9_-]+)?=(["\']).*?\1', '', xml_string)
    xml_string = re.sub(r'\s+[a-zA-Z0-9_-]+:[a-zA-Z0-9_-]+=(["\']).*?\1', '', xml_string)
    xml_string = re.sub(r'<(/?)[a-zA-Z0-9_-]+:([a-zA-Z0-9_-]+)', r'<\1\2', xml_string)
    return xml_string


def element_inner_html(element: ET.Element) -> str:
    """Gibt den inneren Inhalt eines XML-Elements als HTML-String zurück (Text + Kind-Tags)."""
    text = element.text or ""
    for child in element:
        text += ET.tostring(child, encoding='unicode', method='xml')
    return text.strip()


def strip_tags(html_string: str) -> str:
    """Entfernt alle HTML-Tags und gibt den reinen Text zurück."""
    return re.sub(r'<[^>]+>', '', html_string or '').strip()


def is_qti_item(xml_content: str) -> bool:
    """Sucht <assessmentItem gefolgt von Leerzeichen/'>' - ohne diese Tag-Grenze
    würde ein Substring-Check auch bei <assessmentItemRef> anschlagen."""
    return re.search(r'<assessmentItem[\s>]', xml_content) is not None


def get_closest_fraction(value: float) -> str:
    """Rundet einen Prozentwert auf den nächsten von Moodle akzeptierten Fraction-Wert."""
    closest = min(ALLOWED_MOODLE_FRACTIONS, key=lambda x: abs(x - value))
    return str(closest)


def format_fraction_decimal(percentage_str: str) -> str:
    """Wandelt einen Prozentwert ("100.0") in Moodles Dezimalformat ("1.0000000") um."""
    return f"{float(percentage_str) / 100:.7f}"


def process_html_and_images(html_string: str,
                            vfs: Dict[str, bytes]) -> Tuple[str, List[Dict[str, str]]]:
    """Schreibt Bild-Referenzen auf @@PLUGINFILE@@ um und sammelt die Bilddaten
    als Base64. Sucht je src erst den exakten Pfad im vfs, sonst per exaktem
    Basename-Vergleich (nicht endswith(), sonst würde z.B. 'a.png' fälschlich
    auch 'media.png' treffen)."""
    attached_files: Dict[str, str] = {}

    def replacer(match):
        """Ersetzt ein einzelnes src="..." durch die @@PLUGINFILE@@-Variante, falls im vfs gefunden."""
        quote = match.group(1)
        src = match.group(2)
        if src.startswith(('http', 'data:', '@@PLUGINFILE@@')):
            return match.group(0)

        file_data = None
        if src in vfs:
            file_data = vfs[src]
        else:
            basename = os.path.basename(src)
            for path, data in vfs.items():
                if os.path.basename(path) == basename:
                    file_data = data
                    break

        if file_data:
            filename = os.path.basename(src)
            b64_data = base64.b64encode(file_data).decode('ascii')
            attached_files[filename] = b64_data
            return f'src={quote}@@PLUGINFILE@@/{filename}{quote}'

        return match.group(0)

    clean_html = re.sub(r'''src=(["'])(.*?)\1''', replacer, html_string)
    file_list = [{"name": k, "b64": v} for k, v in attached_files.items()]
    return clean_html, file_list


class IdGenerator:
    """Zählt fortlaufende, eindeutige IDs für ein Backup-XML-Dokument hoch.

    Braucht: start (erste vergebene ID, Standard 1). Ein IdGenerator wird
    pro Konvertierungslauf einmal erzeugt und dann an alle Fragen-/
    Kategorie-/Quiz-Bau-Funktionen durchgereicht, damit über den ganzen Lauf
    hinweg keine ID doppelt vergeben wird.
    """

    def __init__(self, start: int = 1):
        """Setzt den Zähler auf start."""
        self._next = start

    def next(self) -> int:
        """Gibt die nächste freie ID zurück und zählt danach hoch."""
        value = self._next
        self._next += 1
        return value


def make_stamp() -> str:
    """Baut Moodles 'stamp'-Kennung (Host+Zeitstempel+Zufallssuffix) für ein XML-Element."""
    timestamp = time.strftime("%y%m%d%H%M%S")
    suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    return f"{STAMP_HOST}+{timestamp}+{suffix}"


def warn_dropped_files(q: Dict) -> None:
    """Fragetext-/Hotspot-Bilder werden schon als echte Dateien eingebettet
    (qti_pipeline._embed_question_images), Bilder in einzelnen Antwortoptionen
    dagegen noch nicht - ihr @@PLUGINFILE@@-Verweis bliebe ein toter Link.
    Macht genau diesen Restfall sichtbar statt ihn stillschweigend passieren
    zu lassen."""
    dropped_files = []
    for collection_key in ('choices', 'subquestions'):
        for entry in q.get(collection_key) or []:
            dropped_files.extend(entry.get('files') or [])
    if dropped_files:
        names = ', '.join(f['name'] for f in dropped_files)
        print(f"[!] '{q['title']}': {len(dropped_files)} Bild(er) in Antwortoptionen "
              f"werden noch nicht eingebettet ({names}) – Fragetext-Bilder dagegen schon.")


def build_question_element(qid: int, name: str, questiontext: str, qtype_name: str,
                           plugin_inner_xml: str, parent: int = 0,
                           penalty: str = "0.3333333", defaultmark: str = "1.0000000") -> str:
    """Baut ein einzelnes <question>-Element im Moodle-Backup-Format.

    parent ist 0 für eigenständige Fragen, sonst die ID der multianswer-
    Elternfrage. questiontext wird zusätzlich HTML-escaped (<p> zu &lt;p&gt;),
    weil das Backup-XML-Format enthaltene HTML-Tags sonst als kaputte
    XML-Struktur werten würde - Eigenheit des .mbz-Formats, kein Bug.

    Low-Level-Baustein ohne Kopplung an ein Frage-Dict/IdGenerator - für
    Mehrfach-Entry-Fragetypen (Cloze/Dropdown), die mehrere <question>-
    Elemente mit expliziten parent-Verknüpfungen selbst zusammenbauen
    (siehe qtype_cloze.generate_cloze_entries).
    """
    safe_name = html_lib.escape(name)
    safe_text = html_lib.escape(questiontext)

    stamp = make_stamp()
    now = int(time.time())

    return f"""              <question id="{qid}">
                <parent>{parent}</parent>
                <name>{safe_name}</name>
                <questiontext>{safe_text}</questiontext>
                <questiontextformat>1</questiontextformat>
                <generalfeedback></generalfeedback>
                <generalfeedbackformat>1</generalfeedbackformat>
                <defaultmark>{defaultmark}</defaultmark>
                <penalty>{penalty}</penalty>
                <qtype>{qtype_name}</qtype>
                <length>1</length>
                <stamp>{stamp}</stamp>
                <timecreated>{now}</timecreated>
                <timemodified>{now}</timemodified>
                <createdby>$@NULL@$</createdby>
                <modifiedby>$@NULL@$</modifiedby>
                <plugin_qtype_{qtype_name}_question>
{plugin_inner_xml}
                </plugin_qtype_{qtype_name}_question>
                <plugin_qbank_comment_question>
                  <comments>
                  </comments>
                </plugin_qbank_comment_question>
                <plugin_qbank_customfields_question>
                  <customfields>
                  </customfields>
                </plugin_qbank_customfields_question>
                <question_hints>
                </question_hints>
                <tags>
                </tags>
              </question>"""


def build_question_xml(q: Dict, id_gen: IdGenerator, qtype_name: str,
                       plugin_inner_xml: str, penalty: str = "0.3333333") -> str:
    """Dünner Wrapper um build_question_element für einfache, nicht-mehrteilige
    Fragetypen (multichoice, truefalse, essay, ...) - zieht Titel/Text
    direkt aus dem Frage-Dict und warnt vorab über nicht transportierte
    Bilder (warn_dropped_files)."""
    qid = id_gen.next()
    warn_dropped_files(q)
    return build_question_element(qid, q['title'], q['text'], qtype_name,
                                  plugin_inner_xml, parent=0, penalty=penalty)


def wrap_question_bank_entry(question_xml: str, cat_id: int, id_gen: IdGenerator):
    """Wrappt ein <question>-Element in einen vollständigen question_bank_entry
    (question_bank_entry → question_version → question_versions →
    questions → question).

    WICHTIG: der Container heißt <question_version> (Singular), die
    einzelne Version darin <question_versions> (Plural, mit id) - genau
    umgekehrt, als die Namen vermuten lassen. Andersherum verschachtelt
    legt Moodle die Fragen beim Restore NICHT an ("ungültige Fragetypen" +
    "Invalid context id").

    Gibt (xml_string, entry_id) zurück - entry_id brauchen Aufrufer wie
    qti_quiz_builder.py, um Fragen per <questionbankentryid> in quiz.xml
    einzuhängen.
    """
    entry_id = id_gen.next()
    version_id = id_gen.next()
    xml = f"""      <question_bank_entry id="{entry_id}">
        <questioncategoryid>{cat_id}</questioncategoryid>
        <idnumber>$@NULL@$</idnumber>
        <ownerid>$@NULL@$</ownerid>
        <question_version>
          <question_versions id="{version_id}">
            <version>1</version>
            <status>ready</status>
            <questions>
{question_xml}
            </questions>
          </question_versions>
        </question_version>
      </question_bank_entry>"""
    return xml, entry_id


# Ein vollständiges {n:TYPE:...}-Cloze-Token, wie es escape_cloze_text/die
# qtype_cloze.py- und qtype_inlinechoice.py-Generatoren erzeugen (Inhalt
# enthält dank der Escaping-Logik nie ein unmaskiertes '{' oder '}').
_CLOZE_TOKEN_PATTERN = re.compile(r'\{\d+:[A-Z_]+:(?:\\.|[^\\{}])*}')


def extract_cloze_tokens(text: str) -> List[str]:
    """Liefert alle {n:TYPE:...}-Cloze-Tokens aus einem Fließtext, in Dokumentreihenfolge."""
    return _CLOZE_TOKEN_PATTERN.findall(text)


def replace_cloze_tokens_with_placeholders(text: str) -> str:
    """Ersetzt jedes {n:TYPE:...}-Cloze-Token durch Moodles Platzhalter-Syntax
    {#i} (durchgezählt in Dokumentreihenfolge) - das braucht eine
    multianswer-Elternfrage im Backup; die rohe {n:TYPE:...}-Syntax gehört
    nur in die einzelnen Subquestion-Einträge (siehe qtype_cloze.py)."""
    counter = {'i': 0}

    def _replacer(_match):
        """Gibt für jeden Treffer der Reihe nach den nächsten {#i}-Platzhalter zurück."""
        counter['i'] += 1
        return f'{{#{counter["i"]}}}'

    return _CLOZE_TOKEN_PATTERN.sub(_replacer, text)


def build_file_tags(files_list: List[Dict[str, str]], indent: str) -> str:
    """Baut <file>-Tags (Base64-kodiert) für das generische Standalone-XML-Format."""
    if not files_list:
        return ""
    tags = [
        f'{indent}<file name="{html_lib.escape(f["name"])}" path="/" encoding="base64">{f["b64"]}</file>'
        for f in files_list
    ]
    return "\n" + "\n".join(tags)
