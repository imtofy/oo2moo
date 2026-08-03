"""Tests für die Zuordnung von Anhängen zu Moodle-Dateibereichen.

Ein Anhang, der nicht im Beschreibungstext referenziert ist, gehört in das
Feld, das der Modultyp dafür vorsieht – bei mod_assign 'introattachment'
("Zusätzliche Dateien"). Landet er stattdessen als Download-Link im
Beschreibungstext, steht er an einer Stelle, an der Moodle ihn beim
Bearbeiten der Aktivität nicht als Anhang führt.

Die Auflösung läuft über eine Rangfolge (ATTACHMENT_FILEAREA_PREFERENCE):
der erste Bereich, den der Modultyp überhaupt besitzt, gewinnt. Ein
Modultyp ohne eigenes Anhang-Feld fällt darüber automatisch auf 'intro'
zurück, wo der eingebettete Link die einzige Möglichkeit bleibt, die Datei
erreichbar zu machen.
"""

from conversion import file_manager
from conversion.node_processor import _auto_embed


def _attachment(name="aufgabe.docx"):
    return {"name": name, "data": b"inhalt", "relpath": ""}


def test_assign_attachment_goes_to_the_field_moodle_provides():
    # mod_assign kennt 'introattachment' (backup_assign_stepslib.php:209).
    assert file_manager.resolve_attachment_filearea("assign") == "introattachment"


def test_module_without_its_own_field_falls_back_to_intro():
    # forum/url/quiz/feedback/choice haben in Moodle-Core ausser 'intro'
    # keinen Dateibereich – dort MUSS der Anhang in die Beschreibung.
    for m_type in ("forum", "url", "quiz", "feedback", "choice"):
        assert file_manager.resolve_attachment_filearea(m_type) == "intro", m_type


def test_content_modules_use_their_content_area():
    for m_type in ("page", "resource", "folder"):
        assert file_manager.resolve_attachment_filearea(m_type) == "content", m_type
        assert file_manager.resolve_content_filearea(m_type) == "content", m_type


def test_unknown_module_type_falls_back_to_intro():
    # Ein Modultyp ohne Eintrag darf die Konvertierung nicht sprengen.
    assert file_manager.resolve_attachment_filearea("gibtesnicht") == "intro"
    assert file_manager.resolve_content_filearea("gibtesnicht") == "intro"


def test_referenced_files_always_use_the_description_area():
    # Ein @@PLUGINFILE@@-Verweis im Beschreibungstext löst nur im Bereich
    # dieses Textes auf – für mod_assign also 'intro', nicht 'introattachment'.
    assert file_manager.resolve_content_filearea("assign") == "intro"


def test_assign_attachment_is_not_written_into_the_description():
    attachments = [_attachment()]
    html = _auto_embed("<p>Bitte bearbeiten.</p>", attachments, "assign")

    assert "Dateianhang" not in html
    assert "aufgabe.docx" not in html
    assert attachments[0]["filearea"] == "introattachment"


def test_module_without_the_field_keeps_the_embedded_link():
    # Ohne Zielfeld wäre die Datei sonst zwar in files.xml registriert,
    # im Kurs aber nirgends sichtbar.
    attachments = [_attachment("protokoll.docx")]
    html = _auto_embed("<p>Text</p>", attachments, "url")

    assert "protokoll.docx" in html
    assert attachments[0].get("filearea") in (None, "intro")


def test_image_referenced_in_the_text_stays_in_the_description():
    # Bilder gehören weiterhin in den Beschreibungstext, auch bei assign –
    # sie sind Teil der Aufgabenstellung, kein separater Anhang.
    attachments = [_attachment("skizze.png")]
    html = _auto_embed("<p>Siehe skizze.png</p>", attachments, "assign")

    assert "@@PLUGINFILE@@/skizze.png" in html
    assert attachments[0].get("filearea") in (None, "intro")


def test_attachment_without_a_document_extension_is_untouched():
    # Eine bereits im Text verlinkte Datei darf nicht zusätzlich verschoben
    # werden – sonst bricht der @@PLUGINFILE@@-Verweis.
    attachments = [_attachment()]
    html = _auto_embed('<a href="@@PLUGINFILE@@/aufgabe.docx">Angabe</a>', attachments, "assign")

    assert html.count("aufgabe.docx") == 1
    assert attachments[0].get("filearea") in (None, "intro")
