"""Zentrale Konfiguration für den gesamten Konverter.

Enthält alle Datei-/Ordnerpfade, Moodle-Zielwerte (WWWROOT/Site-Hash) und
die Mapping-Tabellen, die main.py, olat_parser.py und die qtype_*.py-Module
brauchen, um OLAT-Bausteine bzw. QTI-Fragen auf Moodle-Typen abzubilden.

Braucht keine Werte von außen - wird von allen anderen Modulen per
`from config import ...` gelesen.
"""
import os
import sys


def _resource_path(relative_path: str) -> str:
    """Löst relative_path relativ zum laufenden Programm auf - egal ob normales
    Skript oder gebaute PyInstaller-.exe. sys._MEIPASS existiert nur in der
    .exe (Onefile-Entpackziel), sonst wird der Ordner dieser Datei genommen."""
    if hasattr(sys, '_MEIPASS'):
        # noinspection PyProtectedMember
        # Einzige Schnittstelle, die PyInstaller dafür bietet - keine öffentliche Alternative.
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


# Bewusst leer: Ein-/Ausgabepfade kommen über die GUI bzw. als CLI-Argumente.
# Ein hartkodierter Entwicklungs-Pfad würde als Klartext-String in der
# gebauten .exe landen (Benutzername, lokale Ordnerstruktur, Kursdateiname).
# Für Testläufe während der Entwicklung den Pfad als CLI-Argument übergeben
# oder lokal (uncommitted) hier eintragen.
OLAT_INPUT_FILE = ""

DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

MOODLE_OUTPUT_FILE = os.path.join(DOWNLOAD_DIR, "test_mit_files.mbz")

TEMPLATE_DIR = _resource_path("moodle_musterkurs")


def _license_path() -> str:
    """Löst den Pfad zu LICENSE.md auf - liegt anders als moodle_musterkurs
    nicht unter src/, sondern im Projekt-Wurzelverzeichnis (gilt fürs ganze
    Repo, nicht nur den Konverter-Code). In der gebauten .exe liegt sie
    stattdessen im Bundle-Root (siehe OLAT2Moodle.spec datas)."""
    if hasattr(sys, '_MEIPASS'):
        # noinspection PyProtectedMember
        return os.path.join(sys._MEIPASS, "LICENSE.md")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "LICENSE.md")


LICENSE_PATH = _license_path()


def _icon_path() -> str:
    """Löst den Pfad zur Icon-Datei auf - liegt wie LICENSE.md nicht unter
    src/, sondern eine Ebene höher in assets/. In der gebauten .exe liegt sie
    stattdessen im Bundle-Root (siehe OLAT2Moodle.spec datas)."""
    if hasattr(sys, '_MEIPASS'):
        # noinspection PyProtectedMember
        return os.path.join(sys._MEIPASS, "OLAT2Moodle.ico")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "OLAT2Moodle.ico")


ICON_PATH = _icon_path()


def _placeholder_path(filename: str) -> str:
    """Löst den Pfad zu einer der drei fest vorbereiteten Platzhalter-Dateien
    auf (tools/placeholder.py) - liegen wie das Icon in assets/, nicht unter
    src/. Werden nie zur Laufzeit neu erzeugt, nur auf die passende Seiten-/
    Folienzahl runtergeschnitten, damit sie zum Original passen."""
    if hasattr(sys, '_MEIPASS'):
        # noinspection PyProtectedMember
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", filename)


PLACEHOLDER_VIDEO_PATH = _placeholder_path("placeholder.mp4")
PLACEHOLDER_PDF_PATH = _placeholder_path("placeholder.pdf")
PLACEHOLDER_PPTX_PATH = _placeholder_path("placeholder.pptx")
# Anzahl Seiten/Folien in den beiden Vorlagen-Dateien - mehr als das kann
# nicht "gematcht" werden, dann bleibt's bei dieser Obergrenze.
PLACEHOLDER_MAX_PAGES = 5

# Generischer Platzhalter statt einer echten Moodle-Instanz - dieser Wert
# landet unverändert in original_wwwroot/original_site_identifier_hash
# jeder erzeugten .mbz (siehe xml_generator.py), betrifft also JEDE
# Konvertierung, egal welche Institution das Tool nutzt. Frei überschreibbar,
# falls eine bestimmte Ziel-Moodle-Instanz das mal auswerten sollte -
# für den Restore-Vorgang selbst ist der Wert rein informativ.
MOODLE_WWWROOT = "https://moodle.example.invalid"

MOODLE_SITE_HASH = "00000000000000000000000000000000"

# OLAT-Typen ohne echtes Moodle-Äquivalent (ohne Plugin) - bekommen keinen
# normal konvertierten Baustein, sondern eine ⚠️-Warn-Platzhalterseite an
# ihrer Original-Position im Kurs (siehe main.py, build_unsupported_placeholder_html).
# 'ep'/'portfolio' (Portfolioaufgabe): assign bildet die Portfolio-Semantik
# nicht ab. Zwei Schlüssel für dieselbe Funktion, weil der Typ-String aus dem
# Java-Klassennamen abgeleitet wird (siehe olat_parser._extract_node_fields)
# und OLAT die Klasse zwischenzeitlich von EPCourseNode zu PortfolioCourseNode
# umbenannt hat - je nach OLAT-Version des Exports kommt der eine oder der
# andere Klassenname vor.
SKIPPED_OLAT_TYPES = {"scorm", "lti", "basiclti", "h5p", "ep", "portfolio"}

# OLAT-Typen, die genauso wenig migriert werden wie SKIPPED_OLAT_TYPES, aber
# ohne jede Spur im Kurs selbst - kein Platzhalter, keine Aktivität an der
# Originalposition, nur ein stiller Eintrag im Systemprotokoll (main.py).
# 'bigbluebutton'/'adobeconnect': Meeting-Baustein, dessen OLAT-Konfiguration/
# URL ohnehin nicht zum neuen Moodle-System passt und manuell neu eingerichtet
# werden muss - ein Platzhalter im Kurs wäre hier nur Lärm ohne Mehrwert.
# 'den': undokumentiertes, nicht mehr verwendetes altes OLAT-Format, enthält
# in der Praxis nur noch Datenreste ohne migrationswürdigen Inhalt.
SILENTLY_SKIPPED_OLAT_TYPES = {"bigbluebutton", "adobeconnect", "den"}

# Grund-Text je SILENTLY_SKIPPED_OLAT_TYPES-Typ für den Systemprotokoll-
# Eintrag (main.py hängt ihn als ", <Grund>" an den OLAT-Typ, siehe
# conversion_report._group_block - dieselbe Konvention wie bei "Template fehlt").
SILENTLY_SKIPPED_REASONS = {
    "bigbluebutton": "Meeting-Baustein, muss manuell neu eingerichtet werden",
    "adobeconnect": "Meeting-Baustein, muss manuell neu eingerichtet werden",
    "den": "Datenreste aus einem alten, nicht mehr verwendeten Format",
}

# Symbole für die Systemprotokoll-Meldungen (main.py) - alle frei änderbar,
# Farben/Legendentexte dafür stehen gleich darunter und hängen an denselben
# Konstanten, damit sie nie an einem geänderten Symbol vorbeizeigen können.
# SUCCESS_SYMBOL: sauber übertragener Baustein (main.py transferred_elements).
# WARNING_SYMBOL: Baustein fehlt komplett (SKIPPED_OLAT_TYPES).
# UNRECOGNIZED_TYPE_MARKER: nicht erkannter/nicht gemappter OLAT-Bausteintyp
# (main.py, is_fallback-Pfad) - anders als bei SKIPPED_OLAT_TYPES wird hier
# trotzdem echter Inhalt übernommen, nur der Typ selbst war unbekannt.
# FLATTENED_BOUNDARY_MARKER/FLATTENED_CHILD_MARKER: "strukturell verschoben"-
# Markierung (MAX_SECTION_DEPTH-Handling) - der zu tief verschachtelte
# Struktur-Knoten (bekommt ohnehin schon einen eigenen Baustein) wird mit
# FLATTENED_BOUNDARY_MARKER markiert, seine Kind-Bausteine mit
# FLATTENED_CHILD_MARKER.
SUCCESS_SYMBOL = "✅"
WARNING_SYMBOL = "⚠️"
UNRECOGNIZED_TYPE_MARKER = "❓"
FLATTENED_BOUNDARY_MARKER = "🔀"
FLATTENED_CHILD_MARKER = "ℹ️"

# Sammel-Sektion für Bausteine ohne umschließenden OLAT-Struktur-Knoten -
# eigener, klar erkennbarer Titel statt "Allgemein"/"Allgemeines", damit sie
# nicht mit einer echten, vom Kursautor gleich oder ähnlich benannten Sektion
# verwechselt wird. main.py hängt eine laufende Nummer an (" #1", " #2", ...),
# weil es davon mehrere geben kann - jeder echte Struktur-Abschnitt
# unterbricht die aktuelle Sammlung, danach beginnt bei Bedarf eine neue.
UNGROUPED_SECTION_MARKER = "📌"
UNGROUPED_SECTION_TITLE = "Sammlung aller Bausteine"

# Farben (bg, Rand, Akzent links) pro Symbol im Systemprotokoll. Nur einzelne
# style=""-Attribute mit Eigenschaften aus Moodles echter CSSDefinition.php
# (MOODLE_500_STABLE) - kein <style>-Block (wird von purify_html() beim
# Speichern entfernt, steht nicht auf der erlaubten Element-Liste), kein
# flex/grid (nur klassische display-Werte erlaubt), kein box-shadow (nicht
# auf der erlaubten Eigenschaften-Liste). Deshalb Boxen per float statt
# flex - das einzige Layout, das sicher übersteht (siehe
# conversion_report._build_symbol_legend_html).
SYMBOL_COLORS = {
    SUCCESS_SYMBOL: ('#e8f5ec', '#b7dfc4', '#1e7d3c'),
    WARNING_SYMBOL: ('#faf6ee', '#e6d9c2', '#a8500f'),
    UNRECOGNIZED_TYPE_MARKER: ('#fbf7e6', '#e3d9a8', '#8a6a12'),
    FLATTENED_BOUNDARY_MARKER: ('#eaf1f8', '#bcd4e8', '#3a5f8a'),
    FLATTENED_CHILD_MARKER: ('#eaf3ee', '#bfe0cf', '#2b6e63'),
}

# Legendentexte (Name, Beschreibung) pro Symbol im Systemprotokoll.
SYMBOL_LEGEND_TEXT = {
    SUCCESS_SYMBOL: ('Erfolgreich übertragen',
                     'Bausteintyp erkannt, Inhalt korrekt in Moodle angekommen.'),
    WARNING_SYMBOL: ('Fehlt komplett',
                     'Kein Moodle-Äquivalent, muss von Hand nachgebaut werden.'),
    UNRECOGNIZED_TYPE_MARKER: ('Nicht erkannt',
                               'Inhalt trotzdem übernommen, bitte gegenprüfen.'),
    FLATTENED_BOUNDARY_MARKER: ('War eigener Abschnitt',
                                'Zu tief verschachtelt, eine Ebene höher eingefügt.'),
    FLATTENED_CHILD_MARKER: ('Gehört dazu',
                             f'Lag im {FLATTENED_BOUNDARY_MARKER}-markierten Abschnitt.'),
}

# Farben für Systemprotokoll-Gruppen ohne eigenes Symbol (z.B. "Template
# fehlt", "Konvertierungsfehler" - main.py setzt dort kein 'symbol') und für
# Links im Protokoll (z.B. zurück zur betroffenen Aktivität im Kurs).
NEUTRAL_COLORS = ('#f3f4f6', '#dcdfe4', '#6b7280')
LINK_COLOR = "#0f6cbf"

# OLAT-Typ → Hilfe-Link für die Warn-Platzhalterseite (SKIPPED_OLAT_TYPES).
# Frei editierbar: leerer String = kein Link auf der Seite (die Warnseite
# erscheint trotzdem, nur ohne Link-Absatz). Pro Eintrag steht, WAS das
# eigentliche Problem ist und worauf der einzutragende Link führen sollte -
# einfach die URL zwischen die Anführungszeichen setzen.
UNSUPPORTED_TYPE_HELP_LINKS = {
    # Problem: SCORM-Lernpakete haben ohne SCORM-Plugin kein Moodle-Äquivalent.
    # Link sollte zu einer Anleitung führen, wie man ein SCORM-Paket manuell
    # in Moodle einbindet (bzw. wo man es alternativ hochladen kann).
    "scorm": "",
    # Problem: LTI-Tool-Verknüpfungen (externe Tools wie Zoom o.ä.) sind an
    # die OLAT-spezifische Konfiguration gebunden und müssen in Moodle neu
    # eingerichtet werden. Link sollte zu einer Anleitung "externes Tool
    # (LTI) in Moodle einrichten" führen.
    "lti": "",
    # Problem: wie 'lti' oben (technisch ältere LTI-Version, gleiche Lösung).
    "basiclti": "",
    # Problem: H5P-Interaktionen brauchen das H5P-Plugin, das im Ziel-Moodle
    # (Core-only) nicht installiert ist. Link sollte zu einer Anleitung
    # führen, wie man H5P-Inhalte alternativ einbindet oder das Plugin
    # nachinstalliert bekommt.
    "h5p": "",
    # Problem: Portfolioaufgaben (E-Portfolio mit mehreren Feedback-Runden)
    # haben in Moodle Core keine Entsprechung - eine normale Abgabe (assign)
    # bildet das nicht ab. Link sollte zu einer Anleitung führen, wie man
    # eine vergleichbare Aufgabe mit mehreren Bewertungs-/Feedback-Runden in
    # Moodle nachbaut. 'portfolio' ist derselbe Bausteintyp, nur aus einem
    # neueren OLAT-Export (siehe SKIPPED_OLAT_TYPES).
    "ep": "",
    "portfolio": "",
    # Problem: Die BigBlueButton-Meeting-Konfiguration aus OLAT (Server,
    # Raum-ID) passt nicht zum neuen Moodle-System. Link sollte zu einer
    # Anleitung führen, wie man eine neue BigBlueButton-Aktivität in Moodle
    # einrichtet.
    "bigbluebutton": "",
    # Problem: Wie 'bigbluebutton' oben - die Adobe-Connect-Meeting-URL aus
    # OLAT ist im neuen System nicht gültig. Link sollte zu einer Anleitung
    # führen, wie man den Meeting-Zugang in Moodle neu einrichtet.
    "adobeconnect": "",
}

# Synthetischer 'ident' für einen eigenständig exportierten QTI-Testpaket
# (OLAT-Testeditor-Export ohne umgebenden Kurs, kein editortreemodel.xml).
# main.py erkennt so einen Export und speist einen einzigen Knoten mit
# diesem ident in die normale Hauptschleife ein; qti_quiz_builder.py
# erkennt denselben Wert und nimmt das komplette Manifest-VFS direkt statt
# über 'export/<ident>/repo.zip' aufzulösen (das gibt es hier nicht - der
# Export IST bereits das QTI-Paket, ohne Kurs-Verpackung drumherum).
STANDALONE_QTI_IDENT = "__standalone_qti__"

# Analog zu STANDALONE_QTI_IDENT, nur für ein eigenständig exportiertes
# IMS-Content-Package (OLAT-cp-Baustein ohne umgebenden Kurs, kein
# editortreemodel.xml, aber ein imsmanifest.xml direkt im Wurzel-ZIP statt
# unter 'export/<ident>/'). cp_book_builder.py erkennt denselben Wert und
# nimmt das komplette Manifest-VFS direkt statt über
# 'export/<ident>/repo.zip' aufzulösen.
STANDALONE_CP_IDENT = "__standalone_cp__"

# Ersatzwert für echte Nutzerkennungen/E-Mails, die anonymizer.py im OLAT-
# Export findet (z.B. 'BAA0000', 'mustermann-admin', echte E-Mail-Adressen).
# Frei änderbar.
PLACEHOLDER_USERNAME = "anonym"

# Office-Formate, die kein Browser nativ darstellen kann - ein 'document'-
# Baustein mit einer dieser Endungen wird deshalb (siehe main.py) nicht als
# 'resource' (Datei-Ressource, klickt man drauf lädt sie SOFORT ohne
# Zwischenschritt herunter), sondern als 'folder' (Verzeichnis, zeigt erst
# eine Liste, Download erst beim gezielten Klick auf die Datei selbst)
# angelegt. PDF bewusst nicht dabei - hat einen echten Browser-Viewer.
OFFICE_DOCUMENT_EXTS = ('.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.rtf')
# Kennzeichnet einen so zum Ordner gewandelten Baustein sichtbar im Kurs -
# sonst nicht von einem "echten" OLAT-Ordner-Baustein (bc/pf) zu unterscheiden.
OFFICE_DOCUMENT_MARKER = "📎"

# OLAT-Bausteintyp → Moodle-Modulname.
OLAT_TO_MOODLE_MAPPING = {
    "bc":               "folder",
    "st":               "label",
    "sp":               "page",
    "document":         "resource",
    "fo":               "forum",
    "video":            "page",
    "tu":               "url",
    "iqtest":           "quiz",
    "ita":              "assign",
    "info":             "forum",
    "pf":               "folder",
    "co":               "label",
    "members":          "label",
    "cepage":           "page",
    "iqself":           "quiz",
    "en":               "label",
    "ll":               "page",
    "survey":           "feedback",
    "cal":              "label",
    "dialog":           "forum",
    "checklist":        "label",
    "appointments":     "choice",
    "projectbroker":    "choice",
    "wiki":             "wiki",
    "gta":              "assign",
    "ms":               "label",
    "blog":             "forum",
    "zoom":             "url",
    "form":             "feedback",
    "podcast":          "url",
    "practice":         "quiz",
    "topicbroker":      "choice",
    "videotask":        "assign",
    "iqsurv":           "feedback",
    "cns":              "choice",
    "ta":               "assign",
    "root":             "label",
    "vc":               "url",
    "page":             "page",
    "cp":               "book",
}

# Moodle-Modulname → menschenlesbarer Name, für das Systemprotokoll
# (Erfolgs-Tabelle: OLAT-Baustein → Moodle-Äquivalent).
MOODLE_MODULE_NAMES = {
    "assign":      "Aufgabe",
    "book":        "Buch",
    "choice":      "Abstimmung",
    "feedback":    "Umfrage (Feedback)",
    "folder":      "Ordner",
    "forum":       "Forum",
    "label":       "Textfeld",
    "page":        "Seite",
    "quiz":        "Test",
    "resource":    "Datei",
    "url":         "Externe Seite",
    "wiki":        "Wiki",
}

# OLAT-Typ → menschenlesbarer Name, für das Systemprotokoll.
OLAT_NAMES = {
    "bc":               "Ordner",
    "st":               "Struktur",
    "sp":               "HTML-Seite",
    "document":         "Dokument",
    "fo":               "Forum",
    "video":            "Video",
    "tu":               "Externe Seite",
    "iqtest":           "Test",
    "ita":              "Aufgabe",
    "info":             "Mitteilungen",
    "pf":               "Teilnehmer:innen Ordner",
    "co":               "E-Mail",
    "members":          "Liste der Teilnehmer:innen",
    "cepage":           "Seite",
    "iqself":           "Selbsttest",
    "en":               "Einschreibung",
    "ll":               "Linkliste",
    "survey":           "Umfrage",
    "cal":              "Kalender",
    "dialog":           "Dateidiskussion",
    "checklist":        "Checkliste",
    "appointments":     "Terminplanung",
    "projectbroker":    "Themenvergabe",
    "wiki":             "Wiki",
    "gta":              "Gruppenaufgabe",
    "ep":               "Portfolioaufgabe",
    "portfolio":        "Portfolioaufgabe",
    "scorm":            "SCORM-Lerninhalt",
    "ms":               "Bewertung",
    "blog":             "Blog",
    "zoom":             "Zoom",
    "cp":               "CP-Lerninhalt",
    "form":             "Formular",
    "podcast":          "Podcast",
    "adobeconnect":     "Adobe Connect",
    "practice":         "Übung",
    "lti":              "LTI-Seite",
    "basiclti":         "LTI-Tool",
    "den":              "den (unbekannt)",
    "topicbroker":      "Themenbörse",
    "videotask":        "Videoaufgabe",
    "iqsurv":           "Umfrage (alt)",
    "cns":              "Auswahl",
    "ta":               "Aufgabe (alt)",
    "root":             "Wurzelknoten",
    "vc":               "Virtuelles Klassenzimmer",
    "bigbluebutton":    "BigBlueButton",
}

# --- Konstanten der QTI-Fragen-Pipeline ---

STAMP_HOST = "olat-import"

# Bewertungsanteile (Prozent), die Moodle für Multiple-Choice-Fractions akzeptiert.
ALLOWED_MOODLE_FRACTIONS = {
    100.0, 90.0, 83.33333, 80.0, 75.0, 70.0, 66.66667, 60.0,
    50.0, 40.0, 33.33333, 30.0, 25.0, 20.0, 16.66667,
    14.28571, 12.5, 11.11111, 10.0, 5.0, 0.0,
    -5.0, -10.0, -11.11111, -12.5, -14.28571, -16.66667,
    -20.0, -25.0, -30.0, -33.33333, -40.0, -50.0,
    -60.0, -66.66667, -70.0, -75.0, -80.0,
    -83.33333, -90.0, -100.0,
}

# Erkannte Bezeichnungen für Wahr/Falsch-Antworten in OLAT-Quelltexten.
TRUE_LABELS = {"wahr", "richtig", "true", "ja", "stimmt"}
FALSE_LABELS = {"falsch", "false", "nein", "stimmt nicht", "unwahr"}

# Referenz: OLAT-QTI-Fragetyp → Moodle-Fragetyp. Reine Dokumentation, kein
# Schalter - die echte Zuordnung passiert in qti_pipeline.py/qtype_*.py.
QTI_TO_MOODLE_QUESTION_MAPPING = {
    # OLAT-QTI-Interaction (Bedingung):      Moodle-Fragetyp
    "choiceInteraction (2 Optionen, Wahr/Falsch)":   "truefalse",
    "choiceInteraction (sonst)":                     "multichoice",
    "matchInteraction (class=match_krpim)":          "multichoice (Kprim, ±25%)",
    "matchInteraction (class=match_matrix)":         "— nicht unterstützt (übersprungen)",
    "matchInteraction (sonst)":                      "match (Zuordnung)",
    "orderInteraction":                              "match (Element → Position N)",
    "inlineChoiceInteraction":                       "multianswer (Cloze-Dropdown)",
    "textEntryInteraction (genau 1 Lücke)":          "shortanswer",
    "textEntryInteraction (≥ 2 Lücken)":             "multianswer (Cloze, NUMERICAL/SHORTANSWER je Lücke)",
    "hottextInteraction":                            "multichoice (Mehrfachauswahl)",
    "hotspotInteraction":                            "ddmarker (Drag & Drop Markierung)",
    "extendedTextInteraction":                       "essay (Freitext, manuell bewertet)",
    "uploadInteraction":                             "essay (nur Dateianhang, Textfeld sichtbar mit Hinweistext)",
    "extendedTextInteraction + uploadInteraction":   "essay (Textfeld UND Dateianhang aktiviert)",
    "drawingInteraction":                            "— nicht unterstützt (übersprungen, kein Modul ohne Plugin)",
}

# --- Konstanten der GUI (app/gui.py) ---

# Identifiziert das Programm gegenüber der Windows-Taskleiste. Muss eindeutig
# sein und sich zwischen Versionen nicht ändern, sonst behandelt Windows das
# Programm als ein anderes (eigener Taskleisten-Eintrag, verlorene Anheftung).
APP_MODEL_ID = "olat2moodle.konverter"

# Log-Fenster-Farben passend zum jeweiligen sv_ttk-Theme (Text-Widget wird
# von sv_ttk nicht automatisch mitgestylt, da es kein ttk-Widget ist).
LOG_COLORS = {
    "dark": {"bg": "#1c1c1c", "fg": "#e0e0e0", "insertbackground": "#e0e0e0"},
    "light": {"bg": "#ffffff", "fg": "#1a1a1a", "insertbackground": "#1a1a1a"},
}

# Farben des Streifens am Zeilenanfang im Log-Fenster, je Kategorie einer
# print()-Zeile (siehe app/gui.py _LINE_CATEGORIES für die Zuordnung
# Präfix → Kategorie).
STRIPE_COLORS = {
    "ok": "#4cd471",
    "warn": "#f0a83c",
    "info": "#4a9fe0",
    "compress": "#b07cf0",
}

# --- Konstante des Test-Modus (tools/placeholder.py) ---

# Nur Dateien oberhalb dieser Schwelle werden angefasst - kleine Dateien
# bringen kaum Ersparnis. (Echte Kompression mit eigenen Qualitätsstufen
# gibt es nicht mehr hier im Hauptprogramm, siehe
# compression_standalone/compression.py in der Repo-Wurzel.)
TEST_COMPRESSION_THRESHOLD_MB = 1.0
