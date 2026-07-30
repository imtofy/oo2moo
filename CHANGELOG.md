# Changelog

## Unreleased

### Hinzugefügt

- Wiki-Baustein mit echten Seiten: OLATs Wiki-Paket wird über `repo.zip` ausgelesen, die MediaWiki-artige Syntax zu HTML konvertiert.
- Kalender-Baustein wird als echter Moodle-Kalender-Block in der Kurs-Seitenleiste angelegt (OLAT kennt dafür keine Aktivität).
- Section-Struktur überarbeitet: jeder Top-Level-Struktur-Baustein wird konsequent zu einer echten Section, auch ohne Kinder. Lose Bausteine landen in durchnummerierten "Sammlung aller Bausteine #N"-Abschnitten statt in einem einzigen "Allgemein".
- Unit-Test-Suite (pytest) für alle Kernmodule, inklusive absichtlich fehlerhafter Eingaben (kaputtes ZIP, fehlende XML-Felder etc.) zur Prüfung der Fehlerbehandlung.

### Behoben

- `has_children` falsch erkannt: OLAT schreibt `<children>` für jeden Knoten, auch leer als `<children/>` – Ordner/PDF-Seiten wurden dadurch fälschlich als eigene Section behandelt.
- Leere Struktur-Bausteine fielen fälschlich in die "zu tief verschachtelt"-Behandlung statt eine eigene, wenn auch leere Section zu bekommen.
- `<intro>` (Info-Block) und `<content>` (echter Seiteninhalt) bei Seiten-Aktivitäten werden jetzt sauber getrennt – vorher landete die OLAT-Beschreibung fälschlich im Seiteninhalt.
- OLAT-Emoticons (transparent.gif-Platzhalter) werden entfernt statt einen nie auflösbaren Dateiverweis zu hinterlassen.
- Section-Nummerierung startet bei 0 statt 1 – sonst legt Moodle beim Restore mangels gelieferter Section 0 selbst eine leere, unlöschbare "Allgemeines"-Section an.
- Subsection-Beschreibung bleibt als Label-Aktivität statt im summary-Feld – Moodle 5.2 ignoriert Subsection-Summaries beim Restore komplett (MDL-87621).
- Backup-Validator meldete Block-Kontexte fälschlich als "verwaist" (kannte bisher nur `activities/`, nicht `course/blocks/`).
