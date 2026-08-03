"""Tests für den Aktivitätstitel samt Markierungen (🔓 Passwort, ⚠️ Verlust).

Markierungen kommen aus zwei Richtungen – main.py aus den Knoteneigenschaften,
die Builder aus Verlusten beim Konvertieren – und laufen beide über dasselbe
Feld. Liest ein Builder stattdessen den rohen OLAT-Titel, trägt die
Kursübersicht eine andere Beschriftung als die Aktivität."""

from conversion.file_manager import activity_title, mark_activity_title


def test_without_markers_the_plain_title_is_used():
    assert activity_title({'title': "Einzelne Seite"}) == "Einzelne Seite"


def test_a_marked_title_wins_over_the_raw_one():
    node = {'title': "Geschützte Seite", 'display_title': "🔓 Geschützte Seite 🔓"}
    assert activity_title(node) == "🔓 Geschützte Seite 🔓"


def test_the_fallback_applies_to_a_nameless_node():
    assert activity_title({}, "Test") == "Test"


def test_marking_frames_the_title_on_both_sides():
    node = {'title': "Hotspot-Frage"}
    assert mark_activity_title(node, "⚠️") == "⚠️ Hotspot-Frage ⚠️"
    assert activity_title(node) == "⚠️ Hotspot-Frage ⚠️"


def test_a_builder_marker_keeps_the_one_main_already_set():
    # Ein Test im passwortgeschützten Abschnitt, bei dem zusätzlich
    # Hotspot-Bereiche verlorengingen – beide Verluste bleiben sichtbar.
    node = {'title': "Hotspot-Frage", 'display_title': "🔓 Hotspot-Frage 🔓"}
    assert mark_activity_title(node, "⚠️") == "⚠️ 🔓 Hotspot-Frage 🔓 ⚠️"


def test_an_empty_display_title_falls_back_to_the_raw_one():
    # Ein leerer Wert darf den echten Titel nicht verdrängen.
    assert activity_title({'title': "Wiki", 'display_title': ""}) == "Wiki"
