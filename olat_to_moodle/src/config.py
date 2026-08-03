"""Zentrale Konfiguration für den gesamten Konverter.

Enthält alle Datei-/Ordnerpfade, Moodle-Zielwerte (WWWROOT/Site-Hash) und
die Mapping-Tabellen, die main.py, olat_parser.py und die qtype_*.py-Module
brauchen, um OLAT-Bausteine bzw. QTI-Fragen auf Moodle-Typen abzubilden.

Braucht keine Werte von außen – wird von allen anderen Modulen per
`from config import ...` gelesen.
"""
import os
import sys


def _bundled_path(*parts_from_src: str) -> str:
    """Löst den Pfad einer mitgelieferten Datei auf – egal ob normales Skript
    oder gebaute PyInstaller-.exe.

    parts_from_src ist der Pfad relativ zu DIESEM Verzeichnis (src/), so wie
    die Datei im Repo liegt: _bundled_path("..", "assets", "logo.ico").

    In der .exe entfällt diese Struktur – PyInstaller legt alles flach ins
    Entpackziel (siehe OLAT2Moodle.spec datas), deshalb zählt dort nur der
    letzte Teil. Ausnahme ist moodle_musterkurs, das als ganzer Ordner unter
    seinem eigenen Namen gebündelt wird; auch dafür stimmt der letzte Teil.

    sys._MEIPASS existiert nur in der .exe und ist die einzige Schnittstelle,
    die PyInstaller dafür anbietet – eine öffentliche Alternative gibt es nicht."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, parts_from_src[-1])
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts_from_src)


# Bewusst leer: Ein-/Ausgabepfade kommen über die GUI bzw. als CLI-Argumente.
# Ein hartkodierter Entwicklungs-Pfad würde als Klartext-String in der
# gebauten .exe landen (Benutzername, lokale Ordnerstruktur, Kursdateiname).
# Für Testläufe während der Entwicklung den Pfad als CLI-Argument übergeben
# oder lokal (uncommitted) hier eintragen.
OLAT_INPUT_FILE = ""

DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

MOODLE_OUTPUT_FILE = os.path.join(DOWNLOAD_DIR, "olat_kurs.mbz")

TEMPLATE_DIR = _bundled_path("moodle_musterkurs")


# LICENSE.md liegt im Projekt-Wurzelverzeichnis, gilt fürs ganze Repo.
LICENSE_PATH = _bundled_path("..", "..", "LICENSE.md")


ICON_PATH = _bundled_path("..", "assets", "OLAT2Moodle.ico")


# Fest vorbereitete Platzhalter-Dateien des Test-Modus (tools/placeholder.py) –
# werden nie zur Laufzeit erzeugt, nur auf die Seiten-/Folienzahl des
# Originals runtergeschnitten.
PLACEHOLDER_VIDEO_PATH = _bundled_path("..", "assets", "placeholder.mp4")
PLACEHOLDER_PDF_PATH = _bundled_path("..", "assets", "placeholder.pdf")
PLACEHOLDER_PPTX_PATH = _bundled_path("..", "assets", "placeholder.pptx")
# Anzahl Seiten/Folien in den beiden Vorlagen-Dateien – mehr als das kann
# nicht "gematcht" werden, dann bleibt's bei dieser Obergrenze.
PLACEHOLDER_MAX_PAGES = 5

# Generischer Platzhalter statt einer echten Moodle-Instanz – dieser Wert
# landet unverändert in original_wwwroot/original_site_identifier_hash
# jeder erzeugten .mbz (siehe xml_generator.py), betrifft also JEDE
# Konvertierung, egal welche Institution das Tool nutzt. Frei überschreibbar,
# falls eine bestimmte Ziel-Moodle-Instanz das auswerten sollte – für den
# Restore-Vorgang selbst ist der Wert rein informativ.
MOODLE_WWWROOT = "https://moodle.example.invalid"

MOODLE_SITE_HASH = "00000000000000000000000000000000"

# OLAT-Typen ohne echtes Moodle-Äquivalent (ohne Plugin) – bekommen keinen
# normal konvertierten Baustein, sondern eine ⚠️-Warn-Platzhalterseite an
# ihrer Original-Position im Kurs (siehe main.py, build_unsupported_placeholder_html).
# 'ep'/'portfolio' (Portfolioaufgabe): assign bildet die Portfolio-Semantik
# nicht ab. Zwei Schlüssel für dieselbe Funktion, weil der Typ-String aus dem
# Java-Klassennamen abgeleitet wird (siehe olat_parser._extract_node_fields)
# und OLAT die Klasse zwischenzeitlich von EPCourseNode zu PortfolioCourseNode
# umbenannt hat – je nach OLAT-Version des Exports kommt der eine oder der
# andere Klassenname vor.
SKIPPED_OLAT_TYPES = {"lti", "basiclti", "h5p", "ep", "portfolio"}

# OLAT-Typen, die genauso wenig migriert werden wie SKIPPED_OLAT_TYPES, aber
# ohne jede Spur im Kurs selbst – kein Platzhalter, keine Aktivität an der
# Originalposition, nur ein stiller Eintrag im Systemprotokoll (main.py).
# 'bigbluebutton'/'adobeconnect': Meeting-Baustein, dessen OLAT-Konfiguration/
# URL ohnehin nicht zum neuen Moodle-System passt und manuell neu eingerichtet
# werden muss – ein Platzhalter im Kurs wäre hier nur Lärm ohne Mehrwert.
# 'den': undokumentiertes, nicht mehr verwendetes altes OLAT-Format, enthält
# in der Praxis nur noch Datenreste ohne migrationswürdigen Inhalt.
SILENTLY_SKIPPED_OLAT_TYPES = {"bigbluebutton", "adobeconnect", "den"}

# Grund-Text je SILENTLY_SKIPPED_OLAT_TYPES-Typ für den Systemprotokoll-
# Eintrag (main.py hängt ihn als ", <Grund>" an den OLAT-Typ, siehe
# conversion_report._group_block – dieselbe Konvention wie bei "Template fehlt").
SILENTLY_SKIPPED_REASONS = {
    "bigbluebutton": "Meeting-Baustein, muss manuell neu eingerichtet werden",
    "adobeconnect": "Meeting-Baustein, muss manuell neu eingerichtet werden",
    "den": "Datenreste aus einem alten, nicht mehr verwendeten Format",
}

# Symbole für die Systemprotokoll-Meldungen (main.py) – alle frei änderbar,
# Farben und Legendentexte stehen gleich darunter und hängen an denselben
# Konstanten, damit sie nie an einem geänderten Symbol vorbeizeigen können.
# Nur CALENDAR_BLOCK_MARKER steht nicht für einen Verlust: der Kalender ist
# vollständig da, nur als kursweiter Block statt im Kursverlauf – deshalb
# dort ein gegenständliches Symbol statt eines Warnzeichens.
SUCCESS_SYMBOL = "✅"             # sauber übertragener Baustein
WARNING_SYMBOL = "⚠️"             # Baustein fehlt komplett (SKIPPED_OLAT_TYPES)
UNRECOGNIZED_TYPE_MARKER = "❓"   # Typ unbekannt, Inhalt trotzdem übernommen
FLATTENED_BOUNDARY_MARKER = "🔀"  # war ein eigener Abschnitt, zu tief verschachtelt
FLATTENED_CHILD_MARKER = "ℹ️"     # lag in einem hochgezogenen Abschnitt
PASSWORD_LOST_MARKER = "🔓"       # war passwortgeschützt, jetzt frei zugänglich
CALENDAR_BLOCK_MARKER = "📅"      # liegt als Block in der Seitenleiste

# Beschriftungen der Oberfläche. Stehen hier, damit ein geändertes Symbol
# nicht an drei Fenstern vorbeigeht – Hauptfenster, Lizenz-Gate und
# Build-Zentrale nutzen dieselben Konstanten.
THEME_LABEL_LIGHT = "☀ Helles Design"
THEME_LABEL_DARK = "🌙 Dunkles Design"
JUMP_TO_END_LABEL = "⬇ Zum Ende springen"

# Sammel-Sektion für Bausteine ohne umschließenden OLAT-Struktur-Knoten –
# eigener, klar erkennbarer Titel statt "Allgemein"/"Allgemeines", damit sie
# nicht mit einer echten, vom Kursautor gleich oder ähnlich benannten Sektion
# verwechselt wird. main.py hängt eine laufende Nummer an (" #1", " #2", ...),
# weil es davon mehrere geben kann – jeder echte Struktur-Abschnitt
# unterbricht die aktuelle Sammlung, danach beginnt bei Bedarf eine neue.
UNGROUPED_SECTION_MARKER = "📌"
UNGROUPED_SECTION_TITLE = "Sammlung aller Bausteine"

# Farben (bg, Rand, Akzent links) pro Symbol im Systemprotokoll. Nur einzelne
# style=""-Attribute mit Eigenschaften aus Moodles echter CSSDefinition.php
# (MOODLE_500_STABLE) – kein <style>-Block (wird von purify_html() beim
# Speichern entfernt, steht nicht auf der erlaubten Element-Liste), kein
# flex/grid (nur klassische display-Werte erlaubt), kein box-shadow (nicht
# auf der erlaubten Eigenschaften-Liste). Deshalb Boxen per float statt
# flex – das einzige Layout, das sicher übersteht (siehe
# conversion_report._build_symbol_legend_html).
SYMBOL_COLORS = {
    SUCCESS_SYMBOL: ('#e8f5ec', '#b7dfc4', '#1e7d3c'),            # dunkelgrün
    WARNING_SYMBOL: ('#faf6ee', '#e6d9c2', '#a8500f'),            # orangebraun
    UNRECOGNIZED_TYPE_MARKER: ('#fbf7e6', '#e3d9a8', '#8a6a12'),  # olivgelb
    FLATTENED_BOUNDARY_MARKER: ('#eaf1f8', '#bcd4e8', '#3a5f8a'), # dunkelblau
    FLATTENED_CHILD_MARKER: ('#eaf3ee', '#bfe0cf', '#2b6e63'),    # dunkeltürkis
    PASSWORD_LOST_MARKER: ('#fdeced', '#f2c2c6', '#a4111b'),      # dunkelrot
    CALENDAR_BLOCK_MARKER: ('#f1eefa', '#cfc3ea', '#54408a'),     # violett
}

# Warnhinweis vor der Beschreibung des Bausteins, der in OLAT das Passwort
# gesetzt hat (PasswordCondition, siehe olat_parser._extract_node_fields).
# Moodle-Core kennt keine Passwort-Zugriffsbeschränkung – availability/
# condition/ enthält nur completion, date, grade, group, grouping, profile.
# Der Inhalt wird deshalb vollständig übernommen, ist danach aber ohne
# Passwort erreichbar; die Farbe entspricht PASSWORD_LOST_MARKER oben.
#
# Das Passwort selbst steht bewusst NICHT im Hinweis: er ist für alle
# Kursteilnehmenden sichtbar und würde es an genau die weitergeben, vor
# denen es schützen sollte. Im Systemprotokoll steht es ebenfalls nicht.
PASSWORD_LOST_WARNING = (
    '<p style="color:#a4111b;">'
    '<strong>Achtung:</strong> '
    'Dieser Bereich war in OLAT mit einem Passwort geschützt. Moodle kennt diese Art der '
    'Zugriffsbeschränkung nicht – die Inhalte sind vollständig übernommen, aber ohne '
    'Passwortabfrage zugänglich. Bei Bedarf unter „Voraussetzungen“ eine passende '
    'Beschränkung ergänzen, z.B. über Gruppe oder Gruppierung.</p>'
)

# Legendentexte (Name, Beschreibung) pro Symbol im Systemprotokoll.
SYMBOL_LEGEND_TEXT = {
    SUCCESS_SYMBOL: (
        'Erfolgreich übertragen',
        'Bausteintyp erkannt, Inhalt korrekt in Moodle angekommen.',
    ),
    WARNING_SYMBOL: (
        'Fehlt komplett',
        'Kein Moodle-Äquivalent, muss von Hand nachgebaut werden.',
    ),
    UNRECOGNIZED_TYPE_MARKER: (
        'Nicht erkannt',
        'Inhalt trotzdem übernommen, bitte gegenprüfen.',
    ),
    FLATTENED_BOUNDARY_MARKER: (
        'War eigener Abschnitt',
        'Zu tief verschachtelt, eine Ebene höher eingefügt.',
    ),
    FLATTENED_CHILD_MARKER: (
        'Gehört dazu',
        f'Lag im {FLATTENED_BOUNDARY_MARKER}-markierten Abschnitt.',
    ),
    PASSWORD_LOST_MARKER: (
        'Passwortschutz entfällt',
        'War in OLAT passwortgeschützt, in Moodle frei zugänglich.',
    ),
    CALENDAR_BLOCK_MARKER: (
        'Steht als Block',
        'Kalender liegt in der Seitenleiste, nicht im Kursverlauf.',
    ),
}

# Farben für Systemprotokoll-Gruppen ohne eigenes Symbol (z.B. "Template
# fehlt", "Konvertierungsfehler" – main.py setzt dort kein 'symbol') und für
# Links im Protokoll (z.B. zurück zur betroffenen Aktivität im Kurs).
NEUTRAL_COLORS = ('#f3f4f6', '#dcdfe4', '#6b7280')  # fast weiß, hellgrau, grau
LINK_COLOR = "#0f6cbf"                              # Moodle-Blau

# OLAT-Typ → Hilfe-Link für die Warn-Platzhalterseite (SKIPPED_OLAT_TYPES).
# Frei editierbar: leerer String = kein Link auf der Seite (die Warnseite
# erscheint trotzdem, nur ohne Link-Absatz). Pro Eintrag steht, WAS das
# eigentliche Problem ist und worauf der einzutragende Link führen sollte –
# die URL kommt zwischen die Anführungszeichen.
UNSUPPORTED_TYPE_HELP_LINKS = {
    # Problem: LTI-Tool-Verknüpfungen (externe Tools wie Zoom o.ä.) sind an
    # die OLAT-spezifische Konfiguration gebunden und müssen in Moodle neu
    # eingerichtet werden. Link sollte zu einer Anleitung "externes Tool
    # (LTI) in Moodle einrichten" führen.
    "lti": "",
    # Problem: wie 'lti' oben (technisch ältere LTI-Version, gleiche Lösung).
    "basiclti": "",
    # Problem: mod_h5pactivity ist zwar Moodle-Core, der eigentliche
    # H5P-Inhalt liegt aber in OLATs eigener H5P-Bibliothek und nicht als
    # .h5p-Datei im Kursexport. Link sollte zu einer Anleitung führen, wie
    # man H5P-Inhalte in Moodle neu anlegt oder importiert.
    "h5p": "",
    # Problem: Portfolioaufgaben (E-Portfolio mit mehreren Feedback-Runden)
    # haben in Moodle Core keine Entsprechung – eine normale Abgabe (assign)
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
    # Problem: Wie 'bigbluebutton' oben – die Adobe-Connect-Meeting-URL aus
    # OLAT ist im neuen System nicht gültig. Link sollte zu einer Anleitung
    # führen, wie man den Meeting-Zugang in Moodle neu einrichtet.
    "adobeconnect": "",
}

# Klartext-Grund je SKIPPED_OLAT_TYPES-Typ für die Warn-Platzhalterseite im
# Kurs (siehe conversion_report.build_unsupported_placeholder_html). Bewusst
# je Typ statt eines pauschalen Satzes: mod_lti und mod_h5pactivity sind
# Moodle-Core, "braucht ein Plugin" wäre schlicht falsch.
# 'lti'/'basiclti' und 'ep'/'portfolio' sind je zwei Schlüssel für dieselbe
# Sache (siehe SKIPPED_OLAT_TYPES) – der Text steht deshalb nur einmal, sonst
# laufen die beiden Fassungen beim nächsten Umformulieren auseinander.
_LTI_REASON = (
    "Die Verknüpfung zum externen Tool hängt an der OLAT-Konfiguration und muss "
    "in Moodle als „Externes Tool“ neu eingerichtet werden."
)
_PORTFOLIO_REASON = (
    "Portfolioaufgaben mit mehreren Feedback-Runden haben in Moodle keine Entsprechung."
)

UNSUPPORTED_TYPE_REASONS = {
    "lti": _LTI_REASON,
    "basiclti": _LTI_REASON,
    "h5p":
        "Der H5P-Inhalt liegt in OLATs eigener Bibliothek und nicht als Datei im Export; "
        "er muss in Moodle neu angelegt oder als .h5p-Datei importiert werden.",
    "ep": _PORTFOLIO_REASON,
    "portfolio": _PORTFOLIO_REASON,
}

# Synthetischer 'ident' für einen eigenständig exportierten QTI-Testpaket
# (OLAT-Testeditor-Export ohne umgebenden Kurs, kein editortreemodel.xml).
# main.py erkennt so einen Export und speist einen einzigen Knoten mit
# diesem ident in die normale Hauptschleife ein; qti_quiz_builder.py
# erkennt denselben Wert und nimmt das komplette Manifest-VFS direkt statt
# über 'export/<ident>/repo.zip' aufzulösen (das gibt es hier nicht – der
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

# Endungen, die Moodle in einer Datei-Ressource tatsächlich anzeigen kann.
# Ein 'document'-Baustein mit einer dieser Endungen bleibt eine 'resource';
# alles andere wird stattdessen ein 'folder' (siehe _resolve_moodle_type in
# main.py) – ein Verzeichnis, das die eine Datei zum Herunterladen auflistet.
#
# Bewusst als Positivliste: mod_resource zeigt jede Datei eingebettet an und
# fällt für nicht darstellbare Typen auf ein <object>-Tag zurück, in dem der
# Browser den rohen Dateiinhalt ausgibt (bei XML-basierten Formaten also
# seitenweise Markup). Was Moodle einbetten kann, ist eine kurze feste Liste;
# was es nicht kann, ist offen. Über die Positivliste landet jede unbekannte
# Endung automatisch im Verzeichnis, ohne einzeln eingetragen zu werden.
#
# Quelle der Medien-Endungen: die Typgruppen web_image/web_video/web_audio in
# lib/filelib.php, die resource_display_embed() (mod/resource/locallib.php)
# abfragt. PDF hat dort einen eigenen Zweig mit echtem Viewer; HTML und Text
# stellt der Browser im <object>-Tag sinnvoll dar.
EMBEDDABLE_DOCUMENT_EXTS = (
    '.gif', '.jpe', '.jpeg', '.jpg', '.png', '.svg', '.svgz', '.webp',
    '.avi', '.flv', '.f4v', '.fmp4', '.mov', '.mp4', '.m4v', '.mpeg',
    '.mpe', '.mpg', '.ogv', '.qt', '.ts', '.webm',
    '.aac', '.flac', '.mp3', '.m4a', '.oga', '.ogg', '.ra', '.wav',
    '.pdf', '.htm', '.html', '.txt',
)
# Kennzeichnet einen so zum Ordner gewandelten Baustein sichtbar im Kurs –
# sonst nicht von einem "echten" OLAT-Ordner-Baustein (bc/pf) zu unterscheiden.
DOWNLOAD_DOCUMENT_MARKER = "📎"

# --------------------------------------------------------------------------
# Sichtbare Meldungen im erzeugten Kurs
#
# Alle Texte, die im fertigen Moodle-Kurs auftauchen, stehen hier – nicht
# verstreut an ihrer Verwendungsstelle. Sie sind das, was am ehesten geändert
# werden soll (Wortwahl, Anrede, Ausführlichkeit), und dafür will niemand
# durch vier Module suchen.
#
# {name}-Platzhalter werden per .format() gefüllt; welche es gibt, steht am
# jeweiligen Text. Nicht hierher gehören XML-Bausteine des Backup-Formats –
# das ist Moodles Dateiformat, kein änderbarer Text.
# --------------------------------------------------------------------------

# Bausteintyp nicht erkannt, Inhalt trotzdem übernommen. Platzhalter: olat_name
UNRECOGNIZED_TYPE_WARNING = (
    '<p style="color:red;">'
    '<strong>Achtung:</strong> '
    'Dieser Bausteintyp ({olat_name}) wurde nicht automatisch erkannt – der Inhalt wurde '
    'trotzdem übernommen, bitte einmal prüfen.</p>'
)

# Kein Moodle-Gegenstück für die Funktion (siehe FUNCTIONLESS_OLAT_TYPES).
# Platzhalter: olat_name
FUNCTIONLESS_TYPE_WARNING = (
    '<p style="color:red;">'
    '<strong>Achtung:</strong> '
    'Für diesen OLAT-Bausteintyp ({olat_name}) gibt es keine funktionale '
    'Moodle-Entsprechung – nur Titel und Beschreibung wurden übernommen, die eigentliche '
    'Funktion fehlt. Bitte manuell prüfen, ob und wie das nachgebaut werden muss.</p>'
)

# Kalender-Baustein: der Block existiert, steht aber kursweit statt an dieser
# Stelle im Kursverlauf.
CALENDAR_BLOCK_NOTE = (
    '<p>'
    '<strong>Hinweis:</strong> '
    'Der Kalender wurde als eigener Moodle-Block in der Kurs-Seitenleiste ergänzt (siehe '
    'rechte/linke Spalte der Kursseite) – nicht an dieser Stelle im Kursverlauf, da '
    'Moodle-Blöcke immer kursweit sind, nie an eine bestimmte Position gebunden.</p>'
)

# 'tu'-Baustein ohne hinterlegte Adresse; moodle_xml setzt PLACEHOLDER_URL.
MISSING_URL_WARNING = (
    '<p style="color:red;">'
    '<strong>Achtung:</strong> '
    'Für diesen Baustein war in OLAT keine gültige externe Adresse hinterlegt – der Link '
    'führt aktuell absichtlich ins Leere (http://example.invalid/). Bitte manuell die '
    'richtige URL eintragen.</p>'
)

# Testpaket nicht auflösbar oder ohne unterstützte Fragen.
EMPTY_QUIZ_WARNING = (
    '<p style="color:red;">'
    '<strong>Achtung:</strong> '
    'Der Inhalt dieses Tests konnte nicht automatisch übernommen werden (Testpaket nicht '
    'auflösbar oder keine unterstützten Fragen) – das Quiz ist leer, bitte manuell '
    'nachbauen.</p>'
)

# Content-Package liess sich nicht in Buch-Kapitel zerlegen.
EMPTY_BOOK_WARNING = (
    '<p style="color:red;">'
    '<strong>Achtung:</strong> '
    'Der Inhalt dieses Content-Packages konnte nicht automatisch in Buch-Kapitel '
    'umgewandelt werden. Der ursprüngliche Text ist oben in der Beschreibung erhalten, der '
    'Rest muss manuell nachgetragen werden.</p>'
)

# Im HTML referenzierte Datei fehlt im Export. Platzhalter: filename
MISSING_FILE_WARNING = (
    '<p style="color:red;">'
    '<strong>Achtung:</strong> '
    'Die referenzierte Datei „{filename}“ wurde beim Export nicht gefunden – der Inhalt '
    'dieses Bausteins fehlt. Bitte manuell nachtragen.</p>'
)

# Download-Kasten für einen Anhang, den der Modultyp nicht in einem eigenen
# Feld führen kann (siehe file_manager.ATTACHMENT_FILEAREAS) – ohne diesen
# Link wäre die Datei zwar im Backup, im Kurs aber nirgends erreichbar.
# Platzhalter: url (@@PLUGINFILE@@-Verweis) und filename (bereits maskiert).
ATTACHMENT_LINK_BOX = (
    '<div style="margin-top:20px;padding:15px;'
    'border-left:4px solid #007bff;background-color:#f8f9fa;">'
    '<strong>Dateianhang:</strong> '
    '<a href="{url}" target="_blank">{filename}</a>'
    '</div>'
)

# Ersetzt einen iframe, dessen Quelle auf die alte OLAT-Instanz zeigt.
# Platzhalter: symbol (damit ein geändertes WARNING_SYMBOL auch hier greift).
EMBEDDED_CONTENT_LOST_WARNING = (
    "{symbol} Eingebetteter Inhalt konnte nicht automatisch übernommen werden "
    "(verweist auf die alte OLAT-Quelle) – muss in Moodle manuell neu "
    "eingebunden werden."
)

# Unterordner im Verwaisten-Ordner für Dateien, die niemand von Hand
# weiterverwendet: OLATs interne Beschreibungs- und Konfigurationsdateien.
# Sie bleiben im Kurs, damit nichts unbemerkt verschwindet, verstopfen aber
# nicht die Liste der Dateien, die man wirklich sichten will.
ORPHAN_INTERNAL_SUBFOLDER = "OLAT-interne Dateien"
ORPHAN_INTERNAL_EXTS = (".xml",)

# Rückmeldungen unter einer Frage. {subject} benennt, was bewertet wurde –
# bei einer Sortieraufgabe die Reihenfolge, sonst die Antwort.
QUESTION_FEEDBACK_CORRECT = "{subject} ist richtig."
QUESTION_FEEDBACK_PARTIAL = "{subject} ist teilweise richtig."
QUESTION_FEEDBACK_INCORRECT = "{subject} ist falsch."

# Markierung und Hinweis für Hotspot-Fragen, die in OLAT Ablenker-Bereiche
# hatten. Moodles ddmarker kann sie nicht abbilden: jede Drop-Zone verweist
# über ihr 'choice'-Feld auf einen zugehörigen Marker, eine Zone ohne Marker
# wäre für Lernende unerreichbar. Erfundene Marker für die falschen Bereiche
# würden sie zu KORREKTEN Antworten machen – schlimmer als der Verlust.
#
# Die Frage bleibt lösbar und wird richtig bewertet; sie verliert nur die
# vorgegebene Auswahl. Markierung am Fragenamen und Hinweis im Fragetext,
# damit das auch nach dem Import noch sichtbar ist und nicht nur im
# Protokoll des Konvertierungslaufs stand.
HOTSPOT_REGIONS_LOST_MARKER = "⚠️"

# Mindestradius (Pixel) für kreisförmige Hotspot-Ablagebereiche. OLAT-Kurse
# nutzen dort oft nur 10 Pixel – zum Anklicken eines vorgegebenen Bereichs
# reicht das, zum freien Ablegen einer Markierung in Moodle nicht annähernd.
#
# Bewusst eine Untergrenze statt eines Faktors: ein Faktor würde einen in
# OLAT schon großzügigen Bereich (z.B. 150 Pixel) auf ein Vielfaches
# aufblähen und über den Bildrand hinausschieben. Größere Bereiche bleiben
# so unverändert, nur die unbrauchbar kleinen werden angehoben.
HOTSPOT_MIN_RADIUS = 200
HOTSPOT_REGIONS_LOST_WARNING = (
    '<p style="color:red;">'
    '<strong>Achtung – diese Frage sollte nachbearbeitet werden:</strong> In OLAT gab es '
    '{dropped} weitere anklickbare Bereiche, die nur als falsche Antwort dienten. Moodle '
    'kennt keine solchen Ablenker – die Markierung wird hier <em>frei</em> auf dem Bild '
    'abgelegt statt aus vorgegebenen Bereichen ausgewählt.</p><p style="color:red;">Der '
    'richtige Bereich war in OLAT oft nur wenige Pixel groß – dort genügte das, weil man '
    'ihn nur anklicken musste. Beim freien Ablegen wäre er kaum zu treffen, deshalb wurde '
    'er automatisch auf mindestens {min_radius} Pixel Radius vergrößert. Bitte unter „Frage '
    'bearbeiten“ prüfen, ob die Größe zum Bild passt: zu groß trifft auch daneben, zu klein '
    'wertet richtige Antworten als falsch.</p>'
)

# OLAT-Typen, deren repo.zip KEIN eigener Builder verarbeitet. Ihr
# Paketinhalt muss als normaler Anhang durchgereicht werden, sonst geht er
# verloren: get_node_assets() überspringt repo.zip-Inhalte grundsätzlich,
# weil sie bei cp/scorm/wiki/iqtest sonst doppelt herauskämen (dort
# registriert der jeweilige Builder das Paket selbst).
#
# 'video': OLAT legt eine hochgeladene Videoressource als repo.zip mit
# master/<datei> ab. Einen video_builder gibt es nicht – ohne diesen
# Eintrag käme die Videodatei nirgends an.
PACKAGE_AS_ATTACHMENT_TYPES = {"video"}

# OLAT-Typen ohne funktionale Moodle-Entsprechung: Titel und Beschreibung
# werden übernommen, die eigentliche Funktion (E-Mail verschicken,
# Einschreiben, Bewerten, Abhaken) geht verloren. Sie werden als 'page'
# angelegt statt als 'label' – ein Textfeld hat in Moodle weder Titel noch
# eigene Seite, der Warnhinweis hinge also namenlos zwischen den anderen
# Aktivitäten und ließe sich nicht dem Baustein zuordnen, aus dem er stammt.
# main.py markiert sie zusätzlich mit WARNING_SYMBOL im Titel.
FUNCTIONLESS_OLAT_TYPES = {"co", "en", "checklist", "ms"}

# OLAT-Bausteintyp → Moodle-Modulname.
OLAT_TO_MOODLE_MAPPING = {
    "scorm":            "scorm",
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
    "co":               "page",
    "members":          "label",
    "cepage":           "page",
    "iqself":           "quiz",
    "en":               "page",
    "ll":               "page",
    "survey":           "feedback",
    "cal":              "page",
    "dialog":           "forum",
    "checklist":        "page",
    "appointments":     "choice",
    "projectbroker":    "choice",
    "wiki":             "wiki",
    "gta":              "assign",
    "ms":               "page",
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


# --- Konstanten der GUI (app/gui.py) ---

# Identifiziert das Programm gegenüber der Windows-Taskleiste. Muss eindeutig
# sein und sich zwischen Versionen nicht ändern, sonst behandelt Windows das
# Programm als ein anderes (eigener Taskleisten-Eintrag, verlorene Anheftung).
APP_MODEL_ID = "olat2moodle.konverter"

# Log-Fenster-Farben passend zum jeweiligen sv_ttk-Theme (Text-Widget wird
# von sv_ttk nicht automatisch mitgestylt, da es kein ttk-Widget ist).
LOG_COLORS = {
    "dark": {"bg": "#1c1c1c", "fg": "#e0e0e0", "insertbackground": "#e0e0e0"},   # hell auf dunkel
    "light": {"bg": "#ffffff", "fg": "#1a1a1a", "insertbackground": "#1a1a1a"},  # dunkel auf hell
}

# Farben des Streifens am Zeilenanfang im Log-Fenster, je Kategorie einer
# print()-Zeile (siehe app/gui.py _LINE_CATEGORIES für die Zuordnung
# Präfix → Kategorie).
STRIPE_COLORS = {
    "ok": "#4cd471",        # grün
    "warn": "#f0a83c",      # orange
    "error": "#ef5b5b",     # rot
    "info": "#4a9fe0",      # blau
    "compress": "#b07cf0",  # violett
}

# --- Konstante des Test-Modus (tools/placeholder.py) ---

# Nur Dateien oberhalb dieser Schwelle werden angefasst – kleine Dateien
# bringen kaum Ersparnis. (Echte Kompression mit eigenen Qualitätsstufen
# gibt es nicht mehr hier im Hauptprogramm, siehe
# compression_standalone/compression.py in der Repo-Wurzel.)
TEST_COMPRESSION_THRESHOLD_MB = 1.0
