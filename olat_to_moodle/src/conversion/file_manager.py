"""Verwaltet die Moodle-Dateistruktur (Content-Addressable Storage) der .mbz.

Moodle-Backups speichern jede physische Datei einmal unter dem SHA1-Hash
ihres Inhalts ab (files/<hash[:2]>/<hash>) und referenzieren sie darüber aus
files.xml. Dieses Modul kapselt das Hashing, Ablegen und die files.xml-
Generierung, damit main.py nur noch add_moodle_file()/add_moodle_directory()
aufrufen muss.
"""

import os
import hashlib
import mimetypes
import html
import re
import urllib.parse

# In XML 1.0 verbotene Steuerzeichen: alles unter 0x20 außer Tab (0x09),
# Zeilenumbruch (0x0A) und Wagenrücklauf (0x0D), dazu 0x7F. Ein solches
# Zeichen in einem OLAT-Titel macht nicht nur dieses Feld kaputt, sondern
# die ganze XML-Datei unparsebar – und damit das komplette Backup.
_XML_ILLEGAL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Modultypen, deren Text in <content> steht statt in <intro>. Ein
# @@PLUGINFILE@@-Verweis aus diesem Text löst ausschließlich im Bereich des
# Textes auf – dort müssen die darin referenzierten Dateien also liegen.
CONTENT_TEXT_MODULES = ("page", "resource", "folder")

# Modultypen mit eigenem Dateibereich für Anhänge, die im Text NICHT
# referenziert sind. Ohne Eintrag bleibt es beim Textbereich des Moduls, wo
# ein eingebetteter Download-Link die einzige Möglichkeit ist, die Datei
# überhaupt erreichbar zu machen (node_processor._auto_embed).
#
# mod_assign ist in Moodle-Core der einzige der von uns erzeugten Modultypen
# mit einem solchen Feld ('introattachment' = "Zusätzliche Dateien", siehe
# backup_assign_stepslib.php). forum/url/quiz/feedback/choice haben außer
# 'intro' keinen Dateibereich. wiki und book haben zwar eigene Bereiche,
# die hängen dort aber an einer Unterseiten-ID statt an itemid=0 und passen
# deshalb nicht in diese Zuordnung.
ATTACHMENT_FILEAREAS = {"assign": "introattachment"}


def resolve_content_filearea(m_type: str) -> str:
    """Dateibereich, in dem der Text der Aktivität steht – und damit der
    Bereich, in dem die daraus referenzierten Dateien liegen müssen."""
    return "content" if m_type in CONTENT_TEXT_MODULES else "intro"


def resolve_attachment_filearea(m_type: str) -> str:
    """Dateibereich für einen Anhang ohne Verweis im Text: das dafür
    vorgesehene Feld des Modultyps, sonst der Textbereich selbst."""
    return ATTACHMENT_FILEAREAS.get(m_type) or resolve_content_filearea(m_type)


def escape_xml_text(value, quote: bool = False) -> str:
    """Maskiert einen Wert für einen XML-Textknoten und entfernt vorher die
    in XML verbotenen Steuerzeichen.

    quote=False ist die Vorgabe: in Textknoten müssen nur & < > maskiert
    werden, und literale Anführungszeichen bleiben so erhalten (nötig für
    die @@PLUGINFILE@@-Prüfung in validators/backup_validator.py). Für einen
    Wert, der in ein ATTRIBUT geschrieben wird, quote=True setzen."""
    return html.escape(_XML_ILLEGAL_CHARS.sub('', str(value)), quote=quote)


def activity_title(node: dict, fallback: str = 'Unbenannt') -> str:
    """Titel einer Aktivität samt Markierungen ('display_title', sonst 'title').

    Einzige Quelle für JEDEN Builder: main.py setzt die Markierungen aus den
    Knoteneigenschaften, Builder ergänzen eigene über mark_activity_title().
    Wer stattdessen node['title'] liest, schreibt den rohen OLAT-Titel ins
    Aktivitäts-XML und weicht damit von der Kursübersicht ab."""
    return node.get('display_title') or node.get('title') or fallback


def mark_activity_title(node: dict, symbol: str) -> str:
    """Klammert den Aktivitätstitel in symbol. Vorhandene Markierungen bleiben
    stehen, damit mehrere Verluste am selben Baustein alle sichtbar sind."""
    node['display_title'] = f"{symbol} {activity_title(node)} {symbol}"
    return node['display_title']


def unique_filename(filename: str, taken) -> str:
    """Findet einen im Dateibereich freien Namen, indem '_1', '_2', ... vor die
    Endung gesetzt wird ('bild.png' -> 'bild_1.png').

    Die erste Datei behält ihren Namen ohne Suffix und zählt als 0, die
    zweite wird also '_1'.

    Nötig, weil ein @@PLUGINFILE@@-Verweis immer in den Wurzelpfad des
    Dateibereichs zeigt: zwei verschiedene Dateien mit gleichem Namen können
    dort nicht nebeneinander liegen, die zweite würde sonst verloren gehen.
    taken ist alles, was in DIESEM Dateibereich schon vergeben ist (Menge
    oder Dict)."""
    if filename not in taken:
        return filename
    stem, extension = _split_extension(filename)
    suffix = 1
    while f"{stem}_{suffix}{extension}" in taken:
        suffix += 1
    return f"{stem}_{suffix}{extension}"


# Mehrteilige Endungen, die als Ganzes hinten bleiben müssen – sonst würde
# 'archiv.tar.gz' zu 'archiv.tar_1.gz' statt 'archiv_1.tar.gz'.
_DOPPELTE_ENDUNGEN = ('.tar.gz', '.tar.bz2', '.tar.xz', '.tar.zst')


def _split_extension(filename: str):
    """Zerlegt einen Dateinamen in (Stamm, Endung) – die Endung inklusive
    Punkt, oder leer, wenn es keine gibt."""
    klein = filename.lower()
    for extension in _DOPPELTE_ENDUNGEN:
        if klein.endswith(extension):
            return filename[:-len(extension)], filename[-len(extension):]
    stem, punkt, ext = filename.rpartition('.')
    if not punkt:
        return filename, ''
    return stem, punkt + ext


class FileAreaNames:
    """Vergibt eindeutige Dateinamen innerhalb EINES Moodle-Dateibereichs.

    Ein @@PLUGINFILE@@-Verweis zeigt immer in den Wurzelpfad seines
    Dateibereichs – zwei verschiedene Dateien mit gleichem Basisnamen können
    dort nicht nebeneinander liegen. In OLAT-Exporten passiert genau das
    regelmäßig, weil ein ins Editor-Feld eingefügtes Bild immer 'mceclip0.png'
    heißt und in jedem Ordner neu bei 0 anfängt.

    Pro Dateibereich EINE Instanz anlegen (pro Baustein, pro Buchkapitel, pro
    Frage). Gleicher Inhalt behält seinen Namen – dieselbe Datei zweimal
    einzubinden braucht keinen zweiten Eintrag.
    """

    def __init__(self):
        self._data_by_name = {}
        # Wie oft ein Name unverändert vergeben wurde. Genau so viele
        # unveränderte '@@PLUGINFILE@@/<name>'-Vorkommen stehen noch im HTML,
        # der Zähler ist damit der Index der als nächstes umzuschreibenden
        # Fundstelle (siehe assign_in_html).
        self._kept_count = {}

    def assign(self, filename: str, data: bytes) -> str:
        """Endgültiger Name für diese Datei in diesem Bereich."""
        if self._data_by_name.get(filename, data) != data:
            filename = unique_filename(filename, self._data_by_name)
        else:
            self._kept_count[filename] = self._kept_count.get(filename, 0) + 1
        self._data_by_name[filename] = data
        return filename

    def assign_in_html(self, filename: str, data: bytes, html: str):
        """Wie assign(), zieht aber einen bereits ins HTML geschriebenen
        @@PLUGINFILE@@-Verweis mit um. Gibt (Name, HTML) zurück.

        Setzt voraus, dass die Dateien in derselben Reihenfolge übergeben
        werden, in der ihre Verweise im HTML stehen – sanitize_for_moodle()
        und process_html_and_images() gehen beide in Dokumentreihenfolge vor.
        """
        original = filename
        occurrence = self._kept_count.get(original, 0)
        assigned = self.assign(original, data)
        if assigned != original:
            html = rewrite_pluginfile_reference(html, original, assigned, occurrence)
        return assigned, html


def rewrite_pluginfile_reference(html: str, old_name: str, new_name: str, occurrence: int) -> str:
    """Schreibt das <occurrence>-te (0-basiert) '@@PLUGINFILE@@/<old_name>' im
    HTML auf new_name um und lässt alle anderen Vorkommen stehen.

    Die Verweise stehen URL-kodiert im HTML, deshalb wird auch hier kodiert
    gesucht und geschrieben."""
    needle = f"@@PLUGINFILE@@/{urllib.parse.quote(old_name)}"
    replacement = f"@@PLUGINFILE@@/{urllib.parse.quote(new_name)}"
    start = -1
    for _ in range(occurrence + 1):
        start = html.find(needle, start + 1)
        if start == -1:
            return html
    return html[:start] + replacement + html[start + len(needle):]


def write_xml(path: str, content: str) -> None:
    """content ohne <?xml ...?>-Kopf – der wird hier ergänzt."""
    with open(path, "w", encoding="utf-8", newline='\n') as handle:
        handle.write(f'<?xml version="1.0" encoding="UTF-8"?>\n{content}')


def write_activity_context(temp_dir: str, context_id: int, module_id: int) -> None:
    """Legt contexts/context_<id>/context.xml für eine Aktivität an.

    contextlevel 70 ist in Moodle die Aktivitätsebene (CONTEXT_MODULE),
    instanceid die course_modules-ID, zu der der Kontext gehört. Jede
    erzeugte Aktivität braucht genau einen solchen Eintrag, sonst findet
    Moodle beim Restore ihre Dateien nicht."""
    context_path = os.path.join(temp_dir, "contexts", f"context_{context_id}")
    os.makedirs(context_path, exist_ok=True)
    write_xml(os.path.join(context_path, "context.xml"),
              f'<context id="{context_id}" contextlevel="70" instanceid="{module_id}"></context>')


class FileManager:
    """Sammelt alle Dateien eines Backup-Laufs und schreibt sie Content-addressed weg.

    Braucht: temp_dir (Wurzelverzeichnis des im Bau befindlichen Backups –
    Dateien landen unter temp_dir/files/<hash[:2]>/<hash>).
    """

    def __init__(self, temp_dir: str):
        """Legt die Sammel-Listen für diesen Backup-Lauf an."""
        self.moodle_files = []
        self.temp_dir = temp_dir
        self.created_directories = {}

    def add_moodle_directory(self, contextid: int, component: str, filearea: str, itemid: int, now: int,
                             filepath: str = "/") -> int:
        """Registriert einen leeren Verzeichnis-Eintrag (filename=".") und gibt
        dessen File-ID zurück. Moodle braucht pro (contextid, component,
        filearea, itemid, filepath) GENAU einen solchen Marker, sonst
        verwirft es beim Restore alle Dateien dieses Bereichs/Unterordners –
        jeder echte Unterordner braucht also seinen eigenen. Wiederholte
        Anfragen für denselben Bereich liefern die schon vergebene ID."""
        dir_key = (contextid, component, filearea, itemid, filepath)
        if dir_key in self.created_directories:
            return self.created_directories[dir_key]

        empty_hash = hashlib.sha1(b"").hexdigest()

        target_dir = os.path.join(self.temp_dir, "files", empty_hash[:2])
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, empty_hash)

        if not os.path.exists(target_path):
            with open(target_path, "wb") as handle:
                handle.write(b"")

        file_id = len(self.moodle_files) + 1
        self.moodle_files.append({
            "id": file_id,
            "contenthash": empty_hash,
            "contextid": contextid,
            "component": component,
            "filearea": filearea,
            "itemid": itemid,
            "filename": ".",
            "filepath": filepath,
            "filesize": 0,
            "mimetype": "$@NULL@$",
            "now": now
        })
        self.created_directories[dir_key] = file_id
        return file_id

    def add_moodle_file(self, source_content: bytes, filename: str, contextid: int, component: str,
                         filearea: str, itemid: int, now: int, filepath: str = "/") -> int:
        """Hasht den Inhalt (SHA1) und schreibt ihn nur, falls unter diesem Hash
        noch nichts liegt (Dedup über identische Inhalte)."""
        file_hash = hashlib.sha1(source_content).hexdigest()

        target_dir = os.path.join(self.temp_dir, "files", file_hash[:2])
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, file_hash)

        if not os.path.exists(target_path):
            with open(target_path, "wb") as handle:
                handle.write(source_content)

        file_id = len(self.moodle_files) + 1

        mimetype, _ = mimetypes.guess_type(filename)
        if not mimetype:
            mimetype = "application/octet-stream"

        self.moodle_files.append({
            "id": file_id,
            "contenthash": file_hash,
            "contextid": contextid,
            "component": component,
            "filearea": filearea,
            "itemid": itemid,
            "filename": filename,
            "filepath": filepath,
            "filesize": len(source_content),
            "mimetype": mimetype,
            "now": now
        })
        return file_id

    def generate_files_xml(self) -> str:
        """Baut die globale files.xml aus allen bisher registrierten Dateien/Verzeichnissen."""
        xml = '<files>\n'
        for mf in self.moodle_files:
            safe_filename = html.escape(mf['filename'])
            safe_filepath = html.escape(mf.get('filepath', '/'))
            xml += f'''  <file id="{mf['id']}">
    <contenthash>{mf['contenthash']}</contenthash>
    <contextid>{mf['contextid']}</contextid>
    <component>{mf['component']}</component>
    <filearea>{mf['filearea']}</filearea>
    <itemid>{mf['itemid']}</itemid>
    <filepath>{safe_filepath}</filepath>
    <filename>{safe_filename}</filename>
    <userid>$@NULL@$</userid>
    <filesize>{mf['filesize']}</filesize>
    <mimetype>{mf['mimetype']}</mimetype>
    <status>0</status>
    <timecreated>{mf['now']}</timecreated>
    <timemodified>{mf['now']}</timemodified>
    <source>$@NULL@$</source>
    <author>$@NULL@$</author>
    <license>allrightsreserved</license>
    <sortorder>1</sortorder>
    <referencefileid>$@NULL@$</referencefileid>
  </file>\n'''
        xml += '</files>'
        return xml
