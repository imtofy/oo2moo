"""Liest die Kursstruktur eines OLAT-Exports aus editortreemodel.xml aus.

Ein OLAT-Export enthält im Wurzel-ZIP eine editortreemodel.xml mit dem
kompletten Kursbaum (Abschnitte + Bausteine als CourseNode-Elemente). Dieses
Modul wandelt sie in eine flache Liste von Knoten-Dicts um, die main.py der
Reihe nach in Moodle-Aktivitäten übersetzt.
"""

import os
import zipfile
import xml.etree.ElementTree as etree
from typing import List, Dict, Tuple


def _is_course_node(elem) -> bool:
    """Prüft, ob ein XML-Element ein OLAT-Kursbaustein (CourseNode) ist."""
    return 'CourseNode' in str(elem.tag) or 'CourseNode' in str(elem.get('class', ''))


def _build_url_from_parts(parts: Dict[str, str]) -> str:
    """Baut aus proto/host/port/uri/query eine vollständige URL zusammen -
    'tu'-Knoten (Externe Seite) speichern ihre Adresse in OLAT zerlegt statt
    als fertigen String. Standardport 80/443 wird weggelassen (redundant)."""
    proto = parts.get('proto', 'https')
    host = parts.get('host', '')
    port = parts.get('port')
    uri = parts.get('uri', '')
    query = parts.get('query')

    url = f"{proto}://{host}"
    default_port = '443' if proto == 'https' else '80'
    if port and port != default_port:
        url += f":{port}"
    if uri:
        url += uri if uri.startswith('/') else f"/{uri}"
    if query:
        url += f"?{query}"
    return url


def _iter_own_entries(elem):
    """Liefert alle <entry>-Elemente EINES Knotens in Dokumentreihenfolge, steigt
    dabei aber NICHT in verschachtelte CourseNode-Elemente (Kind-Bausteine) ab -
    ein einfaches elem.iter('entry') würde sonst deren Konfiguration mit
    einsammeln, und Eltern-Knoten würden fälschlich html_file/rel_path/url
    ihrer Kinder erben (letzter Wert gewinnt beim Auslesen)."""
    for child in elem:
        if _is_course_node(child):
            continue
        if child.tag == 'entry':
            yield child
        yield from _iter_own_entries(child)


def _entry_key_value(entry):
    """Liest Schlüssel/Wert eines <entry>-Elements aus (Schlüssel immer <string>,
    Wert je nach Typ <string>/<int>/<null/>). Geht positionell über die
    beiden Kind-Elemente, damit auch <int>/<null/>-Werte (z.B. 'port',
    'query') erfasst werden - ein reines list(entry.iter('string')) würde
    die sonst übersehen. (key, val) mit val=None bei <null/>."""
    children = list(entry)
    if len(children) < 2:
        return None, None
    key = children[0].text
    val_elem = children[1]
    val = None if val_elem.tag == 'null' else val_elem.text
    return key, val


# Moodle bildet Kurshierarchien nur zweistufig ab (Abschnitt + EIN Level
# Unterabschnitt, siehe mod_subsection) - eine dritte OLAT-Strukturebene
# ließe sich nicht mehr als eigene Ebene darstellen und wird daher
# stattdessen dem tiefsten noch unterstützten Abschnitt zugeschlagen.
MAX_SECTION_DEPTH = 2


def _extract_node_fields(cn_elem) -> Tuple[str, str, Dict]:
    """Liest Titel/Typ/Inhaltsquellen EINES <cn>-Elements aus (ohne Verschachtelung).

    Gibt (title, node_type, node_dict_ohne_ident) zurück - ident/section-
    Zugehörigkeit ergänzt der Aufrufer (_walk_tree)."""
    cls = str(cn_elem.get('class', ''))

    title = 'Unbenannt'
    short_elem = cn_elem.find('shortTitle')
    long_elem = cn_elem.find('longTitle')
    if short_elem is not None and short_elem.text and short_elem.text.strip():
        title = short_elem.text.strip()
    elif long_elem is not None and long_elem.text and long_elem.text.strip():
        title = long_elem.text.strip()

    node_type = 'st'
    if cls:
        class_name = cls.split('.')[-1]
        if class_name.endswith('CourseNode'):
            node_type = class_name.replace('CourseNode', '').lower()

    html_file = ""
    rel_path = ""
    node_url = ""
    repo_softkey = ""
    qti_type = ""
    # 'tu'-Knoten (Externe Seite) speichern ihre Ziel-Adresse NICHT als
    # einzelnen 'url'-Schlüssel, sondern in proto/host/port/uri/query
    # zerlegt (siehe _build_url_from_parts weiter oben).
    url_parts = {}

    for entry in _iter_own_entries(cn_elem):
        key, val = _entry_key_value(entry)

        if key in ['file', 'doc.course.folder']:
            if val and val != 'None':
                html_file = val
        elif key in ['relPath', 'subPath', 'folderPath', 'config.subpath']:
            if val and val != 'None':
                rel_path = val
        elif key in ['url', 'reference', 'target', 'extlink']:
            if val and val != 'None':
                node_url = val
        elif key in ['proto', 'host', 'port', 'uri', 'query']:
            if val and val != 'None':
                url_parts[key] = val
        elif key == 'repoSoftkey':
            if val and val != 'None':
                repo_softkey = val
        elif key == 'qtitype':
            if val and val != 'None':
                qti_type = val

    if not node_url and url_parts.get('host'):
        node_url = _build_url_from_parts(url_parts)

    # Je nach OLAT-Version/Bausteinklasse heißt das Beschreibungsfeld
    # 'learningObjectives' ODER 'description' (unterschiedliche
    # CourseNode-Klassen, gleiche Bedeutung) - beide prüfen.
    description = ""
    for desc_tag in ('learningObjectives', 'description'):
        desc_elem = cn_elem.find(desc_tag)
        if desc_elem is not None and desc_elem.text and desc_elem.text.strip():
            description = desc_elem.text.strip()
            break

    return title, node_type, {
        'html_file': html_file,
        'rel_path': rel_path,
        'url': node_url,
        'repo_softkey': repo_softkey,
        'qti_type': qti_type,
        'description': description,
    }


def _walk_tree(tree_elem, st_chain: List[str], nodes: List[Dict], deleted_nodes: List[Dict],
              flattened: bool = False):
    """Durchläuft die editortreemodel.xml rekursiv über die echte <children>-
    Verschachtelung (st_chain = Idents der umschließenden STCourseNode-Knoten,
    äußerster zuerst, auf MAX_SECTION_DEPTH gedeckelt).

    Ein flacher root.iter()-Durchlauf würde nur die Dokumentreihenfolge
    kennen, aber nicht wissen, welcher Baustein innerhalb welches
    Struktur-Knotens liegt - die echte Verschachtelung ist hier deshalb
    nötig. Jeder Knoten bekommt 'parent_st_idents' mit - main.py nutzt das,
    um OLATs Abschnitts-Verschachtelung als Moodle-Abschnitt/Unterabschnitt
    abzubilden, statt jede STCourseNode blind als weiteren flachen
    Abschnitt zu behandeln.

    flattened=True bedeutet: irgendein Vorfahre dieses Knotens war bereits
    ein zu tief verschachtelter Container-Knoten (siehe MAX_SECTION_DEPTH
    unten) - main.py markiert solche Knoten im Kurs sichtbar (ℹ️), damit
    klar bleibt, dass sie ursprünglich zu einem jetzt "hochgezogenen"
    Abschnitt gehörten. Bleibt für den ganzen Teilbaum True, sobald einmal
    gesetzt - auch mehrfach verschachtelte zu tiefe Abschnitte "vererben" es.

    Eine neue Ebene öffnet nicht nur 'st' (reiner Struktur-Container ohne
    eigenen Inhalt), sondern jeder Knotentyp mit echten Kind-Elementen im
    <children>-Element der rohen XML - so kann z.B. eine Einzelseite (sp)
    mit angehängtem Forum im Baum als aufklappbarer Elternknoten erscheinen.
    'has_children' wird pro Knoten mit rausgegeben, main.py braucht das, um
    zu wissen, ob ein Knoten (zusätzlich zu seiner eigenen Aktivität) auch
    einen Unterabschnitt für seine Kinder aufmacht.
    """
    cn = None
    for child in tree_elem:
        if _is_course_node(child):
            cn = child
            break

    next_chain = st_chain
    next_flattened = flattened
    if cn is not None:
        ident_elem = cn.find('ident')
        if ident_elem is not None and ident_elem.text:
            ident = ident_elem.text.strip()
        else:
            ident = cn.get('ident', 'unknown')

        title, node_type, fields = _extract_node_fields(cn)

        if title == 'Unbenannt':
            deleted_nodes.append({'title': title, 'type': node_type, 'reason': 'Element ist unbenannt',
                                   'ident': ident, 'parent_st_idents': list(st_chain)})
        elif node_type in ('members', 'cmembers') or title == 'Liste der Teilnehmer:innen':
            deleted_nodes.append({'title': title, 'type': node_type,
                                   'reason': 'Teilnehmerliste wird nicht übernommen',
                                   'ident': ident, 'parent_st_idents': list(st_chain)})
        else:
            # OLAT schreibt für JEDEN Knoten ein <children>-Element, auch
            # ohne echte Kinder (dann als leeres Self-Closing-Tag
            # '<children/>') - find() findet das Tag so oder so, deshalb
            # zusätzlich prüfen, ob wirklich Kind-Elemente drinstehen.
            children_tag = tree_elem.find('children')
            has_children = children_tag is not None and len(children_tag) > 0
            nodes.append({
                'title': title,
                'type': node_type,
                'ident': ident,
                'parent_st_idents': list(st_chain),
                'flattened': flattened,
                'has_children': has_children,
                **fields,
            })
            if has_children:
                if len(st_chain) < MAX_SECTION_DEPTH:
                    next_chain = st_chain + [ident]
                else:
                    next_flattened = True

    children_elem = tree_elem.find('children')
    if children_elem is not None:
        for child_wrapper in children_elem:
            _walk_tree(child_wrapper, next_chain, nodes, deleted_nodes, next_flattened)


def parse_olat_export(olat_zip_path: str) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Parst einen OLAT-Export und gibt (gültige Knoten, verworfene Knoten) zurück.

    Sucht die editortreemodel.xml im ZIP, entfernt XML-Namespaces und
    durchläuft den Baum rekursiv ab rootNode/children (siehe _walk_tree).
    repo_softkey/qti_type sind nur bei Test-Bausteinen (iqtest/iqself)
    gesetzt - die eigentliche Paketauflösung (auch für cp/Content-Package)
    läuft aber über 'ident' und manifest.resolve_repo_package(), nicht über
    repo_softkey. parent_st_idents sind leer, wenn ein Knoten direkt unter
    dem Kurswurzelknoten liegt.

    Unbenannte Knoten und die OLAT-Teilnehmerliste (Typ 'members', auch
    'cmembers') werden als 'verworfener Knoten' mit Grund zurückgegeben,
    damit main.py sie im Systemprotokoll sichtbar machen kann statt sie
    stillschweigend zu verschlucken.
    """
    nodes = []
    deleted_nodes = []

    if not os.path.exists(olat_zip_path):
        print(f"[Fehler] Datei {olat_zip_path} existiert nicht.")
        return nodes, deleted_nodes

    try:
        with zipfile.ZipFile(olat_zip_path, 'r') as zip_ref:
            tree_files = [f for f in zip_ref.namelist() if f.endswith('editortreemodel.xml')]
            if tree_files:
                with zip_ref.open(tree_files[0]) as f:
                    tree = etree.parse(f)
                    root = tree.getroot()
                    for elem in root.iter():
                        if '}' in elem.tag:
                            elem.tag = elem.tag.split('}', 1)[1]
                    root_node = root.find('rootNode')
                    if root_node is not None:
                        children_elem = root_node.find('children')
                        if children_elem is not None:
                            for child_wrapper in children_elem:
                                _walk_tree(child_wrapper, [], nodes, deleted_nodes)
    except Exception as e:
        print(f"[Fehler] Fehler beim Parsen der ZIP: {e}")

    return nodes, deleted_nodes
