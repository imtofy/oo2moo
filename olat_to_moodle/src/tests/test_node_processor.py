"""Tests für build_node_content() - insbesondere die Trennung von Beschreibung
und Seiteninhalt bei m_type='page' (Info-Block vs. Content, siehe main.py)."""

from conversion.node_processor import build_node_content


class FakeManifest:
    """Minimaler Manifest-Stub - liefert genau das, was ein Test braucht,
    ohne ein echtes OLAT-ZIP zu entpacken."""

    def __init__(self, html_files=None, node_assets=("", []), folder_tree=([], [])):
        self._html_files = html_files or {}
        self._node_assets = node_assets
        self._folder_tree = folder_tree

    def search_file(self, path, base_path=None):
        return self._html_files.get(path)

    def get_node_assets(self, ident):
        return self._node_assets

    def search_directory(self, rel_path):
        return []

    def get_node_folder_tree(self, ident):
        return self._folder_tree


def _base_node(**overrides):
    node = {
        'title': 'Testknoten', 'ident': '1', 'html_file': '', 'rel_path': '',
        'description': '',
    }
    node.update(overrides)
    return node


def test_page_type_separates_description_from_content():
    node = _base_node(
        description='<p>Kurzbeschreibung</p>',
        html_file='seite.html',
    )
    manifest = FakeManifest(html_files={
        'seite.html': {'path': 'export/1/seite.html', 'data': b'<p>Echter Inhalt</p>'},
    })
    html, _, _, _, _, description_html = build_node_content(node, manifest, "page", "sp")
    assert 'Kurzbeschreibung' in description_html
    assert 'Kurzbeschreibung' not in html
    assert 'Echter Inhalt' in html


def test_non_page_type_keeps_description_merged_into_content():
    node = _base_node(description='<p>Nur Titel als Text</p>')
    manifest = FakeManifest()
    html, _, _, _, _, description_html = build_node_content(node, manifest, "label", "cal")
    assert description_html == ""
    assert 'Nur Titel als Text' in html


def test_missing_referenced_file_sets_content_issue_and_visible_warning():
    node = _base_node(html_file='fehlt.html')
    manifest = FakeManifest(html_files={})  # Datei nicht im Archiv
    html, _, _, _, content_issue, _ = build_node_content(node, manifest, "page", "sp")
    assert content_issue == "Referenzierte Datei fehlt"
    assert 'nicht gefunden' in html


def test_video_without_html_content_gets_auto_generated_video_tag():
    node = _base_node()
    manifest = FakeManifest(node_assets=("", [{"name": "clip.mp4", "data": b"fake"}]))
    html, _, _, _, _, _ = build_node_content(node, manifest, "page", "video")
    assert '<video' in html
    assert '@@PLUGINFILE@@/clip.mp4' in html


def test_folder_type_uses_folder_tree_not_node_assets():
    node = _base_node()
    manifest = FakeManifest(
        node_assets=("sollte nicht verwendet werden", [{"name": "sollte-nicht-auftauchen.txt", "data": b""}]),
        folder_tree=([{"name": "echte-datei.txt", "relpath": "", "data": b"x"}], ["leerer_unterordner"]),
    )
    html, attachments, _, empty_dirs, _, _ = build_node_content(node, manifest, "folder", "bc")
    names = {a["name"] for a in attachments}
    assert "echte-datei.txt" in names
    assert "sollte-nicht-auftauchen.txt" not in names
    assert empty_dirs == ["leerer_unterordner"]


def test_no_description_no_content_yields_empty_strings():
    node = _base_node()
    manifest = FakeManifest()
    html, attachments, removed_links, empty_dirs, content_issue, description_html = build_node_content(
        node, manifest, "page", "sp")
    assert html == ""
    assert description_html == ""
    assert content_issue is None
    assert attachments == []
    assert removed_links == []
    assert empty_dirs == []
