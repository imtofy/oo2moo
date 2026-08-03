"""Tests für SectionBuilder – Section-/Subsection-/Sammel-Bucket-Verwaltung
für einen einzelnen Kurslauf (main.py legt pro Aufruf eine neue Instanz an)."""

import os

from conversion.section_builder import SectionBuilder


def _make_template_dir(tmp_path):
    """Baut ein minimales 'subsection'-Template (module.xml + subsection.xml),
    wie main.py es aus Files/moodle_musterkurs kopiert."""
    template_dir = tmp_path / "template" / "subsection"
    template_dir.mkdir(parents=True)
    (template_dir / "module.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<module id="0"><sectionid>0</sectionid><added>0</added></module>', encoding='utf-8')
    (template_dir / "subsection.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<activity id="0" moduleid="0" contextid="0">'
        '<subsection id="0"><name></name><timemodified>0</timemodified></subsection>'
        '</activity>', encoding='utf-8')
    return {"subsection": str(template_dir)}


def _builder(tmp_path):
    (tmp_path / "temp").mkdir()
    return SectionBuilder(str(tmp_path / "temp"), _make_template_dir(tmp_path), now=1700000000)


def _node(ident="1", title="Testknoten"):
    return {"ident": ident, "title": title}


def test_resolve_target_section_with_no_parents_creates_bucket(tmp_path):
    sb = _builder(tmp_path)
    section_id = sb.resolve_target_section([])
    assert sb.sections[section_id]['title'].startswith("📌")
    assert "#1" in sb.sections[section_id]['title']


def test_resolve_target_section_reuses_same_bucket_until_reset(tmp_path):
    sb = _builder(tmp_path)
    first = sb.resolve_target_section([])
    second = sb.resolve_target_section([])
    assert first == second


def test_open_top_section_resets_bucket_so_next_loose_item_gets_new_number(tmp_path):
    sb = _builder(tmp_path)
    bucket1 = sb.resolve_target_section([])
    sb.open_top_section(_node(ident="99", title="Kommunikation"))
    bucket2 = sb.resolve_target_section([])
    assert bucket1 != bucket2
    assert "#2" in sb.sections[bucket2]['title']


def test_resolve_target_section_with_known_parent_returns_mapped_section(tmp_path):
    sb = _builder(tmp_path)
    section_id = sb.open_top_section(_node(ident="42", title="Kommunikation"))
    resolved = sb.resolve_target_section(["42"])
    assert resolved == section_id


def test_resolve_target_section_with_unknown_parent_falls_back_to_bucket(tmp_path):
    sb = _builder(tmp_path)
    resolved = sb.resolve_target_section(["nicht-existierender-ident"])
    assert sb.sections[resolved]['title'].startswith("📌")


def test_open_top_section_numbers_start_at_zero(tmp_path):
    # Slot 0 ist Moodles zwingende "Allgemeines"-Section – die erste im
    # Kurslauf erzeugte Section muss diese Nummer bekommen.
    sb = _builder(tmp_path)
    first_id = sb.open_top_section(_node(ident="1", title="Erste Struktur"))
    assert first_id == 0


def test_set_section_summary_writes_into_existing_section(tmp_path):
    sb = _builder(tmp_path)
    section_id = sb.open_top_section(_node())
    sb.set_section_summary(section_id, "<p>Beschreibung</p>")
    assert sb.sections[section_id]['summary'] == "<p>Beschreibung</p>"


def test_append_module_adds_to_sequence(tmp_path):
    sb = _builder(tmp_path)
    section_id = sb.open_top_section(_node())
    sb.append_module(section_id, 5)
    sb.append_module(section_id, 6)
    assert sb.sections[section_id]['module_ids'] == [5, 6]


def test_create_section_is_independent_of_open_top_section_numbering(tmp_path):
    sb = _builder(tmp_path)
    sb.open_top_section(_node(ident="1"))
    protocol_id = sb.create_section("Systemprotokoll (Konvertierung)")
    assert sb.sections[protocol_id]['title'] == "Systemprotokoll (Konvertierung)"
    assert protocol_id == 1  # direkt nach der ersten Section (Nummer 0)


def test_open_subsection_for_real_st_node_keeps_plain_title(tmp_path):
    sb = _builder(tmp_path)
    new_id, parent_id, subsection_title = sb.open_subsection(
        node=_node(ident="5", title="Verschachtelte Struktur"), node_title="Verschachtelte Struktur",
        olat_type="st", parent_st_idents=[], subsection_module_id=100, context_id=200)
    assert subsection_title == "Verschachtelte Struktur"
    assert sb.sections[new_id]['component'] == 'mod_subsection'
    assert sb.sections[new_id]['modname'] == 'subsection'


def test_open_subsection_for_non_st_node_gets_unterabschnitt_prefix(tmp_path):
    sb = _builder(tmp_path)
    new_id, parent_id, subsection_title = sb.open_subsection(
        node=_node(ident="6", title="Einzelne HTML-Seite"), node_title="Einzelne HTML-Seite",
        olat_type="sp", parent_st_idents=[], subsection_module_id=101, context_id=201)
    assert subsection_title == 'UNTERABSCHNITT: "Einzelne HTML-Seite"'


def test_open_subsection_registers_module_in_parent_section(tmp_path):
    sb = _builder(tmp_path)
    new_id, parent_id, _ = sb.open_subsection(
        node=_node(ident="7"), node_title="Kind", olat_type="sp",
        parent_st_idents=[], subsection_module_id=102, context_id=202)
    assert 102 in sb.sections[parent_id]['module_ids']


def test_open_subsection_writes_real_files_to_disk(tmp_path):
    sb = _builder(tmp_path)
    sb.open_subsection(
        node=_node(ident="8"), node_title="Kind", olat_type="sp",
        parent_st_idents=[], subsection_module_id=103, context_id=203)
    sub_dir = os.path.join(sb.temp_dir, "activities", "subsection_103")
    assert os.path.exists(os.path.join(sub_dir, "module.xml"))
    assert os.path.exists(os.path.join(sb.temp_dir, "contexts", "context_203", "context.xml"))
