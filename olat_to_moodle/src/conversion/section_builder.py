"""Verwaltet die komplette Section-/Subsection-/Sammel-Bucket-Struktur eines
Kurslaufs: welche Moodle-section_id ein Baustein anhand seiner Struktur-
Knoten-Kette bekommt, und wann ein Knoten stattdessen selbst eine neue
Top-Level-Section oder Subsection öffnet (siehe main.py, das pro Knoten
entscheidet, WELCHE der drei Methoden hier zutrifft).

Modul-/Kontext-IDs für Subsection-Aktivitäten werden bewusst NICHT hier
vergeben, sondern von main.py übergeben - die teilen sich denselben
Nummernkreis wie alle anderen Aktivitäten im Kurslauf (next_free_module_id/
context_id_counter dort), eine eigene Zählung hier würde Kollisionen riskieren.
"""

import os
import shutil

from conversion.file_manager import write_xml
from conversion.moodle_xml import modify_module_xml, modify_subsection_xml
from config import UNGROUPED_SECTION_MARKER, UNGROUPED_SECTION_TITLE


class SectionBuilder:
    """Hält den gesamten Section-State EINES Kurslaufs (nicht wiederverwendbar
    über mehrere Läufe hinweg - main.py legt pro Aufruf von
    convert_olat_to_moodle() eine neue Instanz an)."""

    def __init__(self, temp_dir: str, template_mapping: dict, now: int):
        self.temp_dir = temp_dir
        self.template_mapping = template_mapping
        self.now = now

        self.sections: dict = {}
        # OLAT-STCourseNode-Ident → Moodle-section_id, die dieser Struktur-
        # Knoten öffnet (siehe parent_st_idents in olat_parser.py).
        self.st_section_map: dict = {}

        # Startet bei -1 statt 0: die allererste im Kurslauf erzeugte Section
        # bekommt so Nummer 0 (Moodles zwingend vorhandene, nicht löschbare
        # "Allgemeines"-Section) statt dass Moodle beim Restore mangels
        # gelieferter Section 0 selbst eine leere "Allgemeines"-Section
        # ergänzt - das erzeugt sonst einen leeren, unlöschbaren Wrapper
        # zusätzlich zu unserer ersten echten Section.
        self.next_section_id = -1

        # Eigener, weit entfernter Nummernkreis für Unterabschnitte (Moodle-
        # course_sections.section, das <number> in section.xml) - getrennt vom
        # Nummernkreis der normalen Abschnitte oben. Grund: Moodles eigenes
        # Restore verschiebt JEDEN Unterabschnitt beim Wiederherstellen ohnehin
        # ans Ende der Abschnitts-Reihenfolge (restore_section_structure_step::
        # process_section() in Moodle-Core setzt section->section komplett neu,
        # unsere <number> wird für Unterabschnitte also nie übernommen) - liegt
        # eine Unterabschnitts-Nummer aber ZWISCHEN zwei normalen Abschnitten
        # (z.B. Abschnitt 5, Unterabschnitt 6, Abschnitt 7), reißt das Verschieben
        # eine Lücke in die normale Abschnittsfolge, die Moodle danach mit
        # leeren "Neuer Abschnitt"-Plätzen auffüllt - genau die Lücken, die wir
        # in echten Kursen gesehen haben. Mit einem eigenen, weit über der
        # normalen Abschnittszahl liegenden Nummernkreis für Unterabschnitte
        # bleibt die normale Abschnittsfolge lückenlos, egal wie viele
        # Unterabschnitte dazwischen "eigentlich" lägen.
        self.next_subsection_id = 10_000
        self.subsection_instance_counter = 0

        self.current_bucket_section_id = None
        self.bucket_counter = 0

    def _get_or_create_current_bucket(self) -> int:
        """Sammel-Abschnitt für Bausteine ohne umschließenden Struktur-Knoten.

        Wird nicht dauerhaft wiederverwendet: open_top_section() setzt
        current_bucket_section_id auf None zurück, damit lose Bausteine VOR
        und NACH einer echten Struktur in getrennten, durchnummerierten
        Sammlungen landen (#1, #2, ...) statt alle in einer einzigen, an der
        falschen Stelle im Kurs wirkenden Sammlung gebündelt zu werden."""
        if self.current_bucket_section_id is None:
            self.bucket_counter += 1
            self.next_section_id += 1
            self.current_bucket_section_id = self.next_section_id
            self.sections[self.current_bucket_section_id] = {
                "id": self.current_bucket_section_id,
                "title": f"{UNGROUPED_SECTION_MARKER} {UNGROUPED_SECTION_TITLE} "
                         f"#{self.bucket_counter} {UNGROUPED_SECTION_MARKER}",
                "module_ids": [],
                "component": None, "itemid": None, "parentcmid": None, "modname": None, "summary": "",
            }
        return self.current_bucket_section_id

    def resolve_target_section(self, parent_st_idents) -> int:
        """Ermittelt die Moodle-section_id, in die ein Baustein anhand seiner
        umschließenden Struktur-Knoten-Kette gehört (siehe st_section_map)."""
        if not parent_st_idents:
            return self._get_or_create_current_bucket()
        target = self.st_section_map.get(parent_st_idents[-1])
        return target if target is not None else self._get_or_create_current_bucket()

    def open_top_section(self, node: dict) -> int:
        """Öffnet eine neue echte Top-Level-Section für einen Top-Level-
        Struktur-Knoten (jeder 'st'-Knoten ohne parent_st_idents, auch ganz
        ohne Kinder). Setzt den aktuellen Sammel-Bucket zurück, damit lose
        Bausteine danach in einer frischen, neu nummerierten Sammlung landen.

        Befüllt NICHT die Beschreibung (summary) - das braucht main.py's
        eigene build_node_content()/file_mgr-Aufrufe (Bild-Anhänge etc.),
        siehe set_section_summary()."""
        self.next_section_id += 1
        new_section_id = self.next_section_id
        self.sections[new_section_id] = {
            "id": new_section_id, "title": node.get('title', f'Abschnitt {new_section_id}'),
            "module_ids": [], "component": None, "itemid": None,
            "parentcmid": None, "modname": None, "summary": "",
        }
        self.st_section_map[node['ident']] = new_section_id
        self.current_bucket_section_id = None
        return new_section_id

    def set_section_summary(self, section_id: int, summary_html: str) -> None:
        """Trägt die (separat aufbereitete) Beschreibung eines Top-Level-
        Struktur-Knotens in dessen Section ein - siehe open_top_section()."""
        self.sections[section_id]["summary"] = summary_html

    def open_subsection(self, node: dict, node_title: str, olat_type: str,
                        parent_st_idents, subsection_module_id: int, context_id: int):
        """Öffnet eine neue Moodle-Subsection (mod_subsection, Core seit
        Moodle 4.4) - sowohl für echtes st-in-st als auch für einen
        has_children-Knoten ohne eigenen Struktur-Typ (z.B. eine Einzelseite
        mit echten Unterseiten). Die Aktivität selbst liegt im
        umschließenden Abschnitt, der neue Abschnitt ist über
        component/itemid mit ihr verknüpft (siehe xml_generator.
        generate_section_xml) - technisch bleiben alle Abschnitte eine
        flache Liste, Moodle zeigt sie nur optisch eingerückt an.

        subsection_module_id/context_id kommen von main.py (gemeinsamer
        Nummernkreis mit allen anderen Aktivitäten, siehe Moduldocstring).

        Gibt (neue section_id, Elternabschnitt-section_id, Subsection-Titel)
        zurück - main.py braucht alle drei für processed_activities/
        current_target_section_id."""
        self.next_subsection_id += 1
        new_section_id = self.next_subsection_id
        self.subsection_instance_counter += 1
        # Generisch statt st_section_map[parent_st_idents[0]]: der
        # Elternabschnitt kann auch die aktuelle Sammlung sein (siehe
        # has_children-Knoten ohne eigenen 'st'-Typ, z.B. eine Einzelseite
        # mit echten Unterseiten direkt auf Kursebene).
        parent_section_id = self.resolve_target_section(parent_st_idents)

        if olat_type == 'st':
            # Echtes st-in-st: der Name der Struktur selbst reicht als
            # Subsection-Titel, das IST schließlich die vom Kursautor
            # angelegte Struktur.
            subsection_title = node_title
            section_display_title = node.get('title', f'Unterabschnitt {new_section_id}')
        else:
            # has_children-Knoten OHNE eigenen Struktur-Typ (z.B. eine
            # Einzelseite mit echten Unterseiten) - "UNTERABSCHNITT: "
            # macht sichtbar, dass diese Subsection technisch erzeugt
            # wurde und keine vom Kursautor angelegte Struktur ist.
            subsection_title = f'UNTERABSCHNITT: "{node_title}"'
            section_display_title = f'UNTERABSCHNITT: "{node.get("title", f"Unterabschnitt {new_section_id}")}"'

        sub_a_path = os.path.join(self.temp_dir, "activities", f"subsection_{subsection_module_id}")
        shutil.copytree(self.template_mapping["subsection"], sub_a_path)
        modify_module_xml(os.path.join(sub_a_path, "module.xml"),
                          subsection_module_id, parent_section_id, self.now)
        modify_subsection_xml(os.path.join(sub_a_path, "subsection.xml"),
                              self.subsection_instance_counter, subsection_module_id,
                              context_id, subsection_title, self.now)
        os.makedirs(os.path.join(self.temp_dir, "contexts", f"context_{context_id}"), exist_ok=True)
        write_xml(os.path.join(self.temp_dir, "contexts", f"context_{context_id}", "context.xml"),
                  f'<context id="{context_id}" contextlevel="70" '
                  f'instanceid="{subsection_module_id}"></context>')

        self.sections[new_section_id] = {
            "id": new_section_id, "title": section_display_title,
            "module_ids": [], "component": "mod_subsection", "itemid": self.subsection_instance_counter,
            "parentcmid": subsection_module_id, "modname": "subsection", "summary": "",
        }
        self.sections[parent_section_id]["module_ids"].append(subsection_module_id)
        self.st_section_map[node['ident']] = new_section_id

        return new_section_id, parent_section_id, subsection_title

    def append_module(self, section_id: int, module_id: int) -> None:
        """Hängt eine Aktivität ans Ende der Modul-Sequenz einer Section an."""
        self.sections[section_id]["module_ids"].append(module_id)

    def create_section(self, title: str) -> int:
        """Öffnet eine schlichte, inhaltsleere Top-Level-Section mit
        gegebenem Titel - für main.py's Systemprotokoll-Abschnitt am Ende
        des Kurslaufs, der an keinem OLAT-Knoten hängt."""
        self.next_section_id += 1
        section_id = self.next_section_id
        self.sections[section_id] = {
            "id": section_id, "title": title,
            "module_ids": [], "component": None, "itemid": None,
            "parentcmid": None, "modname": None,
        }
        return section_id
