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

from config import (ALLOWED_MOODLE_FRACTIONS, STAMP_HOST,
                    QUESTION_FEEDBACK_CORRECT, QUESTION_FEEDBACK_PARTIAL,
                    QUESTION_FEEDBACK_INCORRECT)
from conversion.file_manager import escape_xml_text, FileAreaNames
from conversion.html_cleaner import rewrite_math_formulas

# Ein Lückentext-Platzhalter in QTI (<textEntryInteraction/>), egal ob mit
# oder ohne schließendem Tag – wird von qtype_shortanswer.py und
# qtype_cloze.py per re.sub() durch die passende Moodle-Cloze-Syntax ersetzt.
_TAG_PATTERN = r'<textEntryInteraction[^>]*/?>(?:</textEntryInteraction>)?'


def escape_cloze_text(text: str) -> str:
    """Maskiert \\ ~ = # { } per vorangestelltem Backslash – NICHT html.escape(),
    Moodle interpretiert Text in {n:TYPE:...} als Cloze-Syntax, nicht HTML.
    Der Backslash wird zuerst maskiert, sonst würden die danach eingefügten
    Escape-Backslashes ein zweites Mal escaped."""
    for ch in ('\\', '~', '=', '#', '{', '}'):
        text = text.replace(ch, '\\' + ch)
    return text


def calculate_choice_fractions(choices: List[Dict], single: bool) -> Tuple[List[Dict], bool]:
    """Verteilt die Bewertungsanteile und gibt (choices, tatsächliches single)
    zurück.

    Bei single=True bekommt die richtige Option 100%, alle anderen 0%. Bei
    single=False wird 100% gleichmäßig auf alle richtigen verteilt und der
    Malus symmetrisch auf alle falschen, gerundet auf den nächsten von
    Moodle akzeptierten Wert (get_closest_fraction). Mutiert choices direkt.

    Sind bei single=True MEHRERE Antworten als korrekt markiert, wird auf
    Mehrfachauswahl umgeschaltet: Moodle erwartet bei single genau eine
    100%-Antwort, mehrere ergäben eine Frage, die sich nicht auswerten lässt.
    Die Alternative (nur die erste richtige gelten lassen) würde die übrigen
    stillschweigend als falsch markieren – das Umschalten erhält dagegen die
    Information aus dem Export."""
    correct_count = sum(1 for choice in choices if choice['is_correct'])
    wrong_count = len(choices) - correct_count

    if single and correct_count > 1:
        print(f"[!] Als Einfachauswahl deklarierte Frage hat {correct_count} richtige "
              f"Antworten – wird als Mehrfachauswahl übernommen, damit alle richtigen "
              f"Antworten erhalten bleiben.")
        single = False
    elif single and correct_count == 0:
        print("[!] Einfachauswahl-Frage ohne als richtig markierte Antwort – "
              "in Moodle ist dann keine Antwort korrekt, bitte prüfen.")

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
    return choices, single


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
    """Sucht <assessmentItem gefolgt von Leerzeichen/'>' – ohne diese Tag-Grenze
    würde ein Substring-Check auch bei <assessmentItemRef> anschlagen."""
    return re.search(r'<assessmentItem[\s>]', xml_content) is not None


def get_closest_fraction(value: float) -> str:
    """Rundet einen Prozentwert auf den nächsten von Moodle akzeptierten Fraction-Wert."""
    closest = min(ALLOWED_MOODLE_FRACTIONS, key=lambda fraction: abs(fraction - value))
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
    names = FileAreaNames()

    def _replace_image_source(match):
        """Ersetzt ein einzelnes src="..." durch die @@PLUGINFILE@@-Variante, falls im vfs gefunden."""
        quote = match.group(1)
        src = match.group(2)
        if src.startswith(('http://', 'https://', 'data:', '@@PLUGINFILE@@')):
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
            # Der Verweis wird hier erst geschrieben, deshalb reicht
            # assign() – es gibt noch kein HTML, das nachzuziehen wäre.
            filename = names.assign(os.path.basename(src), file_data)
            attached_files[filename] = base64.b64encode(file_data).decode('ascii')
            return f'src={quote}@@PLUGINFILE@@/{filename}{quote}'

        return match.group(0)

    clean_html = re.sub(r'''src=(["'])(.*?)\1''', _replace_image_source, html_string)
    # OLATs <span class="math">-Formeln auf Moodles LaTeX-Trennzeichen
    # umschreiben – dieselbe Behandlung wie bei Seiteninhalten, nur laufen
    # Fragetexte nicht durch sanitize_for_moodle().
    clean_html = rewrite_math_formulas(clean_html)
    file_list = [{"name": name, "b64": b64_data} for name, b64_data in attached_files.items()]
    return clean_html, file_list


def answer_xml(answer_id: int, text: str, fraction: str, answerformat: int = 1) -> str:
    """Ein <answer>-Element, wie es alle Fragetypen mit question_answers
    brauchen (Multiple Choice, Kprim, Cloze-Lücken, Dropdown, Freitextlücke).

    answerformat 1 = HTML (Antwort darf Formatierung/Bilder enthalten),
    0 = reiner Text; Lückentext-Antworten sind immer 0, weil Moodle sie
    unformatiert mit der Eingabe vergleicht. fraction kommt fertig als
    Moodle-Dezimalzahl herein (siehe format_fraction_decimal)."""
    return f"""                    <answer id="{answer_id}">
                      <answertext>{escape_xml_text(text)}</answertext>
                      <answerformat>{answerformat}</answerformat>
                      <fraction>{fraction}</fraction>
                      <feedback></feedback>
                      <feedbackformat>1</feedbackformat>
                    </answer>"""


def correct_response_values(root: ET.Element) -> List[str]:
    """Liest die Werte aus <correctResponse> der ersten <responseDeclaration>.

    Was darin steht, hängt vom Fragetyp ab: bei Auswahlfragen die
    identifier der richtigen Optionen, bei Zuordnungen ein Paar
    '<archive> <target>' je Zeile (siehe correct_response_pairs)."""
    response_decl = root.find('.//responseDeclaration')
    if response_decl is None:
        return []
    return [value.text.strip() for value in response_decl.findall('.//correctResponse/value')
            if value.text and value.text.strip()]


def correct_response_pairs(root: ET.Element) -> Dict[str, str]:
    """Zuordnungs-Fragetypen speichern jede richtige Verknüpfung als
    '<archive> <target>' in einem <value> – hier zu {archive: target} aufgelöst.
    Werte ohne Leerzeichen sind keine Zuordnung und fallen weg."""
    pairs = {}
    for value in correct_response_values(root):
        if ' ' in value:
            archive, target = value.split(' ', 1)
            pairs[archive] = target
    return pairs


def extract_question_text(root: ET.Element, vfs: Dict[str, bytes],
                          *interaction_tags: str) -> Tuple[str, List[Dict[str, str]]]:
    """Sammelt den Fragetext aus <itemBody> und gibt (HTML, Bilddateien) zurück.

    Die Interaktions-Elemente selbst gehören nicht dazu – sie enthalten die
    Antwortoptionen, die jeder Fragetyp eigenständig auswertet. Welche das
    sind, gibt der Aufrufer als interaction_tags mit ('choiceInteraction',
    bei Freitext auch mehrere).

    Ohne <itemBody> bleibt der Text leer, statt eine Ausnahme zu werfen –
    der Aufrufer entscheidet dann selbst, ob die Frage trotzdem brauchbar
    ist."""
    item_body = root.find('.//itemBody')
    text_parts = []
    if item_body is not None:
        for elem in item_body:
            if elem.tag not in interaction_tags:
                text_parts.append(element_inner_html(elem))
    return process_html_and_images('\n'.join(filter(None, text_parts)), vfs)


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


# Bilder in einzelnen Antwortoptionen gehören NICHT in den Dateibereich der
# Frage, sondern in den der jeweiligen Antwort – Moodle stellt sie über die
# Mapping-Namen 'question_answer' bzw. 'qtype_match_subquestions' wieder her
# (restore_stepslib.php, send_common_files/send_qtype_files). Je Fragetyp:
# welches XML-Element die Antwort-IDs trägt und wohin die Dateien gehören.
_ANSWER_FILE_TARGETS = {
    'multichoice': ('answer', 'question', 'answer'),
    'kprim': ('answer', 'question', 'answer'),
    'matching': ('match', 'qtype_match', 'subquestion'),
    'order': ('match', 'qtype_match', 'subquestion'),
}

_ANSWER_ID_RE = {
    'answer': re.compile(r'<answer id="(\d+)"'),
    'match': re.compile(r'<match id="(\d+)"'),
}

def warn_dropped_files(question: Dict) -> None:
    """Meldet Bilder in Antwortoptionen, für die es keinen Moodle-Dateibereich
    gibt.

    Für die meisten Fragetypen werden sie eingebettet (siehe
    qti_pipeline._ANSWER_FILE_TARGETS); nur bei den dort nicht aufgeführten
    bliebe der @@PLUGINFILE@@-Verweis ein toter Link. Genau dieser Restfall
    wird hier sichtbar gemacht, statt ihn stillschweigend passieren zu lassen."""
    if question.get('qtype') in _ANSWER_FILE_TARGETS:
        return
    dropped_files = []
    for collection_key in ('choices', 'subquestions'):
        for entry in question.get(collection_key) or []:
            dropped_files.extend(entry.get('files') or [])
    if dropped_files:
        names = ', '.join(dropped['name'] for dropped in dropped_files)
        print(f"[!] '{question['title']}': {len(dropped_files)} Bild(er) in Antwortoptionen "
              f"werden nicht eingebettet ({names}) – Fragetext-Bilder dagegen schon.")


def build_question_element(qid: int, name: str, questiontext: str, qtype_name: str,
                           plugin_inner_xml: str, parent: int = 0,
                           penalty: str = "0.3333333", defaultmark: str = "1.0000000") -> str:
    """Baut ein einzelnes <question>-Element im Moodle-Backup-Format.

    parent ist 0 für eigenständige Fragen, sonst die ID der multianswer-
    Elternfrage. questiontext wird zusätzlich HTML-escaped (<p> zu &lt;p&gt;),
    weil das Backup-XML-Format enthaltene HTML-Tags sonst als kaputte
    XML-Struktur werten würde – Eigenheit des .mbz-Formats, kein Bug.

    Low-Level-Baustein ohne Kopplung an ein Frage-Dict/IdGenerator – für
    Mehrfach-Entry-Fragetypen (Cloze/Dropdown), die mehrere <question>-
    Elemente mit expliziten parent-Verknüpfungen selbst zusammenbauen
    (siehe qtype_cloze.generate_cloze_entries).
    """
    safe_name = escape_xml_text(name)
    safe_text = html_lib.escape(questiontext, quote=False)

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


def build_question_xml(question: Dict, id_gen: IdGenerator, qtype_name: str,
                       plugin_inner_xml: str, penalty: str = "0.3333333") -> str:
    """Dünner Wrapper um build_question_element für einfache, nicht-mehrteilige
    Fragetypen (multichoice, truefalse, essay, ...) – zieht Titel/Text
    direkt aus dem Frage-Dict und warnt vorab über nicht transportierte
    Bilder (warn_dropped_files)."""
    qid = id_gen.next()
    warn_dropped_files(question)
    return build_question_element(qid, question['title'], question['text'], qtype_name,
                                  plugin_inner_xml, parent=0, penalty=penalty)


def wrap_question_bank_entry(question_xml: str, cat_id: int, id_gen: IdGenerator):
    """Wrappt ein <question>-Element in einen vollständigen question_bank_entry
    (question_bank_entry → question_version → question_versions →
    questions → question).

    WICHTIG: der Container heißt <question_version> (Singular), die
    einzelne Version darin <question_versions> (Plural, mit id) – genau
    umgekehrt, als die Namen vermuten lassen. Andersherum verschachtelt
    legt Moodle die Fragen beim Restore NICHT an ("ungültige Fragetypen" +
    "Invalid context id").

    Gibt (xml_string, entry_id) zurück – entry_id brauchen Aufrufer wie
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
    {#i} (durchgezählt in Dokumentreihenfolge) – das braucht eine
    multianswer-Elternfrage im Backup; die rohe {n:TYPE:...}-Syntax gehört
    nur in die einzelnen Subquestion-Einträge (siehe qtype_cloze.py)."""
    counter = {'i': 0}

    def _restore_cloze_token(_match):
        """Gibt für jeden Treffer der Reihe nach den nächsten {#i}-Platzhalter zurück."""
        counter['i'] += 1
        return f'{{#{counter["i"]}}}'

    return _CLOZE_TOKEN_PATTERN.sub(_restore_cloze_token, text)


def build_file_tags(files_list: List[Dict[str, str]], indent: str) -> str:
    """Baut <file>-Tags (Base64-kodiert) für das generische Standalone-XML-Format."""
    if not files_list:
        return ""
    tags = [
        f'{indent}<file name="{html_lib.escape(attached["name"])}" path="/" encoding="base64">{attached["b64"]}</file>'
        for attached in files_list
    ]
    return "\n" + "\n".join(tags)


def build_match_question_xml(question: Dict, id_gen: IdGenerator,
                            feedback_subject: str = "Die Antwort") -> str:
    """Baut den <question>-Block einer Moodle-'match'-Frage aus
    question['subquestions'] (je {'text', 'answer'}).

    Genutzt von Zuordnungs- UND Sortieraufgaben: Moodle hat keinen eigenen
    Sortier-Fragetyp, eine Sortierung wird deshalb als Zuordnung
    "Element -> Zielposition" abgebildet (siehe qtype_order.py).

    feedback_subject benennt in den Rückmeldungen, was bewertet wurde –
    bei einer Sortieraufgabe die Reihenfolge, sonst die Antwort. Der Rest
    des XML ist für beide identisch."""
    options_id = id_gen.next()
    correct_text = QUESTION_FEEDBACK_CORRECT.format(subject=feedback_subject)
    partial_text = QUESTION_FEEDBACK_PARTIAL.format(subject=feedback_subject)
    incorrect_text = QUESTION_FEEDBACK_INCORRECT.format(subject=feedback_subject)

    match_blocks = []
    for sub in question['subquestions']:
        match_id = id_gen.next()
        safe_text = html_lib.escape(sub['text'], quote=False)
        safe_answer = html_lib.escape(sub['answer'], quote=False)
        match_blocks.append(f"""                    <match id="{match_id}">
                      <questiontext>{safe_text}</questiontext>
                      <questiontextformat>1</questiontextformat>
                      <answertext>{safe_answer}</answertext>
                    </match>""")
    matches_block = '\n'.join(match_blocks)

    plugin_inner = f"""                  <matchoptions id="{options_id}">
                    <shuffleanswers>1</shuffleanswers>
                    <correctfeedback>&lt;p&gt;{correct_text}&lt;/p&gt;</correctfeedback>
                    <correctfeedbackformat>1</correctfeedbackformat>
                    <partiallycorrectfeedback>&lt;p&gt;{partial_text}&lt;/p&gt;</partiallycorrectfeedback>
                    <partiallycorrectfeedbackformat>1</partiallycorrectfeedbackformat>
                    <incorrectfeedback>&lt;p&gt;{incorrect_text}&lt;/p&gt;</incorrectfeedback>
                    <incorrectfeedbackformat>1</incorrectfeedbackformat>
                    <shownumcorrect>1</shownumcorrect>
                  </matchoptions>
                  <matches>
{matches_block}
                  </matches>"""

    return build_question_xml(question, id_gen, 'match', plugin_inner, penalty="0.3333333")
