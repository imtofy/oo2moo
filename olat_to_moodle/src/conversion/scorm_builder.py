"""Baut eine echte Moodle-SCORM-Aktivität (mod_scorm) aus einem OLAT-scorm-Baustein.

mod_scorm ist Core-Bestandteil von Moodle (kein Plugin nötig, anders als H5P/
LTI) – ein OLAT-SCORM-Baustein referenziert sein Paket genau wie Wiki/CP über
'export/<ident>/repo.zip', aufgelöst über manifest.resolve_repo_package().
Das Paket selbst ist ein Standard-SCORM-Zip (imsmanifest.xml im Wurzelpfad).
Es wird aus den entpackten VFS-Einträgen neu gepackt statt als Originalblob
durchgereicht, weil anonymizer.sanitize_vfs() nur die entpackten Textdateien
bereinigt – der Originalblob enthielte sonst weiterhin die echten
Nutzerkennungen.

Moodles Restore liest die <scoes>-Liste direkt aus der Backup-XML statt das
Paket selbst zu parsen (siehe restore_scorm_stepslib.php) – die Struktur wird
deshalb hier aus dem Paket-eigenen imsmanifest.xml abgeleitet (organizations/
item-Baum + resources-Zuordnung), nach demselben Organizations-Prinzip wie
IMS-CP (siehe cp_book_builder.py), nur mit SCORM-eigenen Zusatzfeldern
(scormtype sco/asset, Startdatei). Abgedeckt ist der weit überwiegende
Praxisfall (ein Organization-Baum, flache oder wenig verschachtelte Items) –
komplexes Sequencing (seq_ruleconds etc.) wird nicht nachgebildet.

Moodles eigener Reparse-Schritt nach dem Restore (scorm_parse() im
"schnellen" Modus, siehe restore_scorm_activity_structure_step::
after_execute()) befüllt den content-Dateibereich bei größeren Paketen nicht
zuverlässig, obwohl die <scoes>-Struktur korrekt angelegt wird. 'updatefreq'
als Schalter für einen erzwungenen vollen Reparse scheidet aus, weil er bei
lokal gespeicherten Paketen laut Moodles eigener Formular-Validierung nur 0
sein darf (mod_form.php). Deshalb registriert dieser Code jede Datei aus dem
Paket direkt selbst unter component=mod_scorm/filearea=content – genau wie es
ein aus Moodle selbst exportiertes Backup auch tut (siehe
backup_scorm_stepslib.php: annotate_files('mod_scorm', 'content', null)). Der
Restore hängt damit nicht von Moodles eigenem Reparse-Schritt ab."""

import hashlib
import html as html_lib
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List, Optional, TypedDict

from .file_manager import activity_title, escape_xml_text

# Feste Zeitmarke für alle Einträge des neu gepackten Pakets – dieselbe
# Eingabe ergibt so immer dasselbe Zip, sonst würde die Inhalts-Dedup in
# file_manager.py bei jedem Lauf einen anderen Hash sehen. 1980-01-01 ist
# die kleinste vom Zip-Format darstellbare Zeit.
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class ScormActivityResult(TypedDict):
    """Rückgabeform von build_scorm_activity() bei Erfolg – als TypedDict
    statt eines nackten Dict, damit main.py beim Zugriff auf die einzelnen
    Schlüssel keine falschen None-Typwarnungen bekommt."""
    scorm_xml: str
    package_filename: str
    package_bytes: bytes
    content_files: List[Dict]


def _local(tag: str) -> str:
    """Strippt einen XML-Namespace von einem Tag-/Attributnamen ('{ns}foo' -> 'foo') –
    SCORM-1.2- und SCORM-2004-Pakete nutzen unterschiedliche Namespace-URIs für
    dieselben Elemente, der lokale Name bleibt aber gleich."""
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _attr(elem: ET.Element, name: str) -> Optional[str]:
    """Attributzugriff über den lokalen Namen, unabhängig vom Namespace-Präfix
    (adlcp:scormtype hat je nach Paket eine andere volle URI)."""
    for key, value in elem.attrib.items():
        if _local(key) == name:
            return value
    return None


def _child_text(elem: ET.Element, name: str) -> str:
    for child in elem:
        if _local(child.tag) == name:
            return (child.text or '').strip()
    return ''


def _scorm_version(root: ET.Element) -> str:
    """Leitet Moodles 'version'-Feld aus <schemaversion> im Manifest ab.

    Davon hängt ab, welches Datenmodell der Player lädt (scorm_12lib.php
    gegen scorm_13lib.php) – ein SCORM-2004-Paket sucht 'API_1484_11' und
    findet unter SCORM_1.2 nur 'API', kann also nicht mit Moodle
    kommunizieren. Dieselbe Zuordnung wie Moodle selbst, siehe
    mod/scorm/datamodels/scormlib.php: '1.3'/'CAM 1.3' und '2004 3rd/4th
    Edition' sind SCORM_1.3, alles andere SCORM_1.2."""
    for elem in root.iter():
        if _local(elem.tag) != 'schemaversion':
            continue
        value = (elem.text or '').strip()
        if re.match(r'^(CAM )?1\.3$', value) or re.match(r'^2004 (3rd|4th) Edition$', value):
            return 'SCORM_1.3'
        break
    return 'SCORM_1.2'


def _pack_files(files: List[Dict]) -> bytes:
    """Packt eine Dateiliste (siehe _collect_package_files) in ein Zip."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for entry in files:
            arcname = f"{entry['relpath']}/{entry['name']}" if entry['relpath'] else entry['name']
            info = zipfile.ZipInfo(arcname, date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, entry['data'])
    return buffer.getvalue()


def _collect_package_files(entries: Dict[str, bytes]) -> List[Dict]:
    """Flache Dateiliste eines Pakets: [{'name', 'relpath', 'data'}, ...].

    Ein Zip im Paket liegt im VFS doppelt vor: als Datei selbst und flach
    entpackt unter '<zip>|<pfad>' (siehe CourseManifest). Die '|'-Einträge
    sind keine eigenen Dateien und werden deshalb nicht als solche übernommen
    – stattdessen wird das Zip aus ihnen neu gepackt, damit auch sein Inhalt
    anonymisiert ist (siehe Moduldocstring)."""
    files = []
    for relkey, data in entries.items():
        if not relkey or relkey.endswith('/') or '|' in relkey:
            continue
        dirpath, _, filename = relkey.rpartition('/')
        if not filename:
            continue
        if filename.lower().endswith('.zip'):
            nested_prefix = relkey + '|'
            nested = {key[len(nested_prefix):]: value for key, value in entries.items()
                      if key.startswith(nested_prefix)}
            if nested:
                data = _pack_files(_collect_package_files(nested))
        files.append({"name": filename, "relpath": dirpath, "data": data})
    return files


def _parse_resources(root: ET.Element) -> Dict[str, Dict[str, str]]:
    """resources/resource -> {identifier: {'href', 'scormtype'}}."""
    resources = {}
    for elem in root.iter():
        if _local(elem.tag) != 'resource':
            continue
        identifier = _attr(elem, 'identifier')
        if not identifier:
            continue
        resources[identifier] = {
            'href': _attr(elem, 'href') or '',
            'scormtype': (_attr(elem, 'scormtype') or 'sco').lower(),
        }
    return resources


def _walk_items(item_elem: ET.Element, parent_identifier: str, resources: Dict[str, Dict[str, str]],
                counter: List[int], scoes: List[Dict]) -> None:
    """Läuft den <item>-Baum in Dokumentreihenfolge ab und hängt für jedes Item
    eine sco-Zeile an scoes an – counter[0] liefert eine fortlaufende
    sortorder über den gesamten Baum hinweg (Liste statt int, weil Python
    Closures keine äußeren Zahlen per Referenz ändern können)."""
    for child in item_elem:
        if _local(child.tag) != 'item':
            continue
        identifier = _attr(child, 'identifier') or ''
        identifierref = _attr(child, 'identifierref')
        title = _child_text(child, 'title') or identifier
        resource = resources.get(identifierref) if identifierref else None

        counter[0] += 1
        scoes.append({
            'parent': parent_identifier,
            'identifier': identifier,
            'launch': resource['href'] if resource else '',
            'scormtype': resource['scormtype'] if resource else 'sco',
            'title': title,
            'sortorder': counter[0],
        })
        _walk_items(child, identifier, resources, counter, scoes)


def parse_scorm_manifest(manifest_bytes: bytes) -> Optional[Dict]:
    """Parst imsmanifest.xml eines SCORM-Pakets zur Organizations-/Resource-
    Struktur. Gibt None zurück, wenn kein <organizations>-Baum vorhanden ist
    (z.B. reine AICC-artige Pakete ohne Navigationsstruktur) – der Aufrufer
    fällt dann auf die generische, leere SCORM-Aktivität zurück.

    Gibt {'manifest_identifier', 'organization_identifier',
    'organization_title', 'version', 'scoes': [...]} zurück – scoes[0] ist
    immer die Organization selbst (parent='/', launch='', scormtype='sco'),
    siehe Moduldocstring."""
    try:
        root = ET.fromstring(manifest_bytes)
    except ET.ParseError:
        return None

    manifest_identifier = root.get('identifier') or ''
    resources = _parse_resources(root)

    organizations_elem = None
    for child in root:
        if _local(child.tag) == 'organizations':
            organizations_elem = child
            break
    if organizations_elem is None:
        return None

    default_org_id = organizations_elem.get('default')
    org_elem = None
    for child in organizations_elem:
        if _local(child.tag) != 'organization':
            continue
        if org_elem is None:
            org_elem = child
        if default_org_id and child.get('identifier') == default_org_id:
            org_elem = child
            break
    if org_elem is None:
        return None

    org_identifier = org_elem.get('identifier') or manifest_identifier
    org_title = _child_text(org_elem, 'title') or org_identifier

    scoes = [{
        'parent': '/', 'identifier': org_identifier, 'launch': '',
        'scormtype': 'sco', 'title': org_title, 'sortorder': 1,
    }]
    counter = [1]
    _walk_items(org_elem, org_identifier, resources, counter, scoes)

    return {
        'manifest_identifier': manifest_identifier,
        'organization_identifier': org_identifier,
        'organization_title': org_title,
        'version': _scorm_version(root),
        'scoes': scoes,
    }


def _sco_xml(sco_id: int, manifest_identifier: str, organization_identifier: str, sco: Dict) -> str:
    safe_title = escape_xml_text(sco['title'])
    safe_launch = html_lib.escape(sco['launch'])
    return f"""      <sco id="{sco_id}">
        <manifest>{html_lib.escape(manifest_identifier)}</manifest>
        <organization>{html_lib.escape(organization_identifier)}</organization>
        <parent>{html_lib.escape(sco['parent'])}</parent>
        <identifier>{html_lib.escape(sco['identifier'])}</identifier>
        <launch>{safe_launch}</launch>
        <scormtype>{sco['scormtype']}</scormtype>
        <title>{safe_title}</title>
        <sortorder>{sco['sortorder']}</sortorder>
        <sco_datas>
        </sco_datas>
        <seq_ruleconds>
        </seq_ruleconds>
        <seq_rolluprules>
        </seq_rolluprules>
        <seq_objectives>
        </seq_objectives>
        <sco_tracks>
        </sco_tracks>
      </sco>"""


def build_scorm_activity(node, manifest, context_id: int, module_id: int,
                         now: int) -> Optional[ScormActivityResult]:
    """Baut eine vollständige SCORM-Aktivität aus einem OLAT-scorm-Knoten.

    Bricht mit None ab, wenn das Paket nicht auflösbar ist oder dessen
    imsmanifest.xml keinen Organizations-Baum enthält – main.py fällt dann
    auf die generische, leere SCORM-Aktivität zurück statt den Kurslauf
    abzubrechen."""
    ident = node.get('ident')
    sub_vfs = manifest.resolve_repo_package(ident, 'SCORM', 'SCORM-Paket', node.get('title'))
    if sub_vfs is None:
        return None

    manifest_bytes = sub_vfs.get('imsmanifest.xml')
    if manifest_bytes is None:
        print(f"[!] '{node.get('title')}': imsmanifest.xml nicht im SCORM-Paket gefunden.")
        return None

    parsed = parse_scorm_manifest(manifest_bytes)
    if parsed is None:
        print(f"[!] '{node.get('title')}': imsmanifest.xml hat keinen "
              f"<organizations>-Baum, SCORM-Struktur nicht ableitbar.")
        return None

    # Jede Datei im Paket wird 1:1 unter component=mod_scorm/filearea=content
    # registriert (siehe Moduldocstring) – relpath erhält die Unterordner-
    # struktur (z.B. Bilder unter 'mobile/'), main.py legt dafür dieselben
    # Verzeichnis-Marker an wie bei anderen Datei-Anhängen. Aus derselben
    # Liste entsteht auch die 'package'-Zipdatei.
    content_files = _collect_package_files(sub_vfs)
    package_bytes = _pack_files(content_files)
    package_filename = f"scorm_{module_id}.zip"

    sco_count = len(parsed['scoes']) - 1  # ohne die Organization-Wurzelzeile
    print(f"[*] '{node.get('title')}': SCORM-Paket erkannt und übernommen "
          f"({sco_count} Lerneinheit(en), {len(content_files)} Datei(en)).")

    sco_blocks = [_sco_xml(i + 1, parsed['manifest_identifier'], parsed['organization_identifier'], sco)
                 for i, sco in enumerate(parsed['scoes'])]
    scoes_xml = "\n".join(sco_blocks)

    safe_name = escape_xml_text(activity_title(node, 'SCORM-Paket'))
    sha1hash = hashlib.sha1(package_bytes).hexdigest()

    # Activity-Feld 'launch' ist bei Moodle KEIN Dateiname, sondern die
    # numerische ID des Standard-SCO (siehe mod/scorm/datamodels/scormlib.php,
    # $scorm->launch = $sco->id) – scorm_scoes.launch (pro SCO) ist dagegen
    # der echte Dateiname. sco_blocks vergibt lokale IDs 1..N in Dokument-
    # reihenfolge; Moodle nimmt davon den ersten SCO mit gesetzter Startdatei,
    # überspringt also die Organization-Wurzelzeile und reine Cluster-/Ordner-
    # Knoten (Items ohne identifierref).
    default_sco_id = next((idx + 1 for idx, sco in enumerate(parsed['scoes']) if sco['launch']), 0)

    scorm_xml = f"""<activity id="{module_id}" moduleid="{module_id}" modulename="scorm" contextid="{context_id}">
  <scorm id="{module_id}">
    <name>{safe_name}</name>
    <scormtype>local</scormtype>
    <reference>{html_lib.escape(package_filename)}</reference>
    <intro></intro>
    <introformat>1</introformat>
    <version>{parsed['version']}</version>
    <maxgrade>100</maxgrade>
    <grademethod>1</grademethod>
    <whatgrade>0</whatgrade>
    <maxattempt>0</maxattempt>
    <forcecompleted>0</forcecompleted>
    <forcenewattempt>0</forcenewattempt>
    <lastattemptlock>0</lastattemptlock>
    <masteryoverride>1</masteryoverride>
    <displayattemptstatus>1</displayattemptstatus>
    <displaycoursestructure>1</displaycoursestructure>
    <updatefreq>0</updatefreq>
    <sha1hash>{sha1hash}</sha1hash>
    <md5hash></md5hash>
    <revision>1</revision>
    <launch>{default_sco_id}</launch>
    <skipview>0</skipview>
    <hidebrowse>0</hidebrowse>
    <hidetoc>0</hidetoc>
    <nav>1</nav>
    <navpositionleft>-100</navpositionleft>
    <navpositiontop>-100</navpositiontop>
    <auto>0</auto>
    <popup>0</popup>
    <options></options>
    <width>100</width>
    <height>500</height>
    <timeopen>0</timeopen>
    <timeclose>0</timeclose>
    <timemodified>{now}</timemodified>
    <completionstatusrequired>$@NULL@$</completionstatusrequired>
    <completionscorerequired>$@NULL@$</completionscorerequired>
    <completionstatusallscos>0</completionstatusallscos>
    <autocommit>0</autocommit>
    <scoes>
{scoes_xml}
    </scoes>
  </scorm>
</activity>"""

    return {"scorm_xml": scorm_xml, "package_filename": package_filename,
            "package_bytes": package_bytes, "content_files": content_files}
