# Changelog

### Changelog Release v1.0.5

Die Versionen 1.0.3 und 1.0.4 sind hier nie erschienen – ihre Änderungen stecken in diesem Release.

* SCORM-Bausteine (mod_scorm) werden jetzt als echte, funktionierende Moodle-Aktivität übertragen statt übersprungen zu werden – mod_scorm ist Moodle-Core, kein Plugin nötig
* SCO-Struktur (Lernobjekt-Baum) wird aus dem paket-eigenen imsmanifest.xml abgeleitet und im Kurs korrekt angezeigt
* Paketinhalt landet direkt im Backup, damit er sofort nach dem Restore sichtbar ist, ohne dass Moodle das Paket selbst neu entpacken muss
* SCORM-Pakete werden neu gepackt statt unverändert durchgereicht, damit die Anonymisierung von Nutzerkennungen auch im Paket selbst greift
* SCORM-2004-Pakete bekommen das passende Datenmodell statt pauschal SCORM 1.2 (sonst kein Tracking)
* Startet ein Paket mit einem reinen Ordner-Knoten, wird jetzt die erste echte Lerneinheit als Startpunkt gesetzt statt ins Leere zu zeigen
* Dateien mit unbekanntem Typ (z.B. `.drawio`, `.dwb`) landen als Download in einem Ordner, statt als roher XML-Text im Kurs zu stehen – der Dateiname bleibt der aus OLAT
* Dokumente, die Moodle nicht selbst anzeigen kann, werden als Download angeboten und mit 📎 gekennzeichnet
* LaTeX-Formeln erscheinen als gesetzte Formel statt als Quelltext
* Passwortgeschützte OLAT-Bereiche kommen vollständig mit, dazu ein roter Hinweis im Abschnitt und 🔓 an jedem betroffenen Baustein – das Passwort selbst wird weder in den Kurs noch ins Protokoll übernommen
* Bausteine ohne Moodle-Gegenstück (Einschreibung, E-Mail, Checkliste, Bewertung mit Rubrics, Portfolioaufgabe) bekommen einen anklickbaren Titel mit ⚠️ und einen Hinweistext im Kurs, statt nur im Systemprotokoll aufzutauchen
* Der Kalender-Baustein wird mit 📅 gekennzeichnet – er liegt als Block in der Seitenleiste, nicht an seiner Stelle im Kursverlauf
* Hotspot-Fragen: der richtige Bereich wird auf mindestens 200 Pixel Radius vergrößert, weil die Markierung in Moodle frei abgelegt statt angeklickt wird – Test und Frage tragen ⚠️, der Hinweis dazu steht in der Test-Beschreibung
* Markierungen erscheinen jetzt auch an Test, Buch, Wiki und SCORM – bisher trugen sie nur Seiten und Ordner
* Dateianhänge landeten im Beschreibungstext statt im dafür vorgesehenen Feld – bei Aufgaben stehen sie jetzt unter „Zusätzliche Dateien"
* Eine Einzelseite, die auf eine Datei im Wurzelverzeichnis des Kursordners verweist, zog stattdessen eine gleichnamige Datei aus einem Unterordner – im Kurs stand fremder Inhalt
* Bilder mit fest gesetzter Breite konnten aus dem Layout laufen und bekommen jetzt dieselbe Begrenzung wie alle anderen
* Verwaiste Dateien werden über den tatsächlichen Verbrauch erkannt statt über eine Liste bekannter Dateiendungen – bisher verschwand jeder unbekannte Dateityp spurlos
* Quelldateien konvertierter Seiten wurden fälschlich als verwaist gemeldet
* Verwaiste Dateien tragen jetzt den Namen ihres OLAT-Bausteins, OLAT-interne XML-Dateien liegen in einem eigenen zugeklappten Unterordner
* Das Programmfenster trägt sein eigenes Icon, auch in der Taskleiste – dort zeigte Windows vorher das Python-Symbol
* Im Lizenz-Fenster sind Links anklickbar statt nur hübsch dargestellt, und ein Verweis stand dort roh als Markdown-Text

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
