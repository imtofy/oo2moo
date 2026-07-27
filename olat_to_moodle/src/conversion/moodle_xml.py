"""Patcht die aus dem Moodle-Template kopierten Aktivitäts-XMLs mit echten Werten.

main.py kopiert für jede Aktivität ein passendes Template aus Files\\
moodle_musterkurs und ruft danach die Funktionen hier auf, um die
Platzhalter-IDs/Inhalte des Templates durch die tatsächlichen Werte des
OLAT-Knotens zu ersetzen.
"""

import xml.etree.ElementTree as ET
from config import OLAT_NAMES


def modify_module_xml(filepath: str, module_id: int, section_id: int, now: int):
    """Setzt Modul-ID, Section-Zugehörigkeit und Erstellzeitpunkt in module.xml."""
    tree = ET.parse(filepath)
    root = tree.getroot()
    root.set('id', str(module_id))

    section_node = root.find('sectionid')
    if section_node is not None:
        section_node.text = str(section_id)

    added_node = root.find('added')
    if added_node is not None:
        added_node.text = str(now)

    tree.write(filepath, encoding='utf-8', xml_declaration=True)


def modify_subsection_xml(filepath: str, subsection_instance_id: int, module_id: int,
                          context_id: int, title: str, now: int):
    """subsection_instance_id ist die eigene ID der subsection-Instanz, NICHT
    die course_modules-ID - verknüpft den zugehörigen Kind-Abschnitt über
    dessen <itemid>, siehe xml_generator.generate_section_xml.

    Das äußere <activity id="..."> muss subsection_instance_id sein (nicht
    module_id!) - ein echter Moodle-Export (Files/moodle_musterkurs) zeigt
    <activity id="708" moduleid="215149"><subsection id="708">, also id ==
    der Instanz-ID der subsection, moduleid separat die course_modules-ID.
    Mit id==module_id (der ursprüngliche Bug hier) findet Moodles Restore
    beim Auflösen von section.xml's <itemid> keine passende Aktivität mehr -
    die Sektion verliert ihre Verknüpfung und landet als leerer, nicht
    zugeordneter "Neuer Abschnitt" im Kurs, bei jedem Unterabschnitt."""
    tree = ET.parse(filepath)
    root = tree.getroot()
    root.set('id', str(subsection_instance_id))
    root.set('moduleid', str(module_id))
    root.set('contextid', str(context_id))

    sub_node = root.find('subsection')
    if sub_node is not None:
        sub_node.set('id', str(subsection_instance_id))
        name_node = sub_node.find('name')
        if name_node is not None:
            name_node.text = title
        time_node = sub_node.find('timemodified')
        if time_node is not None:
            time_node.text = str(now)

    tree.write(filepath, encoding='utf-8', xml_declaration=True)


def modify_activity_xml(filepath: str, modulename: str, module_id: int, context_id: int,
                        title: str, now: int, original_olat_type: str, is_fallback: bool,
                        html_content: str, node_url: str = ""):
    """Füllt die aktivitätsspezifische XML (z.B. page.xml) mit dem konvertierten Inhalt.

    title muss roh/unescaped übergeben werden - ElementTree escaped beim
    Schreiben selbst, manuelles Vorab-Escaping würde & → &amp;amp; doppeln.
    Eine frische <revision> bei page/resource/folder zwingt Moodle, Dateien
    nach dem Restore sofort neu aufzulösen (sonst erscheint ein Bild teils
    erst nach einmal Öffnen+Speichern). is_fallback stellt einen rot
    hervorgehobenen Warnhinweis voran. modulename='page' schreibt in
    <content> statt <intro>, alle anderen Typen ins <intro>-Feld.
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    root.set('id', str(module_id))
    root.set('moduleid', str(module_id))
    root.set('contextid', str(context_id))

    module_node = root.find(modulename)
    if module_node is not None:
        module_node.set('id', str(module_id))

        name_node = module_node.find('name')
        if name_node is not None:
            name_node.text = title

        time_node = module_node.find('timemodified')
        if time_node is not None:
            time_node.text = str(now)

        revision_node = module_node.find('revision')
        if revision_node is not None:
            revision_node.text = str(now)

        olat_name = OLAT_NAMES.get(original_olat_type, original_olat_type)

        clean_html = html_content if html_content else ""

        if is_fallback:
            fallback_warning = (
                f'<p style="color:red;"><strong>Achtung:</strong> Dieser Bausteintyp '
                f'({olat_name}) wurde nicht automatisch erkannt – der Inhalt wurde '
                f'trotzdem übernommen, bitte einmal prüfen.</p>'
            )
            final_content = f'{fallback_warning}{clean_html}'
        else:
            final_content = clean_html

        if modulename == 'url':
            url_node = module_node.find('externalurl')
            if url_node is None:
                url_node = ET.SubElement(module_node, 'externalurl')
            # example.invalid statt einer echten Domain: 'example' + die TLD
            # '.invalid' sind beide nach RFC 2606 von der IANA für genau
            # diesen Zweck reserviert - garantiert nie auflösbar, anders als
            # z.B. platzhalter.de (eine echte, erreichbare Domain).
            url_node.text = node_url if node_url else "http://example.invalid/"

        if modulename == 'page':
            content_node = module_node.find('content')
            if content_node is not None:
                content_node.text = final_content

            intro_node = module_node.find('intro')
            if intro_node is not None:
                intro_node.text = ""
        else:
            intro_node = module_node.find('intro')
            if intro_node is not None:
                intro_node.text = final_content

    tree.write(filepath, encoding='utf-8', xml_declaration=True)


def set_forum_announcement_type(filepath: str):
    """Macht aus der kopierten forum.xml eine Moodle-"Ankündigungen"-Aktivität
    (type='news', forcesubscribe=2) - für OLATs 'info'-Baustein (Mitteilungen),
    der über dasselbe Forum-Template wie ein normales Forum läuft."""
    tree = ET.parse(filepath)
    root = tree.getroot()
    forum_node = root.find('forum')
    if forum_node is not None:
        type_node = forum_node.find('type')
        if type_node is not None:
            type_node.text = 'news'
        subscribe_node = forum_node.find('forcesubscribe')
        if subscribe_node is not None:
            subscribe_node.text = '2'
    tree.write(filepath, encoding='utf-8', xml_declaration=True)


def rewrite_inforef_xml(filepath: str, file_ids: list, question_category_ids: list | None = None):
    """question_category_ids (nur bei Quiz-Aktivitäten: [top_id, cat_id] aus
    qti_quiz_builder.build_quiz_activity) verknüpft die questions.xml-
    Kategorien mit dieser Aktivität - ohne das findet Moodle beim Restore
    die zugehörigen Fragen nicht."""
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<inforef>\n'
    if file_ids:
        xml += '  <fileref>\n'
        for fid in file_ids:
            xml += f'    <file>\n      <id>{fid}</id>\n    </file>\n'
        xml += '  </fileref>\n'
    if question_category_ids:
        xml += '  <question_categoryref>\n'
        for cat_id in question_category_ids:
            xml += f'    <question_category>\n      <id>{cat_id}</id>\n    </question_category>\n'
        xml += '  </question_categoryref>\n'
    xml += '</inforef>'

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(xml)
