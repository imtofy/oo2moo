"""Erkennt QTI-2.1-Fragen in einem VFS und baut daraus Moodle-questions.xml-Kategorien.

Zentrale Schaltstelle: entscheidet anhand des QTI-Interaction-Tags, welcher
qtype_*.py-Parser ein Item übernimmt, und ruft dessen Generator auf. Bekommt
ein fertiges VFS-Dict (Pfad → Bytes) von qti_quiz_builder.py übergeben,
baut selbst kein eigenes ZIP/Dateisystem auf.
"""

import os
import re
import base64
import xml.etree.ElementTree as ET
import html as html_lib
from typing import List, Dict, Optional

from .helpers import strip_namespaces, is_qti_item, IdGenerator, make_stamp, wrap_question_bank_entry

from .qtype_truefalse import parse_truefalse, generate_truefalse_xml
from .qtype_multichoice import parse_multichoice, generate_multichoice_xml
from .qtype_matching import parse_matching, generate_matching_xml
from .qtype_essay import parse_essay, generate_essay_xml
from .qtype_shortanswer import parse_shortanswer, generate_shortanswer_xml
from .qtype_cloze import parse_cloze, generate_cloze_entries
from .qtype_kprim import parse_kprim, generate_kprim_xml
from .qtype_matrix import parse_matrix
from .qtype_order import parse_order, generate_order_xml
from .qtype_inlinechoice import parse_inlinechoice, generate_inlinechoice_entries
from .qtype_hottext import parse_hottext
from .qtype_hotspot import parse_hotspot, generate_hotspot_xml
from .qtype_drawing import parse_drawing

# Erste <question id="N"> im generierten XML - liefert die Frage-ID, die als
# itemid für die Bilddateien in files.xml gebraucht wird (_embed_question_images).
_QUESTION_ID_RE = re.compile(r'<question id="(\d+)">')

# Reihenfolge in matchInteraction ist entscheidend: parse_kprim/parse_matrix
# müssen vor parse_matching stehen (beide geben bei Nichtübereinstimmung
# None zurück → Fallback zum nächsten). True/false und Drag-and-Drop fallen
# bewusst bis zum generischen parse_matching durch.
INTERACTION_PARSERS = {
    'choiceInteraction':       [parse_truefalse, parse_multichoice],
    'matchInteraction':        [parse_kprim, parse_matrix, parse_matching],
    'orderInteraction':        [parse_order],
    'inlineChoiceInteraction': [parse_inlinechoice],
    'hottextInteraction':      [parse_hottext],
    'hotspotInteraction':      [parse_hotspot],
    'textEntryInteraction':    [parse_shortanswer, parse_cloze],
    'extendedTextInteraction': [parse_essay],
    'uploadInteraction':       [parse_essay],
    'drawingInteraction':      [parse_drawing],
}

# extendedTextInteraction + uploadInteraction dürfen gemeinsam im selben Item
# vorkommen (OLATs Freitext mit "Dateianhang erlauben") - parse_essay()
# verarbeitet beide in einem Aufruf, ohne diese Ausnahme würde die generische
# "andere Interaktionen gehen verloren"-Warnung hier fälschlich auslösen.
_JOINTLY_HANDLED_TAGS = {'extendedTextInteraction', 'uploadInteraction'}

# 'matrix'/'drawing' bewusst nicht registriert (kein Moodle-Standardtyp ohne
# Plugin) → automatischer Skip+Log über generate_question_categories_xml().
# Klarname fürs Systemprotokoll/Log statt des internen qtype-Codes - betrifft
# in der Praxis nur diese beiden, alle anderen qtype-Werte sind schon
# lesbare Bezeichnungen (multichoice, shortanswer, etc.).
_QTYPE_LABELS = {"matrix": "Matrix", "drawing": "Zeichnen"}

GENERATORS = {
    'multichoice': generate_multichoice_xml,
    'truefalse':   generate_truefalse_xml,
    'matching':    generate_matching_xml,
    'essay':       generate_essay_xml,
    'shortanswer': generate_shortanswer_xml,
    'kprim':       generate_kprim_xml,
    'order':       generate_order_xml,
    'hotspot':     generate_hotspot_xml,
}

# Cloze/Dropdown (Moodle-intern 'multianswer') brauchen mehrere
# question_bank_entry-Blöcke pro Frage (Elternfrage + eine je Lücke, siehe
# qtype_cloze.py) - eigener Dispatch-Pfad statt der einfachen GENERATORS oben.
MULTI_ENTRY_GENERATORS = {
    'cloze':          generate_cloze_entries,
    'cloze_dropdown': generate_inlinechoice_entries,
}

INTERACTION_TAG_PRIORITY = [
    'choiceInteraction',
    'matchInteraction',
    'orderInteraction',
    'inlineChoiceInteraction',
    'hottextInteraction',
    'hotspotInteraction',
    'textEntryInteraction',
    'extendedTextInteraction',
    'uploadInteraction',
    'drawingInteraction',
]


def _find_unhandled_interaction_tag(root: ET.Element) -> Optional[str]:
    """Findet jeden *Interaction-Tag, der nicht in INTERACTION_TAG_PRIORITY steht -
    damit verschwindet auch ein künftig neuer, noch unbekannter Fragetyp nicht unbemerkt."""
    known_tags = set(INTERACTION_TAG_PRIORITY)
    for elem in root.iter():
        if elem.tag.endswith('Interaction') and elem.tag not in known_tags:
            return elem.tag
    return None


def _read_item_max_score(root: ET.Element) -> Optional[float]:
    """Liest die Maximalpunktzahl aus der MAXSCORE-outcomeDeclaration, None wenn
    nicht vorhanden/lesbar (Aufrufer nutzt dann den Standardwert)."""
    for od in root.findall('.//outcomeDeclaration'):
        if od.get('identifier') == 'MAXSCORE':
            val = od.findtext('.//defaultValue/value')
            if val:
                try:
                    return float(val.strip())
                except ValueError:
                    return None
            return None
    return None


def _read_item_layout(vfs: Dict[str, bytes]) -> List[Dict[str, str]]:
    """Liest Fragen-Reihenfolge und Sektionszugehörigkeit aus der assessmentTest-Datei.

    Die <assessmentSection title="...">-Blöcke dort gruppieren die Items in
    der vom Autor gewollten Reihenfolge (im OLAT-Testeditor als eigene
    Abschnitte sichtbar, z.B. "Single/Multiple Choice" vs. "Lücken füllen").
    Nur DIREKTE Kind-itemRefs zählen zur jeweiligen Sektion, sonst würden
    Untersektionen den Titel der Elternsektion erben. Leere Liste, wenn
    keine assessmentTest-Datei existiert - dann bleibt die Fundreihenfolge.
    """
    for path, data in vfs.items():
        if not path.lower().endswith('.xml'):
            continue
        if b'assessmentTest' not in data[:4000]:
            continue
        try:
            root = ET.fromstring(strip_namespaces(data.decode('utf-8-sig', errors='replace')))
        except ET.ParseError:
            continue
        layout = []
        for section in root.iter('assessmentSection'):
            title = section.get('title') or ''
            for ref in section.findall('assessmentItemRef'):
                href = ref.get('href')
                if href:
                    layout.append({'file': os.path.basename(href), 'section_title': title})
        if layout:
            return layout
    return []


def find_standalone_test_title(vfs: Dict[str, bytes]) -> Optional[str]:
    """Prüft, ob ein VFS ein eigenständig exportiertes QTI-Testpaket ist (OLAT-
    Testeditor-Export ohne umgebenden Kurs) und liefert dessen Titel.

    main.py ruft das NUR auf, wenn parse_olat_export() keine Kursknoten
    gefunden hat - unterscheidet dort "kaputter/leerer Export" (kein Titel)
    von "eigenständiges Testpaket" (Titel gefunden → Mini-Kurs-Fallback,
    siehe config.STANDALONE_QTI_IDENT).
    """
    for path, data in vfs.items():
        if not path.lower().endswith('.xml'):
            continue
        if b'assessmentTest' not in data[:4000]:
            continue
        try:
            root = ET.fromstring(strip_namespaces(data.decode('utf-8-sig', errors='replace')))
        except ET.ParseError:
            continue
        title = root.get('title')
        if title:
            return title
    return None


def parse_qti_item(xml_content: str, vfs: Dict[str, bytes]) -> Optional[Dict]:
    """Nimmt den ERSTEN Tag aus INTERACTION_TAG_PRIORITY, der im Item vorkommt;
    weitere Interaction-Tags im selben Item werden geloggt und gehen verloren
    (Ausnahme: _JOINTLY_HANDLED_TAGS). Kein Parser akzeptiert das Item oder
    kein bekannter Tag vorhanden → Meldung statt stillem Verwerfen."""
    clean_xml = strip_namespaces(xml_content)
    root = ET.fromstring(clean_xml)
    title = root.get('title', 'Unbenannt')
    max_score = _read_item_max_score(root)

    for tag in INTERACTION_TAG_PRIORITY:
        if root.find(f'.//{tag}') is not None:
            other_tags = [t for t in INTERACTION_TAG_PRIORITY
                          if t != tag and root.find(f'.//{t}') is not None]
            # extendedTextInteraction + uploadInteraction zusammen sind KEIN
            # Datenverlust - siehe _JOINTLY_HANDLED_TAGS - werden also aus der
            # Warnung rausgefiltert.
            if tag in _JOINTLY_HANDLED_TAGS:
                other_tags = [t for t in other_tags if t not in _JOINTLY_HANDLED_TAGS]
            if other_tags:
                print(f"[!] '{title}': Item enthält neben <{tag}> weitere "
                      f"Interaktionen ({', '.join(other_tags)}) – nur <{tag}> "
                      f"wird konvertiert, der Rest geht verloren.")

            for parser_fn in INTERACTION_PARSERS[tag]:
                result = parser_fn(root, vfs)
                if result is not None:
                    result['max_score'] = max_score
                    return result

            print(f"[!] '{title}': <{tag}> erkannt, aber kein Parser hat das Item "
                  f"akzeptiert (z.B. unbekanntes class-Attribut) – übersprungen.")
            return None

    unhandled_tag = _find_unhandled_interaction_tag(root)
    if unhandled_tag:
        print(f"[!] '{title}': Fragetyp <{unhandled_tag}> wird noch nicht "
              f"unterstützt – übersprungen (kein Parser vorhanden).")
    else:
        print(f"[!] '{title}': Keine bekannte oder erkennbare Interaktion "
              f"gefunden – übersprungen.")

    return None


def extract_questions_from_vfs(vfs: Dict[str, bytes]) -> List[Dict]:
    """Prüft jede .xml-Datei (außer imsmanifest.xml) mit is_qti_item() und
    übergibt Treffer an parse_qti_item(); ein Parse-Fehler bei einem Item
    bricht den Lauf nicht ab, sondern wird geloggt. Sortiert die Fragen
    danach nach der assessmentTest-Reihenfolge und setzt 'section_title'
    je Frage (siehe _read_item_layout)."""
    questions = []

    xml_files = {path: data for path, data in vfs.items()
                 if path.endswith('.xml') and 'imsmanifest' not in path.lower()}

    for filepath, data in xml_files.items():
        # utf-8-sig statt utf-8: entfernt ein evtl. vorhandenes BOM am
        # Dateianfang, an dem ET.fromstring sonst scheitern würde.
        content = data.decode('utf-8-sig', errors='replace')

        if not is_qti_item(content):
            continue

        try:
            q_data = parse_qti_item(content, vfs)
            if q_data is not None:
                q_data['_source_file'] = os.path.basename(filepath.split('|')[-1])
                questions.append(q_data)
                print(f"[DEBUG] {q_data['title']} ({q_data['qtype']}) erkannt")
        except Exception as e:
            print(f"[!] Fehler bei '{filepath}': {type(e).__name__}: {e}")

    layout = _read_item_layout(vfs)
    if layout:
        # Fragen ohne Eintrag in der Test-Reihenfolge (sollte es nicht geben)
        # wandern stabil ans Ende, statt zu verschwinden.
        order_index = {item['file']: i for i, item in enumerate(layout)}
        section_by_file = {item['file']: item['section_title'] for item in layout}
        questions.sort(key=lambda item: order_index.get(item.get('_source_file'), len(layout)))
        for q in questions:
            q['section_title'] = section_by_file.get(q.get('_source_file'), '')
    else:
        for q in questions:
            q['section_title'] = ''

    return questions


def _first_question_id(xml_fragment: str) -> Optional[int]:
    """Liest die erste <question id="N"> aus einem generierten Frage-XML als int."""
    m = _QUESTION_ID_RE.search(xml_fragment)
    return int(m.group(1)) if m else None


def _embed_question_images(q: Dict, question_id: Optional[int], context_id: int,
                           file_mgr, now: int) -> None:
    """Moodle hängt Frage-Bilder nicht über einen inforef-Verweis an, sondern
    allein über den files.xml-Eintrag mit component/filearea/itemid=Frage-ID:
      - Fragetext-Bilder:    component='question',       filearea='questiontext'
      - Hotspot-Hintergrund: component='qtype_ddmarker', filearea='bgimage'
    Antwort-Bilder (in einzelnen Optionen) werden noch nicht eingebettet
    (siehe helpers.warn_dropped_files)."""
    if question_id is None or file_mgr is None:
        return

    for f in q.get('text_files') or []:
        try:
            data = base64.b64decode(f['b64'])
        except (ValueError, KeyError):
            continue
        file_mgr.add_moodle_directory(context_id, 'question', 'questiontext', question_id, now)
        file_mgr.add_moodle_file(source_content=data, filename=f['name'], contextid=context_id,
                                 component='question', filearea='questiontext',
                                 itemid=question_id, now=now)

    if q.get('qtype') == 'hotspot' and q.get('image_data') and q.get('image_filename'):
        name = os.path.basename(q['image_filename'])
        file_mgr.add_moodle_directory(context_id, 'qtype_ddmarker', 'bgimage', question_id, now)
        file_mgr.add_moodle_file(source_content=q['image_data'], filename=name, contextid=context_id,
                                 component='qtype_ddmarker', filearea='bgimage',
                                 itemid=question_id, now=now)


def generate_question_categories_xml(questions: List[Dict], id_gen: IdGenerator,
                                     category_name: str, context_id: int,
                                     context_level: int = 70,
                                     context_instance_id: int = 1,
                                     file_mgr=None, now: int = 0):
    """Baut das Kategorie-Paar ('top'-Elternkategorie + echte Kategorie mit den
    Fragen) für EINE Quiz-Aktivität - entspricht dem Aufbau echter Moodle-
    Backups (Referenz-questions.xml: Kategorie id=1 'top' + id=2 als Kind,
    gleiche contextid/contextinstanceid wie die Quiz-Aktivität). Gibt KEINEN
    <question_categories>-Wrapper zurück, main.py fügt mehrere Kategorie-
    Paare zu einer globalen questions.xml zusammen.

    Gibt (XML-Fragment, [top_id, cat_id], Anzahl übersprungener Fragen,
    generierte Fragen mit zusätzlichem Schlüssel 'entry_id') zurück -
    'entry_id' braucht qti_quiz_builder.py, um die Frage als Slot in
    quiz.xml einzuhängen; Cloze-Subquestions tauchen hier nicht auf, sie
    hängen nur über die <sequence> der Elternfrage dran.
    """
    top_id = id_gen.next()
    top_stamp = make_stamp()

    cat_id = id_gen.next()
    cat_stamp = make_stamp()

    entries_xml = []
    skipped = 0
    generated_questions: List[Dict] = []

    for q in questions:
        qtype = q['qtype']

        multi_fn = MULTI_ENTRY_GENERATORS.get(qtype)
        if multi_fn is not None:
            entry_blocks, parent_entry_id = multi_fn(q, id_gen, cat_id)
            entries_xml.extend(entry_blocks)
            generated_questions.append({**q, 'entry_id': parent_entry_id})
            if entry_blocks:
                _embed_question_images(q, _first_question_id(entry_blocks[0]),
                                       context_id, file_mgr, now)
            continue

        generator_fn = GENERATORS.get(qtype)
        if generator_fn is None:
            label = _QTYPE_LABELS.get(qtype, qtype)
            print(f"[!] Fragetyp '{label}' bei '{q['title']}' wird nicht unterstützt – übersprungen.")
            skipped += 1
            continue

        question_xml = generator_fn(q, id_gen)
        entry_xml, entry_id = wrap_question_bank_entry(question_xml, cat_id, id_gen)
        entries_xml.append(entry_xml)
        generated_questions.append({**q, 'entry_id': entry_id})
        _embed_question_images(q, _first_question_id(question_xml),
                               context_id, file_mgr, now)

    entries_block = '\n'.join(entries_xml)

    if skipped:
        print(f"[*] {skipped} Frage(n) mit nicht unterstütztem Fragetyp übersprungen.")

    xml = f"""  <question_category id="{top_id}">
    <name>top</name>
    <contextid>{context_id}</contextid>
    <contextlevel>{context_level}</contextlevel>
    <contextinstanceid>{context_instance_id}</contextinstanceid>
    <info></info>
    <infoformat>0</infoformat>
    <stamp>{top_stamp}</stamp>
    <parent>0</parent>
    <sortorder>0</sortorder>
    <idnumber>$@NULL@$</idnumber>
    <question_bank_entries>
    </question_bank_entries>
  </question_category>
  <question_category id="{cat_id}">
    <name>{html_lib.escape(category_name)}</name>
    <contextid>{context_id}</contextid>
    <contextlevel>{context_level}</contextlevel>
    <contextinstanceid>{context_instance_id}</contextinstanceid>
    <info></info>
    <infoformat>0</infoformat>
    <stamp>{cat_stamp}</stamp>
    <parent>{top_id}</parent>
    <sortorder>999</sortorder>
    <idnumber>$@NULL@$</idnumber>
    <question_bank_entries>
{entries_block}
    </question_bank_entries>
  </question_category>"""

    return xml, [top_id, cat_id], skipped, generated_questions
