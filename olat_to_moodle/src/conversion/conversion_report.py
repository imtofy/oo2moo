"""Baut das Systemprotokoll (den Konvertierungsbericht) am Ende jedes
konvertierten Kurses: Symbol-Legende, ✅-Erfolgstabelle, ⚠️/❓-Warnungen,
🔀-Markierungen für zu tief verschachtelte Struktur und den Ordner mit
verwaisten Dateien. Reine Report-Formatierung – main.py liefert nur die
gesammelten Daten (transferred_elements, skipped_elements, ...) rein.
"""
import os
import shutil
import urllib.parse
import html as html_lib

from config import (OLAT_NAMES, UNSUPPORTED_TYPE_HELP_LINKS, UNSUPPORTED_TYPE_REASONS, MOODLE_MODULE_NAMES,
                    SUCCESS_SYMBOL, WARNING_SYMBOL, UNRECOGNIZED_TYPE_MARKER,
                    FLATTENED_BOUNDARY_MARKER, FLATTENED_CHILD_MARKER,
                    SYMBOL_COLORS, SYMBOL_LEGEND_TEXT, NEUTRAL_COLORS, LINK_COLOR,
                    ORPHAN_INTERNAL_SUBFOLDER, ORPHAN_INTERNAL_EXTS)
from .moodle_xml import modify_activity_xml, modify_module_xml, rewrite_inforef_xml
from .file_manager import write_activity_context


def _build_symbol_legend_html(active_symbols):
    """Baut die Erklär-Kästen für die Symbole, die in DIESEM Bericht tatsächlich
    vorkommen (keine Legende für Symbole zeigen, die der Kurs nicht auslöst)."""
    if not active_symbols:
        return ""
    n = len(active_symbols)
    width = 100 / n - 2
    boxes = []
    for idx, symbol in enumerate(active_symbols):
        name, desc = SYMBOL_LEGEND_TEXT[symbol]
        bg, border, accent = SYMBOL_COLORS[symbol]
        margin = "" if idx == n - 1 else "margin-right:2%;"
        boxes.append(
            f'<div style="float:left; width:{width:.1f}%; {margin}'
            f'background-color:{bg}; border:1px solid {border}; border-left:4px solid {accent}; '
            f'border-radius:6px; padding:9px 10px;">'
            f'<div style="font-size:17px; line-height:1;">{symbol}</div>'
            f'<div style="font-size:12px; font-weight:700; margin-top:4px;">{html_lib.escape(name)}</div>'
            f'<div style="font-size:11px; color:#6b7280; margin-top:2px;">{html_lib.escape(desc)}</div>'
            f'</div>')
    return (f'<p><strong>Zeichenerklärung:</strong> diese Symbole tauchen im Kurs und in dieser '
            f'Übersicht auf:</p><div style="overflow:hidden; margin:0 0 18px;">{"".join(boxes)}</div>')


def build_unsupported_placeholder_html(olat_type):
    """Baut den Inhalt der ⚠️-Warn-Platzhalterseite für einen OLAT-Bausteintyp
    aus SKIPPED_OLAT_TYPES – ersetzt an dessen Original-Position im Kurs den
    sonst komplett fehlenden Baustein, ergänzt um einen Hilfe-Link, falls in
    UNSUPPORTED_TYPE_HELP_LINKS einer hinterlegt ist.

    Der Grund steht je Typ in UNSUPPORTED_TYPE_REASONS: pauschal "braucht ein
    Plugin" wäre falsch, mod_lti und mod_h5pactivity sind Moodle-Core – dort
    scheitert es an der Konfiguration bzw. am Inhalt, nicht am fehlenden
    Modul."""
    label = OLAT_NAMES.get(olat_type, olat_type)
    reason = UNSUPPORTED_TYPE_REASONS.get(
        olat_type, 'Für diesen Bausteintyp gibt es in Moodle keine Entsprechung.')
    html = (f'<p><strong>{WARNING_SYMBOL} Dieser Baustein ({html_lib.escape(label)}) konnte nicht '
            f'automatisch nach Moodle übertragen werden.</strong></p>'
            f'<p>{html_lib.escape(reason)} Er muss bei Bedarf manuell neu angelegt werden.</p>')
    help_link = UNSUPPORTED_TYPE_HELP_LINKS.get(olat_type)
    if help_link:
        html += (f'<p><a href="{html_lib.escape(help_link)}" target="_blank">'
                 f'Hilfe zu diesem Bausteintyp</a></p>')
    return html


def build_flattened_boundary_html():
    """Inhalt der 🔀-Markierungsseite für einen zu tief verschachtelten Struktur-
    Knoten (MAX_SECTION_DEPTH) – ersetzt den fehlenden eigenen Moodle-Abschnitt.
    Bekommt eine 'page' statt (wie normale Struktur-Knoten) ein 'label', weil
    label-Aktivitäten in Moodle keine eigene View-Seite haben (has_view() ==
    false) und deshalb vom Systemprotokoll aus nicht verlinkt werden könnten."""
    return (f'<p><strong>{FLATTENED_BOUNDARY_MARKER} Dies war ein eigener Abschnitt im '
            f'OLAT-Kurs.</strong></p>'
            f'<p>Er lag tiefer verschachtelt, als Moodle abbilden kann (nur Abschnitt + '
            f'Unterabschnitt), und wurde deshalb hier eingefügt. Die folgenden, mit '
            f'{FLATTENED_CHILD_MARKER} markierten Bausteine gehörten in OLAT zu diesem '
            f'Abschnitt.</p>')


def write_protocol_activities(temp_dir, template_mapping, file_mgr, sections,
                               processed_activities, skipped_elements, orphaned_files,
                               removed_links_log, flattened_structures, transferred_elements,
                               total_content_count, section_id, next_module_id,
                               next_context_id, now):
    """Schreibt das Systemprotokoll als eigene Kurs-Sektion ans Kursende.

    Baut zwei Aktivitäten, jeweils nur falls es etwas zu berichten gibt:
      1. Eine Seite, die mit der ✅-Erfolgsmeldung + Tabelle beginnt (wie viele
         von wie vielen Kurselementen sauber übertragen wurden, mit OLAT-Typ/
         -Name und Moodle-Äquivalent/-Name je Zeile), gefolgt von nicht
         übernommenen Bausteinen (die zusätzlich auch als ⚠️-Warn-Platzhalter
         an Ort und Stelle im Kurs stehen, siehe convert_olat_to_moodle), zu
         tief verschachtelten Struktur-Elementen und entfernten OLAT-internen
         Links, in <details open>-Gruppen statt einer langen flachen Liste.
      2. Ein Ordner-Modul mit allen verwaisten Dateien (Moodle zeigt
         Ordnerinhalte nativ an, ersetzt eine sonst nötige HTML-Linkliste).
         Ohne folder-Template stattdessen eine Linkliste auf einer Seite.
    Die innere _write_activity() erledigt für beide das gemeinsame Muster
    (Kontext anlegen, Template kopieren, module/activity/inforef patchen)
    und zählt module_id/context_id danach hoch.
    """
    module_id = next_module_id
    context_id = next_context_id

    def _write_activity(m_type, title, html_content, activity_file_ids, collapsed=False):
        """Baut eine einzelne Aktivität aus dem passenden Template und trägt
        sie in Sektion und Buchhaltung (sections/processed_activities) ein.

        collapsed=True klappt einen Ordner im Kurs zu (showexpanded=0) – bei
        vielen Dateien wäre die aufgeklappte Liste sonst länger als der
        gesamte übrige Kurs."""
        nonlocal module_id, context_id
        write_activity_context(temp_dir, context_id, module_id)
        a_path = os.path.join(temp_dir, "activities", f"{m_type}_{module_id}")
        shutil.copytree(template_mapping[m_type], a_path)
        modify_module_xml(os.path.join(a_path, "module.xml"), module_id, section_id, now)
        modify_activity_xml(os.path.join(a_path, f"{m_type}.xml"), m_type, module_id,
                            context_id, title, now, "summary", False, html_content, "")
        if collapsed:
            activity_path = os.path.join(a_path, f"{m_type}.xml")
            content = open(activity_path, encoding="utf-8").read()
            open(activity_path, "w", encoding="utf-8", newline="").write(
                content.replace("<showexpanded>1</showexpanded>",
                                "<showexpanded>0</showexpanded>", 1))
        rewrite_inforef_xml(os.path.join(a_path, "inforef.xml"), activity_file_ids)
        sections[section_id]["module_ids"].append(module_id)
        processed_activities.append((module_id, m_type, section_id, title))
        module_id += 1
        context_id += 1

    if (skipped_elements or removed_links_log or flattened_structures
            or transferred_elements) and "page" in template_mapping:
        html = ""

        active_symbols = []
        if transferred_elements:
            active_symbols.append(SUCCESS_SYMBOL)
        active_symbols += [symbol for symbol in (WARNING_SYMBOL, UNRECOGNIZED_TYPE_MARKER)
                          if any(el.get('symbol') == symbol for el in skipped_elements)]
        if flattened_structures:
            active_symbols += [FLATTENED_BOUNDARY_MARKER, FLATTENED_CHILD_MARKER]
        html += _build_symbol_legend_html(active_symbols)

        if transferred_elements:
            def _transferred_row(el):
                """Baut eine Tabellenzeile für einen erfolgreich übertragenen Baustein."""
                olat_label = html_lib.escape(OLAT_NAMES.get(el['olat_type'], el['olat_type']))
                moodle_label = html_lib.escape(MOODLE_MODULE_NAMES.get(el['moodle_type'], el['moodle_type']))
                olat_name = html_lib.escape(el['olat_name'])
                moodle_name = html_lib.escape(el['moodle_name'])
                if el.get('link'):
                    moodle_name = f'<a href="{el["link"]}" style="color:{LINK_COLOR};">{moodle_name}</a>'
                cell = 'padding:6px 10px; border-bottom:1px solid #e5e7eb;'
                return (f'<tr><td style="{cell}">{olat_label}</td><td style="{cell}">{olat_name}</td>'
                        f'<td style="{cell}">{moodle_label}</td><td style="{cell}">{moodle_name}</td></tr>')

            head_cell = 'text-align:left; padding:6px 10px; border-bottom:2px solid #b7dfc4;'
            header_row = (f'<tr style="background-color:#e8f5ec;">'
                          f'<th style="{head_cell}">OLAT-Baustein</th><th style="{head_cell}">Name in OLAT</th>'
                          f'<th style="{head_cell}">Moodle-Äquivalent</th><th style="{head_cell}">Name in Moodle</th></tr>')

            # Nur die ersten visible_rows sofort sichtbar – Moodle-Content
            # erlaubt kein <script>, also kein JS-"Mehr anzeigen"-Knopf. Ein
            # zweites <details> als Fortsetzung erreicht dieselbe UX rein mit
            # HTML (dieselbe Technik wie bei den Fehler-Gruppen unten).
            visible_rows = 8
            sorted_elements = sorted(transferred_elements, key=lambda element: (element['olat_type'], element['olat_name']))
            visible, rest = sorted_elements[:visible_rows], sorted_elements[visible_rows:]
            table_margin = "10px" if rest else "20px"

            visible_rows_html = "".join(_transferred_row(el) for el in visible)
            rest_rows_html = "".join(_transferred_row(el) for el in rest)

            html += (f'<p><strong>{SUCCESS_SYMBOL} {len(transferred_elements)} von '
                     f'{total_content_count}</strong> Kurselementen wurden erfolgreich übertragen:</p>'
                     f'<div style="overflow:auto;"><table style="width:100%; border-collapse:collapse; '
                     f'margin:0 0 {table_margin};">{header_row}'
                     f'{visible_rows_html}</table></div>')

            if rest:
                html += (f'<details style="margin:0 0 20px;"><summary style="cursor:pointer; font-size:14px; '
                         f'color:#1e7d3c;">+ {len(rest)} weitere anzeigen</summary>'
                         f'<div style="overflow:auto; margin-top:8px;"><table style="width:100%; '
                         f'border-collapse:collapse;">{header_row}'
                         f'{rest_rows_html}</table></div></details>')

            # Gegencheck: die tatsächlich im HTML gerenderten Zeilen zählen
            # (statt der Liste zu vertrauen, aus der sie gebaut wurden) und mit
            # der Zahl im Fließtext vergleichen. Fängt Render-Bugs ab (z.B.
            # Slicing-/Dedup-Fehler bei visible/rest), die eine reine
            # len(transferred_elements)-Prüfung nicht sehen würde, weil sie
            # dieselbe Quelle nochmal abfragen würde statt das Ergebnis zu prüfen.
            _rendered_rows = visible_rows_html.count('<tr><td') + rest_rows_html.count('<tr><td')
            if _rendered_rows != len(transferred_elements):
                print(f"[!] WARNUNG: Im Systemprotokoll tatsächlich gerenderte Erfolgs-Zeilen "
                      f"({_rendered_rows}) stimmen nicht mit der erfassten Anzahl "
                      f"({len(transferred_elements)}) überein – Render-Logik in "
                      f"write_protocol_activities prüfen, BEVOR diese .mbz verwendet wird.")

        if skipped_elements:
            def _skipped_item(el):
                """Baut einen Listeneintrag für ein übersprungenes/nicht übertragenes Element."""
                text = html_lib.escape(el['title'])
                prefix = f"{el['symbol']} " if el.get('symbol') else ""
                if el.get('link'):
                    return f'<li style="margin-bottom:4px;"><a href="{el["link"]}" style="color:{LINK_COLOR};">{prefix}{text}</a></li>'
                return f'<li style="margin-bottom:4px;">{prefix}{text}</li>'

            def _group_block(type_key, entries):
                """Baut die farbige <details>-Box für eine Gruppe gleichartiger
                übersprungener Bausteine (gleicher OLAT-Typ + gleicher Grund)."""
                base_type = type_key.split(',')[0].strip()
                label = OLAT_NAMES.get(base_type, base_type)
                reason = type_key[len(base_type):].lstrip(', ')
                head = label + (f" – {reason}" if reason else "")
                group_items_html = "".join(_skipped_item(el) for el in entries)
                group_symbol = entries[0].get('symbol')
                group_bg, group_border, group_accent = SYMBOL_COLORS.get(group_symbol, NEUTRAL_COLORS)
                symbol_prefix = f"{group_symbol} " if group_symbol else ""
                return (f'<details open style="background-color:{group_bg}; border:1px solid {group_border}; '
                        f'border-left:4px solid {group_accent}; border-radius:6px; padding:10px 14px; margin:0 0 10px;">'
                        f'<summary style="cursor:pointer; font-size:14px;">{symbol_prefix}<strong>'
                        f'{html_lib.escape(head)}</strong> – {len(entries)} Baustein(e)</summary>'
                        f'<ul style="margin:10px 0 2px; padding-left:20px;">{group_items_html}</ul></details>')

            groups = {}
            for el in skipped_elements:
                groups.setdefault(el['type'], []).append(el)

            # ⚠️ ("fehlt komplett") und ❓ ("übernommen, aber fraglich") sind
            # zwei inhaltlich verschiedene Aussagen – getrennt in eigenen
            # Abschnitten ausgeben statt alphabetisch quer durcheinander,
            # sonst verwischt genau der Unterschied, den die Symbole eigentlich
            # markieren sollen. 'sonstige_keys' fängt die seltenen Fälle ohne
            # eines der beiden Symbole ab (z.B. "Template fehlt",
            # "Konvertierungsfehler" – main.py setzt dort kein 'symbol').
            warning_keys = sorted(group_key for group_key in groups if groups[group_key][0].get('symbol') == WARNING_SYMBOL)
            question_keys = sorted(group_key for group_key in groups
                                   if groups[group_key][0].get('symbol') == UNRECOGNIZED_TYPE_MARKER)
            sonstige_keys = sorted(group_key for group_key in groups if group_key not in warning_keys and group_key not in question_keys)

            # Bei vielen unterschiedlichen Gruppen (Typ+Grund-Kombination) erschlagen
            # zu viele gleichzeitig aufgeklappte Boxen die Seite – dieselbe
            # Show-more-Technik wie bei der ✅-Tabelle oben (visible_rows): nur
            # die ersten visible_groups pro Abschnitt direkt offen sichtbar, der
            # Rest hinter einem zusätzlichen Sammel-<details>.
            visible_groups = 3

            def _render_section(keys):
                """Baut die Boxen für eine Liste von Gruppen-Keys, inkl. Show-more
                ab dem visible_groups-ten Eintrag."""
                visible_keys, rest_keys = keys[:visible_groups], keys[visible_groups:]
                out = "".join(_group_block(group_key, groups[group_key]) for group_key in visible_keys)
                if rest_keys:
                    rest_html = "".join(_group_block(group_key, groups[group_key]) for group_key in rest_keys)
                    rest_count = sum(len(groups[group_key]) for group_key in rest_keys)
                    out += (f'<details style="margin:0 0 10px;"><summary style="cursor:pointer; '
                            f'font-size:14px; color:#8a6a12;">+ {len(rest_keys)} weitere Gruppen '
                            f'anzeigen ({rest_count} Baustein(e))</summary>'
                            f'<div style="margin-top:8px;">{rest_html}</div></details>')
                return out

            if warning_keys:
                warning_count = sum(len(groups[group_key]) for group_key in warning_keys)
                html += (f"<p>{WARNING_SYMBOL} <strong>{warning_count}</strong> Bausteine fehlen "
                         f"komplett (kein Moodle-Äquivalent, muss von Hand nachgebaut werden):</p>")
                html += _render_section(warning_keys)

            if question_keys:
                question_count = sum(len(groups[group_key]) for group_key in question_keys)
                html += (f"<p>{UNRECOGNIZED_TYPE_MARKER} <strong>{question_count}</strong> Bausteine "
                         f"wurden übernommen, der Inhalt ist aber fraglich (bitte gegenprüfen – "
                         f"Links führen, wo vorhanden, direkt zur Aktivität im Kurs):</p>")
                html += _render_section(question_keys)

            if sonstige_keys:
                sonstige_count = sum(len(groups[group_key]) for group_key in sonstige_keys)
                html += (f"<p><strong>{sonstige_count}</strong> weitere Bausteine konnten nicht "
                         f"übernommen werden:</p>")
                html += _render_section(sonstige_keys)

            html += ("<p>Diese Elemente müssen ggf. manuell neu angelegt werden "
                     "(z.B. SCORM/LTI/CP/H5P) oder waren bereits in OLAT "
                     "gelöscht/unbenannt.</p>")

        if removed_links_log:
            total_links = sum(len(entry['links']) for entry in removed_links_log)
            bg, border, accent = NEUTRAL_COLORS
            html += (f'<h3 style="font-size:16px; margin:24px 0 10px;">Entfernte OLAT-interne Links</h3>'
                     f"<p><strong>{total_links}</strong> Link(s) zeigten auf das alte "
                     f"OLAT-System (/auth/…) und wären in Moodle tot gewesen. Der "
                     f"Linktext blieb als normaler Text erhalten. Bei Bedarf in Moodle "
                     f"neu auf das passende Kurselement verlinken:</p>")
            for entry in removed_links_log:
                items = "".join(
                    f'<li style="margin-bottom:4px;">„{html_lib.escape(link["text"] or "(ohne Linktext)")}“ '
                    f'<small style="color:#6b7280;">({html_lib.escape(link["href"])})</small></li>'
                    for link in entry['links'])
                html += (f'<details open style="background-color:{bg}; border:1px solid {border}; '
                         f'border-left:4px solid {accent}; border-radius:6px; padding:10px 14px; margin:0 0 10px;">'
                         f'<summary style="cursor:pointer; font-size:14px;"><strong>'
                         f'{html_lib.escape(entry["title"])}</strong> – {len(entry["links"])} Link(s)</summary>'
                         f'<ul style="margin:10px 0 2px; padding-left:20px;">{items}</ul></details>')

        if flattened_structures:
            def _flattened_item(entry):
                """Baut einen Listeneintrag für ein zu tief verschachteltes Struktur-Element."""
                text = html_lib.escape(entry['location'])
                if entry.get('link'):
                    return (f'<li style="margin-bottom:4px;"><a href="{entry["link"]}" '
                           f'style="color:{LINK_COLOR};">{FLATTENED_BOUNDARY_MARKER} {text}</a></li>')
                return f'<li style="margin-bottom:4px;">{FLATTENED_BOUNDARY_MARKER} {text}</li>'

            items = "".join(_flattened_item(entry) for entry in flattened_structures)
            bg, border, accent = SYMBOL_COLORS[FLATTENED_BOUNDARY_MARKER]
            html += (f'<h3 style="font-size:16px; margin:24px 0 10px;">Zu tief verschachtelte Struktur</h3>'
                     f"<p><strong>{len(flattened_structures)}</strong> Struktur-Element(e) waren "
                     f"tiefer als 2 Ebenen verschachtelt (Moodle unterstützt nur Abschnitt + "
                     f"Unterabschnitt) und wurden in den umschließenden Abschnitt integriert "
                     f"(dort erkennbar am {FLATTENED_BOUNDARY_MARKER}-Symbol, seine Inhalte am "
                     f"{FLATTENED_CHILD_MARKER}-Symbol). Bitte prüfen, ob die entstandene, "
                     f"flachere Struktur so passt:</p>"
                     f'<details open style="background-color:{bg}; border:1px solid {border}; '
                     f'border-left:4px solid {accent}; border-radius:6px; padding:10px 14px; margin:0 0 10px;">'
                     f'<summary style="cursor:pointer; font-size:14px;">{FLATTENED_BOUNDARY_MARKER} '
                     f'<strong>Betroffene Abschnitte</strong> '
                     f'– {len(flattened_structures)} Element(e)</summary>'
                     f'<ul style="margin:10px 0 2px; padding-left:20px;">{items}</ul></details>')

        _write_activity("page", "Systemprotokoll: Konvertierungsbericht", html, [])

    if orphaned_files:
        if "folder" in template_mapping:
            file_ids = [file_mgr.add_moodle_directory(context_id, "mod_folder", "content", 0, now)]
            # OLATs interne XML wandert in einen eigenen Unterordner: sie
            # gehört zur Vollständigkeit, ist aber nichts, was jemand von Hand
            # weiterverwendet – im selben Verzeichnis verdeckt sie die Dateien,
            # die man wirklich sichten will.
            internal = [(name, data) for name, data in orphaned_files.items()
                        if name.lower().endswith(ORPHAN_INTERNAL_EXTS)]
            if internal:
                file_ids.append(file_mgr.add_moodle_directory(
                    context_id, "mod_folder", "content", 0, now,
                    filepath=f"/{ORPHAN_INTERNAL_SUBFOLDER}/"))
            for fname, fdata in sorted(orphaned_files.items(), key=lambda kv: kv[0].lower()):
                is_internal = fname.lower().endswith(ORPHAN_INTERNAL_EXTS)
                file_ids.append(file_mgr.add_moodle_file(
                    source_content=fdata, filename=fname, contextid=context_id,
                    component="mod_folder", filearea="content", itemid=0, now=now,
                    filepath=f"/{ORPHAN_INTERNAL_SUBFOLDER}/" if is_internal else "/"))
            intro = ("<p>Diese Dateien lagen im OLAT-Kursordner, wurden aber von keinem "
                     "Baustein referenziert (z.B. ehemalige Forumsanhänge). Bitte sichten "
                     "und bei Bedarf den passenden Aktivitäten zuordnen.</p>")
            _write_activity("folder", "Systemprotokoll: Verwaiste Dateien", intro, file_ids,
                            collapsed=True)
        elif "page" in template_mapping:
            file_ids = [file_mgr.add_moodle_directory(context_id, "mod_page", "content", 0, now)]
            html = "<h3>Verwaiste Dateien</h3><ul>"
            for fname, fdata in sorted(orphaned_files.items(), key=lambda kv: kv[0].lower()):
                file_ids.append(file_mgr.add_moodle_file(
                    source_content=fdata, filename=fname, contextid=context_id,
                    component="mod_page", filearea="content", itemid=0, now=now))
                plugin_ref = f"@@PLUGINFILE@@/{urllib.parse.quote(fname)}"
                html += f'<li><a href="{plugin_ref}" target="_blank">{html_lib.escape(fname)}</a></li>'
            html += "</ul>"
            _write_activity("page", "Systemprotokoll: Verwaiste Dateien", html, file_ids)
