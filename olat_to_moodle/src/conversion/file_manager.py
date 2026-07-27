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


def write_xml(path: str, content: str) -> None:
    """content ohne <?xml ...?>-Kopf - der wird hier ergänzt."""
    with open(path, "w", encoding="utf-8", newline='\n') as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n{content}')


class FileManager:
    """Sammelt alle Dateien eines Backup-Laufs und schreibt sie Content-addressed weg.

    Braucht: temp_dir (Wurzelverzeichnis des im Bau befindlichen Backups -
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
        verwirft es beim Restore alle Dateien dieses Bereichs/Unterordners -
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
            with open(target_path, "wb") as f:
                f.write(b"")

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
            with open(target_path, "wb") as f:
                f.write(source_content)

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
