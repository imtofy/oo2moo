"""Tests für Bausteine, deren repo.zip kein eigener Builder verarbeitet.

get_node_assets() überspringt Inhalte aus 'export/<ident>/repo.zip', weil sie
sonst doppelt herauskämen: bei cp/scorm/wiki/iqtest registriert der jeweilige
Builder das Paket selbst. Für einen Video-Baustein gibt es keinen solchen
Builder – dort ist repo.zip die einzige Quelle, der Ausschluss lässt die
Videodatei also ersatzlos verschwinden."""

import io
import zipfile

from conversion.manifest import CourseManifest


def _course_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _manifest_with_video(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, 'w') as archive:
        archive.writestr("master/video.mp4", b"filmdaten")
        archive.writestr("master/poster.jpg", b"vorschau")
        archive.writestr("repoentry/repo.xml", b"<repo/>")
    course = _course_zip({
        "editortreemodel.xml": b"<root/>",
        "export/77/repo.zip": inner.getvalue(),
    })
    path = tmp_path / "kurs.zip"
    path.write_bytes(course)
    return CourseManifest(str(path))


def test_package_contents_are_skipped_by_default(tmp_path):
    # Unverändertes Verhalten für cp/scorm/wiki/iqtest – deren Builder
    # registrieren das Paket selbst.
    _, assets = _manifest_with_video(tmp_path).get_node_assets("77")
    assert assets == []


def test_package_contents_are_returned_when_requested(tmp_path):
    _, assets = _manifest_with_video(tmp_path).get_node_assets(
        "77", include_package_files=True)

    names = {asset["name"] for asset in assets}
    assert "video.mp4" in names
    video = next(asset for asset in assets if asset["name"] == "video.mp4")
    assert video["data"] == b"filmdaten"


def test_package_structure_files_are_not_returned_as_attachments(tmp_path):
    # repo.xml beschreibt den Repository-Eintrag, ist kein Kursinhalt.
    _, assets = _manifest_with_video(tmp_path).get_node_assets(
        "77", include_package_files=True)
    assert "repo.xml" not in {asset["name"] for asset in assets}


def test_video_type_is_marked_as_having_no_builder():
    from config import PACKAGE_AS_ATTACHMENT_TYPES
    assert "video" in PACKAGE_AS_ATTACHMENT_TYPES
    # Typen MIT eigenem Builder dürfen dort nicht stehen, sonst käme ihr
    # Paket zusätzlich als loser Anhang heraus.
    for olat_type in ("cp", "scorm", "wiki", "iqtest", "iqself"):
        assert olat_type not in PACKAGE_AS_ATTACHMENT_TYPES
