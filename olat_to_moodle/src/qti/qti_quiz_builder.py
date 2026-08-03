"""Baut echte Moodle-Quiz-Aktivitäten aus OLAT-Testbausteinen (iqtest/iqself).

Bindeglied zwischen dem Kurs-Konverter (main.py) und der QTI-Fragen-Pipeline
(qti_pipeline.py + qtype_*.py).

Ein iqtest/iqself-CourseNode referenziert sein QTI-2.1-Paket zwar über den
moduleConfiguration-Entry 'repoSoftkey', aufgelöst wird es aber über
manifest.resolve_repo_package() – siehe dort für den 'export/<node-ident>/'-
Mechanismus (identisch für cp-Content-Packages, siehe cp_book_builder.py).

Sonderfall eigenständiges QTI-Testpaket ohne Kurs drumherum (siehe
config.STANDALONE_QTI_IDENT): main.py speist dafür einen synthetischen
Knoten mit diesem ident ein – es gibt dann kein repo.zip, der Export IST
bereits das QTI-Paket, build_quiz_activity() nimmt dann manifest.vfs
unverändert als Fragen-VFS.
"""

import html as html_lib
from typing import Dict, List, Optional, TypedDict

from . import qti_pipeline
from config import HOTSPOT_REGIONS_LOST_MARKER, STANDALONE_QTI_IDENT
from conversion.file_manager import activity_title, escape_xml_text, mark_activity_title

_QUESTIONS_PER_PAGE = 1
_DEFAULT_MAXMARK = "1.0000000"


class QuizActivityResult(TypedDict):
    """Rückgabestruktur von build_quiz_activity() bei Erfolg."""
    quiz_xml: str
    category_entries_xml: str
    category_ids: List[int]


def _build_quiz_sections_xml(question_instances: List[Dict], id_gen) -> str:
    """Moodle-Quiz-Sections sind zusammenhängende Slot-Bereiche mit eigener
    Überschrift (firstslot..nächste Section-1). Aufeinanderfolgende
    question_instances mit demselben section_title bilden eine Section;
    sind bei allen Fragen section_title leer, entsteht automatisch nur
    eine einzige Section ohne Überschrift."""
    blocks = []
    prev_title = None
    for i, qi in enumerate(question_instances, start=1):
        cur_title = qi.get('section_title') or ''
        if i == 1 or cur_title != prev_title:
            sec_id = id_gen.next()
            safe_heading = html_lib.escape(cur_title, quote=False)
            blocks.append(f"""      <section id="{sec_id}">
        <firstslot>{i}</firstslot>
        <heading>{safe_heading}</heading>
        <shufflequestions>0</shufflequestions>
      </section>""")
            prev_title = cur_title
    return '\n'.join(blocks)


def _generate_quiz_xml(quiz_id: int, module_id: int, context_id: int, title: str,
                       now: int, question_instances: List[Dict], id_gen,
                       intro: str = "") -> str:
    """quiz_id = module_id, Moodle braucht hier keine getrennte ID. sumgrades
    ist die Summe aller maxmark-Werte; die übrigen Felder sind feste
    Moodle-Standardwerte aus einer echten Moodle-5.0-Referenz-quiz.xml
    (deferredfeedback als Bewertungsverhalten, freie Navigation)."""
    safe_title = html_lib.escape(title, quote=False)
    sumgrades = sum(float(qi['maxmark']) for qi in question_instances)
    # Moodle rechnet das Ergebnis von sumgrades auf grade um. Beide gleich
    # zu setzen erhält die Punktzahlen aus OLAT – bei festem grade (Moodles
    # Neuanlage-Default 10) erschiene ein 40-Punkte-Test als 'x von 10'.
    quiz_grade = sumgrades if sumgrades > 0 else 10.0
    sections_block = _build_quiz_sections_xml(question_instances, id_gen)

    instance_blocks = []
    for i, qi in enumerate(question_instances, start=1):
        instance_blocks.append(f"""      <question_instance id="{qi['instance_id']}">
        <quizid>{quiz_id}</quizid>
        <slot>{i}</slot>
        <page>{i}</page>
        <displaynumber>$@NULL@$</displaynumber>
        <requireprevious>0</requireprevious>
        <maxmark>{qi['maxmark']}</maxmark>
        <quizgradeitemid>$@NULL@$</quizgradeitemid>
        <question_reference id="{qi['reference_id']}">
          <usingcontextid>{context_id}</usingcontextid>
          <component>mod_quiz</component>
          <questionarea>slot</questionarea>
          <questionbankentryid>{qi['entry_id']}</questionbankentryid>
          <version>$@NULL@$</version>
        </question_reference>
      </question_instance>""")
    instances_block = '\n'.join(instance_blocks)

    # Hinweise einzelner Fragen stehen in der Beschreibung des Tests
    # statt im Fragetext: Moodle zeigt in der Fragenliste Name und
    # Textanfang nebeneinander, dort stünde die Warnung mittendrin.
    safe_intro = escape_xml_text(intro)

    return f"""<activity id="{quiz_id}" moduleid="{module_id}" modulename="quiz" contextid="{context_id}">
  <quiz id="{quiz_id}">
    <name>{safe_title}</name>
    <intro>{safe_intro}</intro>
    <introformat>1</introformat>
    <timeopen>0</timeopen>
    <timeclose>0</timeclose>
    <timelimit>0</timelimit>
    <overduehandling>autosubmit</overduehandling>
    <graceperiod>0</graceperiod>
    <preferredbehaviour>deferredfeedback</preferredbehaviour>
    <canredoquestions>0</canredoquestions>
    <attempts_number>0</attempts_number>
    <attemptonlast>0</attemptonlast>
    <grademethod>1</grademethod>
    <decimalpoints>2</decimalpoints>
    <questiondecimalpoints>-1</questiondecimalpoints>
    <reviewattempt>69888</reviewattempt>
    <reviewcorrectness>4352</reviewcorrectness>
    <reviewmaxmarks>69888</reviewmaxmarks>
    <reviewmarks>4352</reviewmarks>
    <reviewspecificfeedback>4352</reviewspecificfeedback>
    <reviewgeneralfeedback>4352</reviewgeneralfeedback>
    <reviewrightanswer>4352</reviewrightanswer>
    <reviewoverallfeedback>4352</reviewoverallfeedback>
    <questionsperpage>{_QUESTIONS_PER_PAGE}</questionsperpage>
    <navmethod>free</navmethod>
    <shuffleanswers>1</shuffleanswers>
    <sumgrades>{sumgrades:.5f}</sumgrades>
    <grade>{quiz_grade:.5f}</grade>
    <timecreated>{now}</timecreated>
    <timemodified>{now}</timemodified>
    <password></password>
    <subnet></subnet>
    <browsersecurity>-</browsersecurity>
    <delay1>0</delay1>
    <delay2>0</delay2>
    <showuserpicture>0</showuserpicture>
    <showblocks>0</showblocks>
    <completionattemptsexhausted>0</completionattemptsexhausted>
    <completionminattempts>0</completionminattempts>
    <allowofflineattempts>0</allowofflineattempts>
    <precreateattempts>$@NULL@$</precreateattempts>
    <subplugin_quizaccess_seb_quiz>
    </subplugin_quizaccess_seb_quiz>
    <quiz_grade_items>
    </quiz_grade_items>
    <question_instances>
{instances_block}
    </question_instances>
    <sections>
{sections_block}
    </sections>
    <feedbacks>
    </feedbacks>
    <overrides>
    </overrides>
    <grades>
    </grades>
    <attempts>
    </attempts>
  </quiz>
</activity>"""


def build_quiz_activity(node: Dict, manifest, context_id: int, module_id: int,
                        id_gen, now: int, file_mgr=None,
                        report_sink: Optional[List[Dict]] = None) -> Optional[QuizActivityResult]:
    """Baut eine vollständige Quiz-Aktivität mit echten Fragen aus einem
    OLAT-iqtest/iqself-Knoten. id_gen ist der EINE IdGenerator für den
    ganzen Kurslauf, damit über mehrere Tests hinweg keine ID doppelt
    vergeben wird.

    Bricht mit None ab, sobald das Paket nicht auflösbar ist, keine
    unterstützten Fragen gefunden werden, oder alle Fragen ohne Generator
    sind (z.B. eine reine Matrix-Frage) – main.py fällt dann auf die
    generische leere Quiz-Aktivität zurück statt den Kurslauf abzubrechen.

    report_sink (optional): erhält bei JEDEM Ausgang – auch bei None-Rückgabe –
    eine Fragen-Bilanz {title, module_id, resolved, recognized, emitted,
    unsupported} für die spätere Soll-Ist-Validierung (conversion_validator.py).
    'recognized' = von der QTI-Pipeline erkannte Fragen, 'emitted' = tatsächlich
    als Quiz-Slot gebaute, 'unsupported' = ohne Moodle-Äquivalent verworfene
    (z.B. Matrix/Zeichnen – dokumentierter, kein fehlerhafter Verlust).

    Gibt bei Erfolg {"quiz_xml", "category_entries_xml", "category_ids":
    [top_id, cat_id]} zurück, sonst None.
    """
    title = node.get('title', 'Test')

    def _report(resolved: bool, recognized: int, emitted: int, unsupported: int):
        """Meldet die Fragen-Bilanz an report_sink, falls einer übergeben wurde."""
        if report_sink is not None:
            report_sink.append({
                'title': title, 'module_id': module_id, 'resolved': resolved,
                'recognized': recognized, 'emitted': emitted, 'unsupported': unsupported,
            })

    if node.get('ident') == STANDALONE_QTI_IDENT:
        sub_vfs = manifest.vfs
    else:
        sub_vfs = manifest.resolve_repo_package(
            node.get('ident'), 'IMSQTI', 'QTI-Paket', node.get('title'))
        if sub_vfs is None:
            _report(resolved=False, recognized=0, emitted=0, unsupported=0)
            return None

    questions = qti_pipeline.extract_questions_from_vfs(sub_vfs)
    if not questions:
        print(f"[!] '{node.get('title')}': keine unterstützten Fragen im QTI-Paket gefunden.")
        _report(resolved=True, recognized=0, emitted=0, unsupported=0)
        return None

    category_name = f"{node.get('title', 'Test')} – Fragen"
    category_entries_xml, category_ids, skipped, generated_questions = (
        qti_pipeline.generate_question_categories_xml(
            questions, id_gen, category_name=category_name,
            context_id=context_id, context_level=70, context_instance_id=module_id,
            file_mgr=file_mgr, now=now))

    if not generated_questions:
        print(f"[!] '{node.get('title')}': alle {len(questions)} erkannten Fragen ohne "
              f"Generator (z.B. nur Matrix) – Quiz bliebe leer, Fallback auf Leer-Quiz.")
        _report(resolved=True, recognized=len(questions), emitted=0, unsupported=skipped)
        return None

    # Nur bei WIRKLICH mehreren unterschiedlichen Sektionstiteln als
    # Section-Überschriften nutzen – ein einzelner Test hat meist nur einen
    # (oft OLATs Standardtitel "Sektion"), dann soll das Quiz eine einzige
    # Section ohne Überschrift bleiben.
    distinct_titles = {question.get('section_title') for question in generated_questions if question.get('section_title')}
    use_sections = len(distinct_titles) > 1

    question_instances = []
    for question in generated_questions:
        # Echte OLAT-Punktzahl (MAXSCORE) statt Standardwert 1.0, damit die
        # relative Gewichtung erhalten bleibt (z.B. "Frage 3 zählt doppelt").
        max_score = question.get('max_score')
        if isinstance(max_score, (int, float)) and max_score > 0:
            maxmark = f"{max_score:.7f}"
        else:
            maxmark = _DEFAULT_MAXMARK
        question_instances.append({
            'instance_id': id_gen.next(),
            'reference_id': id_gen.next(),
            'entry_id': question['entry_id'],
            'maxmark': maxmark,
            'section_title': question.get('section_title', '') if use_sections else '',
        })

    # Beim Bauen festgestellte Verluste (derzeit nur verworfene Hotspot-
    # Bereiche): Hinweistext in die Beschreibung, Markierung an den Namen –
    # sonst fällt der Test erst nach dem Öffnen als nachbearbeitungswürdig auf.
    notices = [question['activity_notice'] for question in generated_questions
               if question.get('activity_notice')]
    if notices:
        mark_activity_title(node, HOTSPOT_REGIONS_LOST_MARKER)

    quiz_xml = _generate_quiz_xml(
        quiz_id=module_id, module_id=module_id, context_id=context_id,
        title=activity_title(node, 'Test'), now=now,
        question_instances=question_instances, id_gen=id_gen,
        intro="".join(notices))

    if skipped:
        print(f"[*] '{node.get('title')}': {skipped} von {len(questions)} Frage(n) ohne "
              f"Generator (z.B. Matrix) – im Quiz nicht enthalten.")

    _report(resolved=True, recognized=len(questions),
            emitted=len(question_instances), unsupported=skipped)
    return {
        "quiz_xml": quiz_xml,
        "category_entries_xml": category_entries_xml,
        "category_ids": category_ids,
    }
