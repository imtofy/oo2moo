"""Tests für den sichtbaren Hinweis bei verworfenen Hotspot-Bereichen.

Moodles ddmarker kennt keine Distraktor-Zonen: jede Drop-Zone braucht einen
zugehörigen Marker, eine Zone ohne Marker wäre unerreichbar. Die falschen
Bereiche einer OLAT-Hotspot-Frage lassen sich deshalb nicht übernehmen – die
Frage bleibt lösbar und wird korrekt bewertet, verliert aber ihre Ablenker.

Markierung und Hinweis gehören deshalb in den Kurs selbst, nicht nur ins
Konvertierungsprotokoll: nach dem Import ist sonst nirgends erkennbar, dass
die Frage in OLAT mehr Bereiche hatte."""

from config import HOTSPOT_MIN_RADIUS, HOTSPOT_REGIONS_LOST_MARKER
from qti.helpers import IdGenerator
from qti.qtype_hotspot import generate_hotspot_xml


def _question(region_count, correct_count=1):
    return {
        'title': "Hotspot-Frage",
        'text': "<p>Wählen Sie die Brille.</p>",
        'image_data': b"bilddaten",
        'image_filename': "foto.jpg",
        'regions': [
            {'shape': "circle", 'coords': f"{100 + index},200,10",
             'is_correct': index < correct_count}
            for index in range(region_count)
        ],
    }


def test_question_without_dropped_regions_stays_unmarked():
    xml = generate_hotspot_xml(_question(1), IdGenerator())
    assert HOTSPOT_REGIONS_LOST_MARKER not in xml
    assert "Achtung" not in xml


def test_dropped_regions_add_a_marker_to_the_question_name():
    xml = generate_hotspot_xml(_question(5), IdGenerator())
    assert HOTSPOT_REGIONS_LOST_MARKER in xml


def test_the_warning_stays_out_of_the_question_text():
    # Moodle zeigt in der Fragenliste Name und Textanfang nebeneinander –
    # im Fragetext stünde die Warnung mitten in der Übersicht.
    question = _question(5)
    xml = generate_hotspot_xml(question, IdGenerator())
    assert "Achtung" not in xml
    assert "Wählen Sie die Brille." in xml


def test_the_warning_is_handed_over_for_the_quiz_description():
    question = _question(5)
    generate_hotspot_xml(question, IdGenerator())
    notice = question["activity_notice"]

    assert "Achtung" in notice
    # Die Zahl der verlorenen Bereiche gehört hinein, sonst weiß niemand,
    # wie viel nachzubauen wäre.
    assert "4" in notice
    # Und der Hinweis muss sagen, dass die Größe schon angehoben wurde –
    # sonst sucht die Lehrkraft nach einem Problem, das nicht mehr besteht.
    assert str(HOTSPOT_MIN_RADIUS) in notice
    assert "Frage bearbeiten" in notice


def test_a_question_without_dropped_regions_hands_over_nothing():
    question = _question(1)
    generate_hotspot_xml(question, IdGenerator())
    assert "activity_notice" not in question


def test_tiny_region_is_enlarged_to_the_minimum():
    # In OLAT klickt man einen vorgegebenen Bereich an, wenige Pixel genügen.
    # In Moodle wird frei abgelegt – derselbe Radius wäre kaum zu treffen.
    question = _question(1)
    question['regions'][0]['coords'] = "359,266,10"
    xml = generate_hotspot_xml(question, IdGenerator())
    assert f"<coords>359,266;{HOTSPOT_MIN_RADIUS}</coords>" in xml


def test_a_generous_region_keeps_its_size():
    # Ein fester Faktor hätte hier ein Vielfaches der Bildbreite ergeben.
    question = _question(1)
    question['regions'][0]['coords'] = "400,300,450"
    xml = generate_hotspot_xml(question, IdGenerator())
    assert "<coords>400,300;450</coords>" in xml


def test_non_circular_regions_are_untouched():
    question = _question(1)
    question['regions'][0].update(shape="rect", coords="10,20,80,90")
    xml = generate_hotspot_xml(question, IdGenerator())
    assert "<coords>10,20;80,90</coords>" in xml


def test_the_original_question_text_is_kept():
    xml = generate_hotspot_xml(_question(5), IdGenerator())
    assert "Wählen Sie die Brille." in xml


def test_only_correct_regions_become_drop_zones():
    xml = generate_hotspot_xml(_question(5, correct_count=2), IdGenerator())
    assert xml.count("<drop id=") == 2
    assert xml.count("<drag id=") == 2
