# OLAT zu Moodle Konverter

Ein Werkzeug, das einen OLAT/OpenOLAT-Kursexport (`.zip`) automatisch in ein
Moodle-Kurs-Backup (`.mbz`) umwandelt – Kursstruktur, Bausteine, Fragen/Tests
und Dateien werden dabei so weit wie möglich automatisch übertragen.

## Download

Die aktuelle Version steht unter [Releases](../../releases) als
`Olat_to_Moodle.exe` zum Download bereit (Windows, keine Installation nötig).

## Verwendung

1. `Olat_to_Moodle.exe` starten.
2. Den OLAT-Export (`.zip`) auswählen.
3. Einen Zielpfad für die Moodle-Backup-Datei (`.mbz`) angeben.
4. Auf „Konvertieren" klicken.
5. Die erzeugte `.mbz`-Datei kann direkt über Moodles Kurs-Wiederherstellung
   importiert werden.

Am Ende des konvertierten Kurses steht ein automatisch erzeugtes
Systemprotokoll, das auflistet, was erfolgreich übertragen wurde und wo
manuell nachgearbeitet werden sollte (z.B. bei Bausteintypen ohne
Moodle-Äquivalent).

## Voraussetzungen

- Windows
- Ziel-Moodle-Version 5.0 (Core, ohne Zusatz-Plugins)

## Rückmeldungen

Fehler oder fehlende Bausteintypen gerne über [Issues](../../issues) melden.

## Lizenz

Siehe [LICENSE.md](LICENSE.md). Nutzung für private/nicht-kommerzielle Zwecke ist
frei möglich; Kopieren, Verändern oder Weiterverbreiten des Programms ist ohne
Zustimmung nicht gestattet.

Für eingebettete Drittanbieter-Komponenten siehe
[THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).
