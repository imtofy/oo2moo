"""Tests für die Erkennung und Vererbung von OLATs Passwort-Bedingung.

OLAT schreibt das PasswordCondition-Element für JEDEN Knoten mit, auch für
ungeschützte – erst ein <password> mit Inhalt darin bedeutet echten Schutz.
Diese Unterscheidung ist der Kern der Prüfung; ohne sie wäre jeder Baustein
des Kurses als passwortgeschützt markiert."""

import xml.etree.ElementTree as ET

from conversion.node_processor import with_password_warning
from conversion.olat_parser import _walk_tree, PASSWORD_CONDITION_CLASS

_CONDITION_WITHOUT_PASSWORD = f"""<additionalConditions>
  <{PASSWORD_CONDITION_CLASS}>
    <expertMode>false</expertMode>
  </{PASSWORD_CONDITION_CLASS}>
</additionalConditions>"""


def _condition_with(password):
    return f"""<additionalConditions>
      <{PASSWORD_CONDITION_CLASS}>
        <expertMode>false</expertMode>
        <password>{password}</password>
      </{PASSWORD_CONDITION_CLASS}>
    </additionalConditions>"""


def _wrapper(ident, node_type, title, condition_xml="", children_xml=""):
    return ET.fromstring(f"""<org.olat.course.tree.CourseEditorTreeNode>
      <cn class="org.olat.course.nodes.{node_type}CourseNode">
        <ident>{ident}</ident>
        <shortTitle>{title}</shortTitle>
        {condition_xml}
      </cn>
      <children>{children_xml}</children>
    </org.olat.course.tree.CourseEditorTreeNode>""")


def _walk(elem):
    nodes = []
    _walk_tree(elem, [], nodes, [])
    return nodes


def test_condition_element_without_password_is_not_protection():
    nodes = _walk(_wrapper("1", "SP", "Offen", _CONDITION_WITHOUT_PASSWORD))
    assert nodes[0]['defines_password'] is False
    assert nodes[0]['password_protected'] is False


def test_node_without_any_condition_is_not_protected():
    nodes = _walk(_wrapper("1", "SP", "Offen"))
    assert nodes[0]['defines_password'] is False
    assert nodes[0]['password_protected'] is False


def test_empty_password_element_is_not_protection():
    nodes = _walk(_wrapper("1", "SP", "Offen", _condition_with("   ")))
    assert nodes[0]['defines_password'] is False


def test_password_is_detected_on_the_node_that_sets_it():
    nodes = _walk(_wrapper("1", "ST", "Geschützt", _condition_with("geheim")))
    assert nodes[0]['defines_password'] is True
    assert nodes[0]['password_protected'] is True


def test_protection_is_inherited_by_the_whole_subtree():
    # In OLAT gilt die Bedingung eines Struktur-Bausteins für alles darunter,
    # ohne dass die Kinder sie selbst noch einmal führen.
    grandchild = _wrapper("3", "SP", "Enkel")
    child = _wrapper("2", "ST", "Kind", children_xml=ET.tostring(grandchild, encoding="unicode"))
    root = _wrapper("1", "ST", "Geschützt", _condition_with("geheim"),
                    children_xml=ET.tostring(child, encoding="unicode"))

    by_title = {n['title']: n for n in _walk(root)}

    assert [n['password_protected'] for n in by_title.values()] == [True, True, True]
    # Der Hinweistext gehört nur an den Knoten, der das Passwort gesetzt hat.
    assert by_title['Geschützt']['defines_password'] is True
    assert by_title['Kind']['defines_password'] is False
    assert by_title['Enkel']['defines_password'] is False


def test_sibling_outside_the_protected_branch_stays_open():
    protected = _wrapper("2", "ST", "Geschützt", _condition_with("geheim"))
    sibling = _wrapper("3", "SP", "Daneben")
    root = _wrapper("1", "ST", "Wurzel", children_xml=(
        ET.tostring(protected, encoding="unicode") + ET.tostring(sibling, encoding="unicode")))

    by_title = {n['title']: n for n in _walk(root)}

    assert by_title['Geschützt']['password_protected'] is True
    assert by_title['Daneben']['password_protected'] is False
    assert by_title['Wurzel']['password_protected'] is False


def test_warning_is_added_only_for_the_node_that_sets_the_password():
    assert with_password_warning("<p>Inhalt</p>", {'defines_password': False}) == "<p>Inhalt</p>"
    with_warning = with_password_warning("<p>Inhalt</p>", {'defines_password': True})
    assert with_warning.endswith("<p>Inhalt</p>")
    assert "Passwort" in with_warning


def test_warning_survives_an_empty_description():
    # Ein Struktur-Baustein ohne eigene Beschreibung darf den Hinweis
    # trotzdem bekommen – sonst verschwindet er genau dort, wo nichts
    # anderes auf den Verlust hinweist.
    assert with_password_warning("", {'defines_password': True}).startswith("<p")
