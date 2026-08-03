"""Tests für CourseManifest.get_node_assets() – vor allem die Grenze zwischen
Paket-Inhalten (repo.zip, gehören dem jeweiligen Builder) und knoteneigenem
Inhalt (oonode.zip und lose Dateien), weil beide im VFS hinter derselben
'|'-Zip-Grenze liegen und nur am Container-Namen unterscheidbar sind."""

from conversion.manifest import CourseManifest


def _manifest(vfs):
    """CourseManifest ohne echtes ZIP – get_node_assets() liest nur self.vfs."""
    manifest = CourseManifest.__new__(CourseManifest)
    manifest.vfs = vfs
    return manifest


def test_repo_package_contents_are_not_node_assets():
    # cp/scorm/wiki/iqtest lösen ihr Paket über resolve_repo_package() auf und
    # registrieren die Dateien selbst – hier dürfen sie nicht ein zweites Mal
    # als lose Anhänge herauskommen.
    manifest = _manifest({
        "export/42/repo.zip": b"PK\x03\x04",
        "export/42/repo.zip|imsmanifest.xml": b"<manifest/>",
        "export/42/repo.zip|bild.png": b"\x89PNG",
        "export/42/repo.zip|mobile/foto.jpg": b"\xff\xd8\xff",
    })

    html, assets = manifest.get_node_assets("42")

    assert assets == []
    assert html == ""


def test_oonode_contents_stay_node_assets():
    # oonode.zip ist der Container für den EIGENEN Inhalt eines Knotens
    # (siehe get_node_folder_tree) – der muss weiterhin eingesammelt werden.
    manifest = _manifest({
        "export/42/oonode.zip": b"PK\x03\x04",
        "export/42/oonode.zip|anhang.pdf": b"%PDF-1.4",
    })

    _html, assets = manifest.get_node_assets("42")

    assert [attach["name"] for attach in assets] == ["anhang.pdf"]


def test_loose_files_and_html_still_found():
    manifest = _manifest({
        "export/42/seite.html": b"<p>Inhalt</p>",
        "export/42/anhang.pdf": b"%PDF-1.4",
    })

    html, assets = manifest.get_node_assets("42")

    assert "Inhalt" in html
    assert [attach["name"] for attach in assets] == ["anhang.pdf"]


def test_package_and_own_content_side_by_side():
    # Ein Knoten kann beides haben: ein referenziertes Paket UND eigene
    # Dateien direkt darunter. Nur das Paket wird ausgeblendet.
    manifest = _manifest({
        "export/42/repo.zip": b"PK\x03\x04",
        "export/42/repo.zip|paketseite.html": b"<p>Paket</p>",
        "export/42/repo.zip|paketbild.png": b"\x89PNG",
        "export/42/eigene.pdf": b"%PDF-1.4",
    })

    html, assets = manifest.get_node_assets("42")

    assert [attach["name"] for attach in assets] == ["eigene.pdf"]
    assert "Paket" not in html


def test_other_nodes_are_untouched():
    manifest = _manifest({
        "export/42/anhang.pdf": b"%PDF-1.4",
        "export/99/fremd.pdf": b"%PDF-1.4",
    })

    _html, assets = manifest.get_node_assets("42")

    assert [attach["name"] for attach in assets] == ["anhang.pdf"]


def test_a_leading_slash_means_the_course_folder_root():
    """In OLAT bezeichnet '/datei.html' die Wurzel des Kursordners. Ohne diese
    Unterscheidung gewinnt eine gleichnamige Datei aus einem Unterordner,
    sobald sie im VFS zuerst steht – der Baustein zeigt dann fremden Inhalt."""
    manifest = _manifest({
        "oocoursefolder.zip|unterordner/video.html": b"<p>falsches Video</p>",
        "oocoursefolder.zip|video.html": b"<p>richtiges Video</p>",
    })

    hit = manifest.search_file("/video.html")

    assert hit["path"] == "oocoursefolder.zip|video.html"


def test_without_a_leading_slash_a_subfolder_hit_stays_valid():
    manifest = _manifest({"oocoursefolder.zip|unterordner/video.html": b"<p>Video</p>"})

    hit = manifest.search_file("video.html")

    assert hit["path"] == "oocoursefolder.zip|unterordner/video.html"


def test_an_absolute_path_still_falls_back_to_a_subfolder_hit():
    """Liegt die Datei nirgends in der Wurzel, ist ein Treffer im Unterordner
    besser als gar keiner – die Wurzel hat nur Vorrang, sie ist keine Pflicht."""
    manifest = _manifest({"oocoursefolder.zip|unterordner/skript.pdf": b"%PDF"})

    hit = manifest.search_file("/skript.pdf")

    assert hit["path"] == "oocoursefolder.zip|unterordner/skript.pdf"
