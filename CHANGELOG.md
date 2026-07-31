# Changelog

### Changelog Release v1.0.2

* Portfolio-Baustein (`ep`) wurde bei neueren OLAT-Exporten nicht erkannt (OLAT hat die Java-Klasse umbenannt) - `portfolio` als zweiter Schlüssel ergänzt
* iframe-Inhalte (z.B. H5P), die auf die alte OLAT-Quelle verweisen, werden jetzt erkannt und durch eine Warnung ersetzt statt tot im Kurs zu bleiben
* adobeconnect/bigbluebutton/den bekommen keine Warn-Platzhalterseite mehr im Kurs, nur noch einen stillen Eintrag im Systemprotokoll

### Changelog Release v1.0.1

* Wiki-Baustein mit echten Seiten (OLATs Wiki-Paket wird ausgelesen, Syntax zu HTML konvertiert)
* Kalender-Baustein als echter Moodle-Kalender-Block in der Kurs-Seitenleiste
* Section-Struktur überarbeitet: jeder Top-Level-Struktur-Baustein wird zu einer echten Section, lose Bausteine landen in durchnummerierten Sammel-Abschnitten
* Unit-Test-Suite (pytest) für alle Kernmodule, inklusive absichtlich fehlerhafter Eingaben
* `has_children` falsch erkannt - Ordner/PDF-Seiten wurden dadurch fälschlich als eigene Section behandelt
* Leere Struktur-Bausteine fielen fälschlich in die "zu tief verschachtelt"-Behandlung
* `<intro>` und `<content>` bei Seiten-Aktivitäten waren vermischt - OLAT-Beschreibung landete fälschlich im Seiteninhalt
* OLAT-Emoticons hinterließen einen nie auflösbaren Dateiverweis, werden jetzt entfernt
* Section-Nummerierung startet jetzt bei 0 statt 1 (sonst legt Moodle beim Restore selbst eine zusätzliche leere Section an)
* Subsection-Beschreibung bleibt als Label-Aktivität statt im summary-Feld (Moodle 5.2 ignoriert Subsection-Summaries beim Restore, MDL-87621)
* Backup-Validator meldete Block-Kontexte fälschlich als "verwaist"
