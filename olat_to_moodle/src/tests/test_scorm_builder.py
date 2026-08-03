"""Tests für scorm_builder.py – vor allem parse_scorm_manifest() (Organizations-/
Resource-Baum zu scorm_scoes-Zeilen), da Moodle diese Struktur beim Restore
unverändert aus der Backup-XML in seine Datenbank übernimmt."""

from conversion.scorm_builder import parse_scorm_manifest, build_scorm_activity


def _manifest_xml(items_xml, resources_xml, manifest_id="MANIFEST-1", org_id="ORG-1",
                  schemaversion=None):
    metadata_xml = (f"<metadata><schema>ADL SCORM</schema>"
                    f"<schemaversion>{schemaversion}</schemaversion></metadata>"
                    if schemaversion else "")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<manifest identifier="{manifest_id}" xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2">
  {metadata_xml}
  <organizations default="{org_id}">
    <organization identifier="{org_id}">
      <title>Organisation</title>
      {items_xml}
    </organization>
  </organizations>
  <resources>
    {resources_xml}
  </resources>
</manifest>"""


def test_single_sco_package_produces_root_plus_one_sco():
    xml = _manifest_xml(
        items_xml='<item identifier="ITEM-1" identifierref="RES-1"><title>Kurs</title></item>',
        resources_xml='<resource identifier="RES-1" type="webcontent" href="index.html" '
                      'adlcp:scormtype="sco"></resource>')
    result = parse_scorm_manifest(xml.encode('utf-8'))
    assert result is not None
    assert result['manifest_identifier'] == "MANIFEST-1"
    assert result['organization_identifier'] == "ORG-1"
    assert len(result['scoes']) == 2

    root, item = result['scoes']
    assert root['parent'] == '/'
    assert root['identifier'] == "ORG-1"
    assert root['launch'] == ''
    assert item['parent'] == "ORG-1"
    assert item['identifier'] == "ITEM-1"
    assert item['launch'] == "index.html"
    assert item['scormtype'] == "sco"
    assert item['title'] == "Kurs"


def test_nested_items_get_correct_parent_chain():
    xml = _manifest_xml(
        items_xml=(
            '<item identifier="PARENT" identifierref="RES-PARENT"><title>Modul 1</title>'
            '<item identifier="CHILD" identifierref="RES-CHILD"><title>Lektion 1</title></item>'
            '</item>'),
        resources_xml=(
            '<resource identifier="RES-PARENT" type="webcontent" href="modul1.html" adlcp:scormtype="sco"></resource>'
            '<resource identifier="RES-CHILD" type="webcontent" href="lektion1.html" adlcp:scormtype="sco"></resource>'))
    result = parse_scorm_manifest(xml.encode('utf-8'))
    by_id = {sco['identifier']: sco for sco in result['scoes']}
    assert by_id['PARENT']['parent'] == "ORG-1"
    assert by_id['CHILD']['parent'] == "PARENT"
    assert by_id['CHILD']['launch'] == "lektion1.html"


def test_item_without_identifierref_is_pure_cluster_node():
    # Ein reiner Navigations-/Ordner-Knoten ohne direktes Lernobjekt – kommt
    # in echten mehrstufigen SCORM-Paketen vor, hat kein eigenes launch.
    xml = _manifest_xml(
        items_xml='<item identifier="CLUSTER"><title>Kapitel</title></item>',
        resources_xml='')
    result = parse_scorm_manifest(xml.encode('utf-8'))
    cluster = result['scoes'][1]
    assert cluster['launch'] == ''
    assert cluster['scormtype'] == 'sco'


def test_schemaversion_decides_scorm_version():
    # Das Datenmodell des Players hängt daran (scorm_12lib.php gegen
    # scorm_13lib.php) – ein 2004-Paket sucht 'API_1484_11' statt 'API'.
    item = '<item identifier="ITEM-1" identifierref="RES-1"><title>Kurs</title></item>'
    resource = '<resource identifier="RES-1" href="index.html" adlcp:scormtype="sco"></resource>'
    versions = {
        None: "SCORM_1.2",
        "1.2": "SCORM_1.2",
        "1.3": "SCORM_1.3",
        "CAM 1.3": "SCORM_1.3",
        "2004 3rd Edition": "SCORM_1.3",
        "2004 4th Edition": "SCORM_1.3",
    }
    for schemaversion, expected in versions.items():
        xml = _manifest_xml(item, resource, schemaversion=schemaversion)
        assert parse_scorm_manifest(xml.encode('utf-8'))['version'] == expected, schemaversion


def test_resource_without_scormtype_attribute_defaults_to_sco():
    xml = _manifest_xml(
        items_xml='<item identifier="ITEM-1" identifierref="RES-1"><title>Kurs</title></item>',
        resources_xml='<resource identifier="RES-1" type="webcontent" href="index.html"></resource>')
    result = parse_scorm_manifest(xml.encode('utf-8'))
    assert result['scoes'][1]['scormtype'] == 'sco'


# --- Absichtlich kaputte/unerwartete Eingaben ---

def test_manifest_without_organizations_returns_none():
    xml = """<?xml version="1.0"?><manifest identifier="M">
      <resources><resource identifier="R" href="x.html"></resource></resources>
    </manifest>"""
    assert parse_scorm_manifest(xml.encode('utf-8')) is None


def test_malformed_xml_returns_none():
    assert parse_scorm_manifest(b"<manifest><organizations>") is None


def test_organizations_without_any_organization_returns_none():
    xml = """<?xml version="1.0"?><manifest identifier="M">
      <organizations></organizations>
    </manifest>"""
    assert parse_scorm_manifest(xml.encode('utf-8')) is None


class FakeScormManifest:
    """Minimaler Manifest-Stub für build_scorm_activity() – liefert das
    entpackte Paket-VFS, ohne ein echtes SCORM-Zip zu entpacken."""

    def __init__(self, sub_vfs):
        self._sub_vfs = sub_vfs

    def resolve_repo_package(self, ident, resource_type_marker, package_label, node_title=None):
        return self._sub_vfs


def _node(ident="42", title="SCORM-Test"):
    return {"ident": ident, "title": title}


def test_build_scorm_activity_returns_none_when_package_not_resolvable():
    fake = FakeScormManifest(sub_vfs=None)
    assert build_scorm_activity(_node(), fake, context_id=1, module_id=1, now=1700000000) is None


def test_build_scorm_activity_returns_none_without_imsmanifest():
    fake = FakeScormManifest(sub_vfs={"index.html": b"<html></html>"})
    assert build_scorm_activity(_node(), fake, context_id=1, module_id=1, now=1700000000) is None


def test_build_scorm_activity_builds_valid_xml_and_registers_package():
    manifest_xml = _manifest_xml(
        items_xml='<item identifier="ITEM-1" identifierref="RES-1"><title>Kurs</title></item>',
        resources_xml='<resource identifier="RES-1" type="webcontent" href="index.html" '
                      'adlcp:scormtype="sco"></resource>').encode('utf-8')
    fake = FakeScormManifest(sub_vfs={"imsmanifest.xml": manifest_xml})

    result = build_scorm_activity(_node(title="Mein SCORM-Paket"), fake, context_id=5, module_id=42, now=1700000000)

    assert result is not None
    assert result['package_filename'] == "scorm_42.zip"

    import xml.etree.ElementTree as ET
    root = ET.fromstring(result['scorm_xml'])
    assert root.get('modulename') == 'scorm'
    scorm = root.find('scorm')
    assert scorm.findtext('reference') == "scorm_42.zip"
    # Activity-Feld 'launch' ist die numerische ID des Standard-SCO, kein
    # Dateiname (siehe scorm_builder.py-Kommentar) – id=1 ist die Organization-
    # Wurzelzeile, id=2 der erste echte SCO.
    assert scorm.findtext('launch') == "2"
    assert scorm.findtext('completionstatusrequired') == "$@NULL@$"
    assert scorm.findtext('completionscorerequired') == "$@NULL@$"
    scoes = scorm.findall('.//sco')
    assert len(scoes) == 2
    # Der Dateiname selbst steht nur auf SCO-Ebene.
    assert scoes[1].findtext('launch') == "index.html"
    # Moodle lehnt bei lokal gespeicherten Paketen jeden anderen Wert ab
    # (siehe scorm_builder.py-Moduldocstring).
    assert scorm.findtext('updatefreq') == "0"


def test_build_scorm_activity_extracts_content_files_for_every_package_file():
    manifest_xml = _manifest_xml(
        items_xml='<item identifier="ITEM-1" identifierref="RES-1"><title>Kurs</title></item>',
        resources_xml='<resource identifier="RES-1" type="webcontent" href="index.html" '
                      'adlcp:scormtype="sco"></resource>').encode('utf-8')
    fake = FakeScormManifest(sub_vfs={
        "imsmanifest.xml": manifest_xml,
        "index.html": b"<html></html>",
        "mobile/bild.jpg": b"\xff\xd8\xff",
        "mobile/": b"",
        "": b"",
    })

    result = build_scorm_activity(_node(), fake, context_id=5, module_id=42, now=1700000000)

    by_name = {(content_file['relpath'], content_file['name']): content_file for content_file in result['content_files']}
    assert set(by_name.keys()) == {
        ("", "imsmanifest.xml"),
        ("", "index.html"),
        ("mobile", "bild.jpg"),
    }
    assert by_name[("mobile", "bild.jpg")]['data'] == b"\xff\xd8\xff"


def test_default_launch_skips_cluster_node_without_own_file():
    # Erstes Item ist ein reiner Ordner-Knoten – Moodle nimmt als Standard-SCO
    # den ersten Eintrag MIT Startdatei, sonst startet die Aktivität ins Leere.
    manifest_xml = _manifest_xml(
        items_xml=('<item identifier="CLUSTER"><title>Kapitel</title>'
                   '<item identifier="ITEM-1" identifierref="RES-1"><title>Kurs</title></item>'
                   '</item>'),
        resources_xml='<resource identifier="RES-1" href="index.html" '
                      'adlcp:scormtype="sco"></resource>').encode('utf-8')
    fake = FakeScormManifest(sub_vfs={"imsmanifest.xml": manifest_xml})

    result = build_scorm_activity(_node(), fake, context_id=5, module_id=42, now=1700000000)

    import xml.etree.ElementTree as ET
    scorm = ET.fromstring(result['scorm_xml']).find('scorm')
    # id=1 Organization, id=2 Cluster (ohne launch), id=3 der echte SCO.
    assert scorm.findtext('launch') == "3"


def test_package_is_repacked_from_anonymized_entries_and_is_deterministic():
    # sanitize_vfs() bereinigt nur die entpackten Textdateien, nicht den
    # Zip-Blob – das Paket muss deshalb aus den VFS-Einträgen neu entstehen.
    manifest_xml = _manifest_xml(
        items_xml='<item identifier="ITEM-1" identifierref="RES-1"><title>Kurs</title></item>',
        resources_xml='<resource identifier="RES-1" href="index.html" '
                      'adlcp:scormtype="sco"></resource>').encode('utf-8')
    fake = FakeScormManifest(sub_vfs={
        "imsmanifest.xml": manifest_xml,
        "index.html": b"<html>bereinigt</html>",
        "mobile/bild.jpg": b"\xff\xd8\xff",
    })

    result = build_scorm_activity(_node(), fake, context_id=5, module_id=42, now=1700000000)

    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(result['package_bytes'])) as zf:
        assert sorted(zf.namelist()) == ["imsmanifest.xml", "index.html", "mobile/bild.jpg"]
        assert zf.read("index.html") == b"<html>bereinigt</html>"

    # Gleiche Eingabe, gleiches Zip – sonst greift die Inhalts-Dedup in
    # file_manager.py bei jedem Lauf daneben.
    again = build_scorm_activity(_node(), fake, context_id=5, module_id=42, now=1700009999)
    assert again['package_bytes'] == result['package_bytes']


def test_nested_zip_in_package_is_repacked_not_flattened():
    # CourseManifest legt ein Zip im Paket doppelt ab: als Datei und flach
    # entpackt unter '<zip>|<pfad>' – die '|'-Einträge dürfen nicht als eigene
    # Dateien durchrutschen.
    manifest_xml = _manifest_xml(
        items_xml='<item identifier="ITEM-1" identifierref="RES-1"><title>Kurs</title></item>',
        resources_xml='<resource identifier="RES-1" href="index.html" '
                      'adlcp:scormtype="sco"></resource>').encode('utf-8')
    fake = FakeScormManifest(sub_vfs={
        "imsmanifest.xml": manifest_xml,
        "index.html": b"<html></html>",
        "material/anhang.zip": b"PK\x03\x04original",
        "material/anhang.zip|inhalt.html": b"<html>bereinigt</html>",
    })

    result = build_scorm_activity(_node(), fake, context_id=5, module_id=42, now=1700000000)

    names = {(content_file['relpath'], content_file['name']) for content_file in result['content_files']}
    assert names == {("", "imsmanifest.xml"), ("", "index.html"), ("material", "anhang.zip")}

    import io
    import zipfile
    nested = next(content_file for content_file in result['content_files'] if content_file['name'] == "anhang.zip")
    with zipfile.ZipFile(io.BytesIO(nested['data'])) as zf:
        assert zf.namelist() == ["inhalt.html"]
        assert zf.read("inhalt.html") == b"<html>bereinigt</html>"
