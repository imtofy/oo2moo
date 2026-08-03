"""Tests für collect_orphaned_files() – die Meldung von Dateien aus dem
OLAT-Export, die nirgends im Backup gelandet sind.

Entscheidend ist die Richtung der Prüfung: gemeldet wird, was übrig BLEIBT,
nicht was auf einer Liste erlaubter Endungen steht. Eine Endungsliste kann
einen Dateityp nicht kennen und lässt ihn dann spurlos verschwinden – genau
das darf nicht passieren, weil der Verlust sonst erst im fertigen Moodle-Kurs
auffällt (oder gar nicht)."""

import hashlib

from conversion.manifest import CourseManifest, collect_orphaned_files
from conversion.node_processor import build_node_content


def _hashes(*contents):
    return {hashlib.sha1(content).hexdigest() for content in contents}


def _manifest(vfs):
    """CourseManifest ohne echtes ZIP – die Suche liest nur self.vfs."""
    manifest = CourseManifest.__new__(CourseManifest)
    manifest.vfs = vfs
    manifest.consumed_content_paths = set()
    return manifest


def test_unused_video_is_reported():
    # Kein Dokument, also von einer Endungsliste nie erfasst.
    vfs = {"export/77/repo.zip|master/video.mp4": b"filmdaten"}
    assert "77_video.mp4" in collect_orphaned_files(vfs, set(), set())


def test_unknown_extension_is_reported():
    vfs = {"kursordner/Diagramm.drawio": b"xml", "kursordner/notiz.gibtesnicht": b"x"}
    orphaned = collect_orphaned_files(vfs, set(), set())
    assert set(orphaned) == {"Diagramm.drawio", "notiz.gibtesnicht"}


def test_file_that_landed_in_the_backup_is_not_reported():
    vfs = {"kursordner/bild.png": b"bilddaten"}
    assert collect_orphaned_files(vfs, _hashes(b"bilddaten"), set()) == {}


def test_identical_content_under_another_name_counts_as_used():
    # files.xml speichert Content-addressed – derselbe Inhalt liegt nur einmal
    # im Backup und deckt damit jede Fundstelle ab.
    vfs = {"a/bild.png": b"gleich", "b/anderer_name.png": b"gleich"}
    assert collect_orphaned_files(vfs, _hashes(b"gleich"), set()) == {}


def test_contents_of_a_processed_package_are_not_reported():
    # SCORM/Buch/Test werden als Paket verarbeitet; ihre Innereien landen
    # nicht einzeln in files.xml, sind aber trotzdem übernommen.
    vfs = {
        "export/77/repo.zip|kapitel1.html": b"<p>Text</p>",
        "export/77/repo.zip|js/player.js": b"code",
    }
    assert collect_orphaned_files(vfs, set(), {"77"}) == {}


def test_package_of_another_node_is_still_reported():
    vfs = {"export/77/repo.zip|inhalt.html": b"a", "export/88/repo.zip|film.mp4": b"b"}
    assert set(collect_orphaned_files(vfs, set(), {"77"})) == {"88_film.mp4"}


def test_structural_files_are_not_reported():
    # Manifeste und Paket-Konfiguration sind Struktur, kein Kursinhalt.
    vfs = {
        "export/1/imsmanifest.xml": b"x",
        "export/1/repo.xml": b"x",
        "export/1/repo.zip|QTI21PackageConfig.xml": b"x",
        "export/1/repo.zip|video_metadata.xml": b"x",
    }
    assert collect_orphaned_files(vfs, set(), set()) == {}


def test_junk_files_are_not_reported():
    vfs = {"kursordner/._oo_meta_seite.html": b"x", "kursordner/.DS_Store": b"x"}
    assert collect_orphaned_files(vfs, set(), set()) == {}


def test_directory_entries_are_not_reported():
    # Verzeichnisse stehen ohne Basisnamen im VFS.
    vfs = {"kursordner/unterordner/": b""}
    assert collect_orphaned_files(vfs, set(), set()) == {}


def test_same_name_with_different_content_keeps_both():
    # OLAT vergibt je Baustein dieselben Dateinamen; die zweite Datei zu
    # verwerfen hiesse, echten Inhalt zu verlieren.
    vfs = {"a/skript.pdf": b"inhalt eins", "b/skript.pdf": b"inhalt zwei"}
    orphaned = collect_orphaned_files(vfs, set(), set())
    assert sorted(orphaned) == ["skript.pdf", "skript_1.pdf"]
    assert sorted(orphaned.values()) == [b"inhalt eins", b"inhalt zwei"]


def test_same_name_and_same_content_is_kept_once():
    vfs = {"a/skript.pdf": b"gleich", "b/skript.pdf": b"gleich"}
    assert list(collect_orphaned_files(vfs, set(), set())) == ["skript.pdf"]


def test_three_files_with_one_name_are_numbered_upwards():
    vfs = {f"knoten_{i}/taskDefinitions.xml": f"aufgabe {i}".encode() for i in range(3)}
    orphaned = collect_orphaned_files(vfs, set(), set())
    assert sorted(orphaned) == ["taskDefinitions.xml", "taskDefinitions_1.xml",
                                "taskDefinitions_2.xml"]
    assert len(set(orphaned.values())) == 3


def test_an_unpacked_archive_is_not_reported_as_its_own_find():
    # Sonst erscheint dieselbe Datei zweimal: als Verpackung und als Inhalt.
    vfs = {
        "export/1/repo.zip": b"zipdaten",
        "export/1/repo.zip|film.mp4": b"filmdaten",
    }
    assert set(collect_orphaned_files(vfs, set(), set())) == {"1_film.mp4"}


def test_an_archive_that_was_not_unpacked_is_still_reported():
    # Ohne entpackten Inhalt ist die Zip selbst das Einzige, was übrig bleibt.
    vfs = {"kursordner/material.zip": b"zipdaten"}
    assert set(collect_orphaned_files(vfs, set(), set())) == {"material.zip"}


def test_identically_named_packages_cause_no_conflict_messages(capsys):
    # 'repo.zip' heißt bei JEDEM Baustein gleich – ohne die Archiv-Regel
    # meldete jeder weitere Baustein einen Namenskonflikt.
    vfs = {}
    for ident in ("1", "2", "3"):
        vfs[f"export/{ident}/repo.zip"] = f"zip{ident}".encode()
        vfs[f"export/{ident}/repo.zip|inhalt_{ident}.txt"] = f"text{ident}".encode()

    orphaned = collect_orphaned_files(vfs, set(), set())

    assert "Namenskonflikt" not in capsys.readouterr().out
    assert set(orphaned) == {"1_inhalt_1.txt", "2_inhalt_2.txt", "3_inhalt_3.txt"}


def test_the_name_carries_the_olat_block_title():
    # Ohne Herkunft heißen im Verwaisten-Ordner mehrere Dateien gleich, und
    # niemand sieht ihnen an, zu welchem Baustein sie gehörten.
    vfs = {"export/77/taskDefinitions.xml": b"aufgabe"}
    orphaned = collect_orphaned_files(vfs, set(), set(), node_titles={"77": "Videoaufgabe"})
    assert list(orphaned) == ["Videoaufgabe_taskDefinitions.xml"]


def test_blocks_with_the_same_internal_filename_stay_apart():
    vfs = {
        "export/77/taskDefinitions.xml": b"eins",
        "export/88/taskDefinitions.xml": b"zwei",
    }
    orphaned = collect_orphaned_files(
        vfs, set(), set(), node_titles={"77": "Videoaufgabe", "88": "Gruppenaufgabe"})
    assert sorted(orphaned) == ["Gruppenaufgabe_taskDefinitions.xml",
                                "Videoaufgabe_taskDefinitions.xml"]


def test_unknown_block_falls_back_to_its_ident():
    vfs = {"export/99/feed.xml": b"feed"}
    assert list(collect_orphaned_files(vfs, set(), set())) == ["99_feed.xml"]


def test_characters_that_break_filenames_are_dropped_from_the_title():
    vfs = {"export/77/notiz.txt": b"text"}
    orphaned = collect_orphaned_files(vfs, set(), set(), node_titles={"77": 'A/B: "C"'})
    assert list(orphaned) == ["AB_C_notiz.txt"]


def test_course_folder_files_name_their_subfolder():
    vfs = {"oocoursefolder.zip|bilder/logo.png": b"bild"}
    assert list(collect_orphaned_files(vfs, set(), set())) == ["bilder_logo.png"]


def test_course_level_files_are_not_prefixed_with_themselves():
    # Kursweite Dateien liegen als 'export/<datei>' ohne Baustein-Ordner –
    # ohne Längenprüfung stünde dort der Dateiname als eigene Herkunft.
    vfs = {"export/BadgeClasses.xml": b"badges"}
    assert list(collect_orphaned_files(vfs, set(), set())) == ["BadgeClasses.xml"]


def test_spaces_in_the_block_title_become_underscores():
    # Ein Dateiname ohne Leerzeichen übersteht URL-Kodierung und Downloads
    # unbeschadet.
    vfs = {"export/77/form.xml": b"formular"}
    orphaned = collect_orphaned_files(vfs, set(), set(),
                                      node_titles={"77": "Bewertung mit Rubrics"})
    assert list(orphaned) == ["Bewertung_mit_Rubrics_form.xml"]


def _page_node(html_file):
    return {'title': 'Einzelne Seite', 'ident': '77', 'description': '',
            'html_file': html_file, 'rel_path': ''}


def test_source_html_of_a_converted_page_is_not_reported():
    """Der Quelltext einer Einzelseite liegt in Moodle im <content> der Seite
    und damit NIE in files.xml – ohne eigenes Verbrauchssignal bliebe er als
    scheinbar uebrig gebliebene Datei stehen, obwohl er uebernommen wurde."""
    vfs = {"oocoursefolder.zip|einzelne_seite/einzelne_seite.html": b"<p>Seitentext</p>"}
    manifest = _manifest(vfs)

    html_content, *_ = build_node_content(_page_node("/einzelne_seite/einzelne_seite.html"),
                                          manifest, "page", "sp")

    assert "Seitentext" in html_content, "Vorbedingung: der Inhalt ist in der Seite gelandet"
    assert collect_orphaned_files(vfs, set(), set(),
                                  consumed_paths=manifest.consumed_content_paths) == {}


def test_an_unreferenced_html_file_is_still_reported():
    """Gegenprobe: nur die tatsächlich eingelesene Datei gilt als verbraucht.
    Eine zweite HTML-Datei im selben Ordner gehört zu keinem Baustein und
    muss weiterhin auffallen."""
    vfs = {
        "oocoursefolder.zip|seite/seite.html": b"<p>Seitentext</p>",
        "oocoursefolder.zip|seite/uebrig.html": b"<p>Niemandes Inhalt</p>",
    }
    manifest = _manifest(vfs)

    build_node_content(_page_node("/seite/seite.html"), manifest, "page", "sp")

    orphaned = collect_orphaned_files(vfs, set(), set(),
                                      consumed_paths=manifest.consumed_content_paths)
    assert list(orphaned) == ["seite_uebrig.html"]
