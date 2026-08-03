"""Baut den Moodle-Inhalt (HTML + Anhänge) für einen einzelnen OLAT-Kursbaustein.

Sammelt die HTML-Quelle und alle zugehörigen Dateien eines Kursknotens aus
dem CourseManifest-VFS zusammen, bereinigt das HTML für Moodle
(html_cleaner.sanitize_for_moodle) und bettet verwaiste Bilder/Dokumente/
Medien automatisch ein, damit main.py nur noch build_node_content()
aufrufen muss.
"""

import os
import re
import urllib.parse
import html as html_lib
from typing import Dict, List, Optional, Tuple

from config import (PACKAGE_AS_ATTACHMENT_TYPES, PASSWORD_LOST_WARNING,
                    MISSING_FILE_WARNING, ATTACHMENT_LINK_BOX)
from .file_manager import FileAreaNames, resolve_attachment_filearea, resolve_content_filearea
from .html_cleaner import sanitize_for_moodle


_IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp')
_DOCUMENT_EXTS = ('.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.txt', '.zip', '.rtf')
_VIDEO_EXTS = ('.mp4', '.mov', '.webm', '.mkv', '.m4v')
_AUDIO_EXTS = ('.mp3', '.wav', '.ogg', '.m4a')


def _is_thumbnail(fname: str) -> bool:
    """Erkennt interne OLAT-Vorschaubilder (Thumbnails/Video-Poster), die nicht
    als eigenständiges Bild eingebettet werden sollen."""
    return (
        fname.startswith('._oo_th_') or
        fname.lower() == 'poster.jpg' or
        bool(re.match(r'^\d{8,12}\.jpg$', fname, re.IGNORECASE)) or
        bool(re.match(r'^thumbnail_\d+\.jpe?g$', fname, re.IGNORECASE))
    )


# Skaliert Videos responsiv auf die volle Breite, begrenzt die Höhe aber nach
# oben (verhindert, dass ein sehr hochkantiges Video den Seitenrahmen sprengt).
# Die explizite Breite ist nötig, weil Browser ein <video>-Element ohne
# geladene Metadaten sonst in Originalgröße (oft winzig) darstellen.
_VIDEO_STYLE = "width:100%; max-width:100%; max-height:75vh; height:auto;"

# Feste Höhenbegrenzung (max-height) statt reinem height:auto wie beim Video –
# ein <iframe> hat anders als <video> keine eigene Breiten/Höhen-Beziehung,
# würde also ohne Höhenangabe gar nicht oder mit Browser-Default (~150px)
# dargestellt. 80vh/900px sorgt dafür, dass es auf großen Bildschirmen nicht
# den ganzen Viewport füllt, auf kleinen (Handy) aber trotzdem brauchbar
# groß bleibt und scrollbar ist.
_PDF_EMBED_STYLE = "width:100%; height:80vh; max-height:900px; border:none;"


def _auto_embed(html_content: str, attachments: List[Dict], m_type: str) -> str:
    """Bettet Anhänge ein, die noch nicht im HTML referenziert sind – sonst
    wäre die Datei zwar in files.xml registriert, aber im Kurs nirgends
    sichtbar. Bilder: ersetzen den Dateinamen im Text, falls er als nackter
    Text vorkommt (OLAT-Bildunterschrift), sonst werden sie vorne
    angehängt. Video/Audio landen als Player – jeweils nur, wenn noch kein
    @@PLUGINFILE@@-Verweis existiert.

    Dokumente bekommen nur dann einen Download-Link im Text, wenn der
    Modultyp keinen eigenen Anhang-Bereich hat. Gibt es einen (bei
    mod_assign das Feld "Zusätzliche Dateien"), wird der Anhang stattdessen
    mit 'filearea' markiert – main.py registriert ihn dann dort, wo Moodle
    ihn als Anhang der Aktivität führt statt als Teil ihres Textes.
    Referenzierte Dateien bleiben unberührt im Textbereich, weil ihr
    @@PLUGINFILE@@-Verweis nur dort auflöst."""
    for attach in attachments:
        fname = attach["name"]
        safe_name = urllib.parse.quote(fname)
        plugin_ref_encoded = f"@@PLUGINFILE@@/{safe_name}"
        plugin_ref_raw = f"@@PLUGINFILE@@/{fname}"

        is_image = fname.lower().endswith(_IMAGE_EXTS)
        is_document = fname.lower().endswith(_DOCUMENT_EXTS)
        is_video = fname.lower().endswith(_VIDEO_EXTS)
        is_audio = fname.lower().endswith(_AUDIO_EXTS)

        if is_image and not _is_thumbnail(fname):
            if html_content and plugin_ref_encoded not in html_content and plugin_ref_raw not in html_content:
                img_tag = (f'<img src="{plugin_ref_encoded}" '
                           f'style="max-width: calc(100% - 30px); height: auto; margin: 10px 15px;" '
                           f'alt="{html_lib.escape(fname)}">')
                pattern = rf'(^|>|\s)({re.escape(fname)})($|<|\s)'
                new_html = re.sub(pattern,
                                  lambda match, tag=img_tag: f"{match.group(1)}{tag}{match.group(3)}",
                                  html_content)
                html_content = new_html if new_html != html_content else img_tag + "<br/>" + html_content
            elif not html_content:
                html_content = (f'<img src="{plugin_ref_encoded}" '
                                f'style="max-width: calc(100% - 30px); height: auto; margin: 10px 15px;" '
                                f'alt="{html_lib.escape(fname)}">')

        elif is_video or is_audio:
            if plugin_ref_encoded not in html_content and plugin_ref_raw not in html_content:
                if is_video:
                    media_tag = (f'<video controls style="{_VIDEO_STYLE}">'
                                 f'<source src="{plugin_ref_encoded}"></video>')
                else:
                    media_tag = f'<audio controls><source src="{plugin_ref_encoded}"></audio>'
                html_content = (html_content + f"<br/>{media_tag}") if html_content else media_tag

        elif is_document:
            if plugin_ref_encoded not in html_content and plugin_ref_raw not in html_content:
                attachment_area = resolve_attachment_filearea(m_type)
                if attachment_area != resolve_content_filearea(m_type):
                    attach["filearea"] = attachment_area
                    continue
                doc_link = ATTACHMENT_LINK_BOX.format(
                    url=plugin_ref_encoded, filename=html_lib.escape(fname))
                html_content = (html_content + f"<br/>{doc_link}") if html_content else doc_link

    return html_content


def build_node_content(node: Dict, manifest, m_type: str, olat_type: str,
                       link_map: Optional[Dict] = None
                       ) -> Tuple[str, List[Dict], List[Dict], List[str], Optional[str], str]:
    """Sammelt HTML-Inhalt und Anhänge eines Kursknotens und bereitet sie für Moodle auf.

    link_map (OLAT-ident → (Moodle-Modul-ID, Modultyp)) löst kursinterne
    gotonode-Verweise zu echten Moodle-Links auf. OLATs "Beschreibung"
    (node['description']) bekommt bei m_type='page' einen eigenen, separat
    zurückgegebenen Sanitize-Durchlauf (description_html) statt in den
    Seiteninhalt eingemischt zu werden – mod_page hat mit <intro> (Info-
    Block, im Template bereits über showdescription/printintro aktiv) und
    <content> (eigentlicher Seiteninhalt) zwei eigenständige Felder dafür
    (siehe main.py/moodle_xml.py). Bei jedem anderen Bausteintyp (Ordner,
    Forum, Externe Seite, ...) gibt es kein vom Intro getrenntes Content-
    Feld – dort steht die Beschreibung vorne im gemeinsamen Text, sonst
    ginge sie verloren. Bilder/Dokumente im HTML werden relativ
    zur HTML-Quelle nachgeladen, damit bei mehrfach vorkommenden Dateinamen
    (z.B. 'mceclip0.png') die richtige Version gefunden wird.

    Bei m_type='folder' kommen die Anhänge über
    manifest.get_node_folder_tree() statt get_node_assets(), damit echte
    Unterordner-Struktur (inkl. leerer Unterordner) erhalten bleibt statt
    alles flach in einen Ordner zu werfen – Dedup läuft daher nach
    (Unterordner-Pfad, Dateiname), nicht nur Dateiname. _auto_embed() läuft
    bei Ordnern und bei 'resource' (Datei-Baustein) NICHT – deren Anhang ist
    in beiden Fällen schon der eigentliche Aktivitätsinhalt (siehe
    filearea='content' in main.py), ein zusätzlicher Download-Link im
    Intro-Text wäre redundant.

    Gibt (bereinigtes HTML, eindeutige Anhänge, entfernte OLAT-interne
    Links, leere Unterordner-Pfade, Inhalts-Problem, Beschreibung als
    eigenes HTML) zurück – leere Unterordner-Pfade nur bei m_type='folder'
    befüllt, main.py legt dafür eigene Verzeichnis-Marker an (sonst zeigt
    Moodle den leeren Unterordner gar nicht erst an). Inhalts-Problem ist
    None im Normalfall, sonst ein kurzer Grund-String (z.B. fehlende
    referenzierte Datei) – main.py nutzt das, um den Baustein im
    Systemprotokoll als ❓ statt ✅ zu zählen. description_html ist nur bei
    m_type='page' befüllt, sonst immer leer (siehe oben).
    """
    ident = node.get('ident')
    html_content = ""
    attachments = []
    removed_links = []
    html_base_path = None
    reference_warning = ""

    html_file_param = node.get('html_file')
    if html_file_param:
        found_file = manifest.search_file(html_file_param)
        if found_file:
            if found_file["path"].endswith(('.html', '.htm')):
                html_content = found_file["data"].decode('utf-8-sig', errors='ignore')
                html_base_path = found_file["path"]
                # Wird Seitentext und landet nie als eigene Datei im Backup –
                # ohne diese Meldung gälte die Quelldatei als verwaist.
                manifest.consumed_content_paths.add(found_file["path"])
            else:
                attachments.append(
                    {"name": os.path.basename(html_file_param), "data": found_file["data"]})
                if found_file["path"].lower().endswith('.pdf') and m_type == "page":
                    # OLAT lässt eine Einzelseite direkt auf eine PDF (statt
                    # HTML) zeigen und stellt sie dann eingebettet/scrollbar
                    # dar, nicht als Download – dieselbe Erwartung soll auch
                    # in Moodle gelten, deshalb hier als <iframe> im
                    # Seiteninhalt statt als bloßer Anhang-Link (siehe
                    # _auto_embed weiter unten, der sonst greifen würde).
                    # Nur bei m_type='page': dessen Inhalt landet in <content>,
                    # und die Datei liegt unter component=mod_page/
                    # filearea='content' (siehe main.py) – GENAU dort löst
                    # @@PLUGINFILE@@ im Seiteninhalt auch auf. Bei 'resource'
                    # würde derselbe Verweis in <intro> landen, das aber eine
                    # ANDERE filearea ('intro') erwartet als die, unter der
                    # die Datei tatsächlich liegt ('content') – der Verweis
                    # ginge ins Leere und Moodle zeigt darin seine eigene
                    # "Datei nicht gefunden"-Seite an (verschachtelt im Kurs).
                    html_content = (
                        f'<iframe src="@@PLUGINFILE@@/{os.path.basename(html_file_param)}" '
                        f'style="{_PDF_EMBED_STYLE}"></iframe>'
                    )
        else:
            # Referenzierte Datei genannt, aber im Export nicht wiederzufinden –
            # sichtbar machen statt den Baustein stillschweigend leer zu lassen.
            fname = os.path.basename(html_file_param)
            print(f"[!] '{node.get('title', 'Unbenannt')}': referenzierte Datei "
                  f"'{fname}' nicht im Archiv gefunden – Inhalt fehlt.")
            reference_warning = MISSING_FILE_WARNING.format(filename=html_lib.escape(fname))

    rel_path_param = node.get('rel_path')
    if rel_path_param:
        attachments.extend(manifest.search_directory(rel_path_param))

    # Paket-Inhalte filtert get_node_assets() anhand der repo.zip-Grenze
    # selbst heraus, weil sie sonst zusätzlich zum Builder-Ergebnis als lose
    # Anhänge herauskämen. Ausgenommen sind Typen ohne eigenen Builder: dort
    # ist repo.zip die einzige Quelle (siehe PACKAGE_AS_ATTACHMENT_TYPES).
    node_html, node_assets = manifest.get_node_assets(
        ident, include_package_files=olat_type in PACKAGE_AS_ATTACHMENT_TYPES)
    if not html_content and node_html:
        html_content = node_html

    empty_dirs = []
    if m_type == "folder" and olat_type != "document":
        # Echter OLAT-Ordner-Baustein (bc/pf) – Inhalt liegt als echte
        # Unterordner-Struktur unter dem Knoten-Ident, siehe
        # get_node_folder_tree(). Ein 'document'-Baustein, der nur wegen
        # seines Office-Formats zum Ordner gewandelt wurde (siehe
        # main.py._resolve_moodle_type), hat dagegen gar keine solche
        # Struktur – seine eine Datei kam schon oben über html_file_param
        # in attachments, braucht hier keine zusätzliche Suche.
        folder_files, empty_dirs = manifest.get_node_folder_tree(ident)
        for folder_file in folder_files:
            attachments.append({"name": folder_file["name"], "relpath": folder_file["relpath"], "data": folder_file["data"]})
    else:
        attachments.extend(node_assets)

    # Alle aus HTML aufgelösten Dateien landen im selben Dateibereich dieses
    # Bausteins – Beschreibung und Seiteninhalt teilen sich deshalb EINE
    # Namensvergabe (siehe FileAreaNames).
    embedded_names = FileAreaNames()

    def _resolve_assets(asset_paths, html):
        """Löst im HTML gefundene Bild-/Medienverweise gegen das Manifest-VFS
        auf, hängt Treffer an attachments an und gibt das HTML mit ggf.
        umbenannten @@PLUGINFILE@@-Verweisen zurück – gemeinsam für
        Seiteninhalt und (bei m_type='page') separat sanitisierte
        Beschreibung, sonst würden Bilder AUS der Beschreibung nicht mehr in
        files.xml landen."""
        for asset_path in asset_paths:
            print(f"[DEBUG] Asset in HTML erkannt: {asset_path}")
            found_asset = manifest.search_file(asset_path, base_path=html_base_path)
            if not found_asset:
                print(f"[!] Eingebettete Datei '{asset_path}' nicht im Archiv gefunden – "
                      f"fehlt im Kursinhalt.")
                continue
            print(f"[DEBUG] Asset im Archiv gefunden: {found_asset['path']}")

            original = os.path.basename(asset_path)
            name, html = embedded_names.assign_in_html(original, found_asset["data"], html)
            if name != original:
                print(f"[*] Zwei verschiedene Dateien heißen '{original}' – die zweite "
                      f"wird als '{name}' übernommen.")
            attachments.append({"name": name, "data": found_asset["data"]})
        return html

    description = (node.get('description') or '').strip()
    description_html = ""
    if description and m_type == "page":
        description_html, desc_asset_paths, desc_removed_links = sanitize_for_moodle(description, link_map)
        removed_links.extend(desc_removed_links)
        description_html = _resolve_assets(desc_asset_paths, description_html)
    elif description:
        html_content = f"{description}{html_content}" if html_content else description

    if reference_warning:
        html_content = f"{reference_warning}{html_content}" if html_content else reference_warning

    if html_content:
        html_content, asset_paths, content_removed_links = sanitize_for_moodle(html_content, link_map)
        removed_links.extend(content_removed_links)
        html_content = _resolve_assets(asset_paths, html_content)
    else:
        html_content = ""

    if m_type == "page" and olat_type == "video" and not html_content:
        video_file = next(
            (attach for attach in attachments if attach['name'].lower().endswith(('.mp4', '.mov', '.webm', '.mkv'))),
            None)
        poster_file = next((attach for attach in attachments if attach['name'].lower() == 'poster.jpg'), None)
        if video_file:
            poster_attr = ' poster="@@PLUGINFILE@@/poster.jpg"' if poster_file else ''
            html_content = (
                f'<video controls{poster_attr} class="img-fluid" style="{_VIDEO_STYLE}">'
                f'<source src="@@PLUGINFILE@@/{video_file["name"]}"></video>'
            )

    # Dedup über (Unterordner, Dateiname). Bei gleichem Namen mit ABWEICHENDEM
    # Inhalt geht die zweite Datei verloren: das HTML verweist über
    # @@PLUGINFILE@@/<name> auf den Wurzelpfad des Dateibereichs, dort kann
    # der Name nur einmal vergeben sein. Umbenennen ginge erst, wenn
    # sanitize_for_moodle() pro Vorkommen zurückmeldet, welchen Verweis es
    # geschrieben hat – bis dahin wenigstens sichtbar melden statt still zu
    # überschreiben (gleiches Vorgehen wie bei den verwaisten Dateien in
    # main.py).
    unique_attachments = []
    seen_attachments = {}
    for attachment in attachments:
        key = (attachment.get("relpath", ""), attachment["name"])
        if key in seen_attachments:
            if seen_attachments[key]["data"] != attachment["data"]:
                print(f"[!] '{node.get('title')}': zwei verschiedene Dateien heißen "
                      f"'{attachment['name']}' – nur die erste wird übernommen, die "
                      f"zweite fehlt im Kurs.")
            continue
        seen_attachments[key] = attachment
        unique_attachments.append(attachment)

    if m_type not in ("folder", "resource"):
        html_content = _auto_embed(html_content, unique_attachments, m_type)

    content_issue = "Referenzierte Datei fehlt" if reference_warning else None
    return html_content, unique_attachments, removed_links, empty_dirs, content_issue, description_html


def with_password_warning(html: str, node: dict) -> str:
    """Stellt dem Inhalt den Warnhinweis voran, wenn dieser Knoten in OLAT das
    Passwort gesetzt hat (nicht bei den Knoten darunter, die es nur erben –
    die tragen ausschließlich die Titel-Markierung, sonst stünde derselbe
    Absatz in jedem Baustein des Teilbaums)."""
    if not node.get('defines_password'):
        return html
    return PASSWORD_LOST_WARNING + (html or "")
