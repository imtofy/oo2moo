"""Tests für olat_parser.py – insbesondere has_children (leeres <children/>
vs. echte Kind-Elemente) und die Tiefenbegrenzung/flattened-Vererbung, da
beides an OLATs XML-Eigenheiten hängt und leicht wieder falsch werden kann."""

import xml.etree.ElementTree as ET

from conversion.olat_parser import _walk_tree, _extract_node_fields, _build_url_from_parts, parse_olat_export


def _wrapper(ident, node_type, title, children_xml=""):
    """Baut einen <org.olat.course.tree.CourseEditorTreeNode>-Wrapper mit
    <cn>+<children>, wie ihn OLATs editortreemodel.xml tatsächlich schreibt –
    <children> steht IMMER da, auch leer als Self-Closing-Tag."""
    xml = f"""<org.olat.course.tree.CourseEditorTreeNode>
      <cn class="org.olat.course.nodes.{node_type}CourseNode">
        <ident>{ident}</ident>
        <shortTitle>{title}</shortTitle>
      </cn>
      <children>{children_xml}</children>
    </org.olat.course.tree.CourseEditorTreeNode>"""
    return ET.fromstring(xml)


def test_empty_children_element_means_has_children_false():
    elem = _wrapper("1", "SP", "Blattknoten")
    nodes, deleted = [], []
    _walk_tree(elem, [], nodes, deleted)
    assert nodes[0]['has_children'] is False


def test_children_with_real_content_means_has_children_true():
    inner = """<org.olat.course.tree.CourseEditorTreeNode>
      <cn class="org.olat.course.nodes.SPCourseNode">
        <ident>2</ident><shortTitle>Kind</shortTitle>
      </cn>
      <children></children>
    </org.olat.course.tree.CourseEditorTreeNode>"""
    elem = _wrapper("1", "SP", "Elternknoten", children_xml=inner)
    nodes, deleted = [], []
    _walk_tree(elem, [], nodes, deleted)
    assert nodes[0]['has_children'] is True
    assert nodes[1]['title'] == 'Kind'
    assert nodes[1]['parent_st_idents'] == ['1']


def test_node_beyond_max_depth_gets_flattened_and_children_inherit_it():
    # Drei has_children-Ebenen tief – MAX_SECTION_DEPTH=2 erlaubt genau zwei
    # echte Verschachtelungen (Ebene1 als Section, Ebene2 als Subsection,
    # Ebene3 selbst liegt noch genau auf der Grenze und bleibt gültig
    # platziert) – erst DEREN Kinder (eine vierte Ebene) können keinen
    # weiteren Container mehr bekommen und werden 'flattened'.
    level3 = """<org.olat.course.tree.CourseEditorTreeNode>
      <cn class="org.olat.course.nodes.STCourseNode">
        <ident>3</ident><shortTitle>Ebene3</shortTitle>
      </cn>
      <children>
        <org.olat.course.tree.CourseEditorTreeNode>
          <cn class="org.olat.course.nodes.SPCourseNode">
            <ident>4</ident><shortTitle>KindVonEbene3</shortTitle>
          </cn>
          <children></children>
        </org.olat.course.tree.CourseEditorTreeNode>
      </children>
    </org.olat.course.tree.CourseEditorTreeNode>"""
    level2 = f"""<org.olat.course.tree.CourseEditorTreeNode>
      <cn class="org.olat.course.nodes.STCourseNode">
        <ident>2</ident><shortTitle>Ebene2</shortTitle>
      </cn>
      <children>{level3}</children>
    </org.olat.course.tree.CourseEditorTreeNode>"""
    root = _wrapper("1", "ST", "Ebene1", children_xml=level2)

    nodes, deleted = [], []
    _walk_tree(root, [], nodes, deleted)

    by_title = {n['title']: n for n in nodes}
    assert by_title['Ebene1']['flattened'] is False
    assert by_title['Ebene2']['flattened'] is False
    assert by_title['Ebene3']['flattened'] is False
    assert by_title['Ebene3']['parent_st_idents'] == ['1', '2']
    assert by_title['KindVonEbene3']['flattened'] is True


def test_node_without_any_title_lands_in_deleted_nodes():
    # _walk_tree selbst filtert nicht – das übernimmt main.py über
    # deleted_nodes. Ein <cn> ohne shortTitle/longTitle gehört dort hinein.
    elem = ET.fromstring("""<org.olat.course.tree.CourseEditorTreeNode>
      <cn class="org.olat.course.nodes.SPCourseNode"><ident>1</ident></cn>
      <children></children>
    </org.olat.course.tree.CourseEditorTreeNode>""")
    nodes, deleted = [], []
    _walk_tree(elem, [], nodes, deleted)
    assert nodes == []
    assert deleted[0]['reason'] == 'Element ist unbenannt'


def test_node_actually_named_unbenannt_is_kept():
    # 'Unbenannt' ist ein zulässiger, vom Autor vergebener Name und darf nicht
    # mit dem Ersatzwert für "kein Titel" verwechselt werden – sonst fliegt der
    # Baustein mit raus.
    elem = _wrapper("1", "SP", "Unbenannt")
    nodes, deleted = [], []
    _walk_tree(elem, [], nodes, deleted)
    assert [n['title'] for n in nodes] == ['Unbenannt']
    assert deleted == []


def test_participant_list_is_recognised_by_type_not_by_name():
    # Erkennung allein über den Bausteintyp: ein gleichnamiger, inhaltlich
    # anderer Baustein darf nicht mitverworfen werden.
    nodes, deleted = [], []
    _walk_tree(_wrapper("1", "Members", "Wer ist dabei?"), [], nodes, deleted)
    assert nodes == []
    assert deleted[0]['reason'] == 'Teilnehmerliste wird nicht übernommen'

    nodes, deleted = [], []
    _walk_tree(_wrapper("2", "SP", "Liste der Teilnehmer:innen"), [], nodes, deleted)
    assert [n['title'] for n in nodes] == ['Liste der Teilnehmer:innen']
    assert deleted == []


def test_extract_node_fields_prefers_learning_objectives_over_description():
    xml = """<cn class="org.olat.course.nodes.STCourseNode">
      <ident>1</ident>
      <shortTitle>Test</shortTitle>
      <learningObjectives>Lernziele-Text</learningObjectives>
      <description>Beschreibung-Text</description>
    </cn>"""
    cn = ET.fromstring(xml)
    _, _, fields = _extract_node_fields(cn)
    assert fields['description'] == 'Lernziele-Text'


def test_extract_node_fields_falls_back_to_description_when_no_learning_objectives():
    xml = """<cn class="org.olat.course.nodes.STCourseNode">
      <ident>1</ident>
      <shortTitle>Test</shortTitle>
      <description>Beschreibung-Text</description>
    </cn>"""
    cn = ET.fromstring(xml)
    _, _, fields = _extract_node_fields(cn)
    assert fields['description'] == 'Beschreibung-Text'


def test_extract_node_fields_prefers_short_title_over_long_title():
    xml = """<cn class="org.olat.course.nodes.SPCourseNode">
      <ident>1</ident>
      <shortTitle>Kurz</shortTitle>
      <longTitle>Lang</longTitle>
    </cn>"""
    cn = ET.fromstring(xml)
    title, _, _ = _extract_node_fields(cn)
    assert title == 'Kurz'


def test_build_url_from_parts_omits_default_https_port():
    url = _build_url_from_parts({'proto': 'https', 'host': 'example.com', 'port': '443', 'uri': '/pfad'})
    assert url == 'https://example.com/pfad'


def test_build_url_from_parts_keeps_nonstandard_port():
    url = _build_url_from_parts({'proto': 'https', 'host': 'example.com', 'port': '8443'})
    assert url == 'https://example.com:8443'


def test_parse_olat_export_missing_file_returns_empty_lists():
    nodes, deleted = parse_olat_export(r'C:\pfad\der\nicht\existiert.zip')
    assert nodes == []
    assert deleted == []


# --- Absichtlich kaputte/unerwartete Eingaben (Fehlerbehandlung) ---

def test_parse_olat_export_corrupt_zip_does_not_raise(tmp_path):
    # Datei existiert, ist aber gar kein ZIP – darf main.py nicht mit einer
    # Exception abschießen, sondern soll (leer, aber gültig) zurückgeben.
    broken = tmp_path / "kaputt.zip"
    broken.write_bytes(b"Das ist kein ZIP-Archiv, nur irgendein Text.")
    nodes, deleted = parse_olat_export(str(broken))
    assert nodes == []
    assert deleted == []


def test_parse_olat_export_zip_without_editortreemodel_returns_empty_lists(tmp_path):
    # Gültiges ZIP, aber ohne die erwartete editortreemodel.xml (z.B. ein
    # falsch ausgewähltes Export-ZIP) – soll leer zurückgeben, nicht abstürzen.
    import zipfile
    zip_path = tmp_path / "ohne_treemodel.zip"
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr("irgendeine_andere_datei.txt", "Inhalt")
    nodes, deleted = parse_olat_export(str(zip_path))
    assert nodes == []
    assert deleted == []


def test_extract_node_fields_without_titles_returns_none_as_title():
    # <cn> ganz ohne shortTitle/longTitle – title muss None sein (nicht ein
    # Anzeigetext, der sich nicht von einem echten Titel unterscheiden ließe)
    # statt eine Exception zu werfen.
    cn = ET.fromstring('<cn class="org.olat.course.nodes.STCourseNode"></cn>')
    title, node_type, fields = _extract_node_fields(cn)
    assert title is None
    assert node_type == 'st'
    assert fields['description'] == ''


def test_walk_tree_wrapper_without_cn_element_is_skipped_gracefully():
    # <children> ohne jedes <...CourseNode>-Kind (z.B. durch OLAT-Exportfehler) –
    # darf nicht crashen, produziert keinen Knoten.
    elem = ET.fromstring("<org.olat.course.tree.CourseEditorTreeNode><children></children>"
                         "</org.olat.course.tree.CourseEditorTreeNode>")
    nodes, deleted = [], []
    _walk_tree(elem, [], nodes, deleted)
    assert nodes == []
    assert deleted == []
