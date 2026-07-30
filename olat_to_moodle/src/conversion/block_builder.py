"""Baut echte Moodle-Block-Instanzen (course/blocks/...) für OLAT-Bausteine
ohne Aktivitäts-Äquivalent, aber mit einem passenden Moodle-Block.

Ein Block ist strukturell etwas anderes als eine Aktivität: er hängt nicht in
der Sequenz einer Section, sondern liegt kursweit in der Seitenleiste
(defaultregion='side-pre'), unabhängig von seiner Position im OLAT-Baum.
Schema gegen einen echten Moodle-5.2-Export verifiziert (course/blocks/
calendar_month_<id>/block.xml eines Kurses, dem der Kalender-Block manuell
hinzugefügt und wieder exportiert wurde).

Bisher einziger Fall: OLATs 'cal'-Baustein (Kalender) hat kein Aktivitäts-
Äquivalent, aber Moodles eingebauter 'calendar_month'-Block zeigt denselben
Monatskalender.
"""


def build_calendar_block_xml(block_id: int, context_id: int, now: int) -> str:
    """Baut block.xml für einen Moodle 'calendar_month'-Block.

    parentcontextid ist immer 1 (Kurs-Kontext) - der Block hängt am Kurs
    selbst, nicht an einer bestimmten Aktivität oder Section."""
    return f"""<block id="{block_id}" contextid="{context_id}" version="2025041400">
  <blockname>calendar_month</blockname>
  <parentcontextid>1</parentcontextid>
  <showinsubcontexts>0</showinsubcontexts>
  <pagetypepattern>course-view-*</pagetypepattern>
  <subpagepattern>$@NULL@$</subpagepattern>
  <defaultregion>side-pre</defaultregion>
  <defaultweight>0</defaultweight>
  <configdata></configdata>
  <timecreated>{now}</timecreated>
  <timemodified>{now}</timemodified>
  <block_positions>
  </block_positions>
</block>"""
