"""Filtert echte Nutzerkennungen aus dem OLAT-Export, BEVOR irgendein anderes
Modul den Content zu sehen bekommt - CourseManifest ruft sanitize_vfs() einmal
direkt nach dem Einlesen auf. Parser, node_processor, html_cleaner usw.
bekommen dadurch automatisch nur den bereinigten Content, ohne dass die
Anonymisierung an anderer Stelle im Code nochmal berücksichtigt werden muss.

Bekannte OLAT-Kennungs-Formate (siehe PATTERNS unten):
  - 'B' + 2 Buchstaben + 4 Ziffern (aktuelles Format, z.B. 'BAA0000')
  - 'u' + 9 Ziffern (uraltes Format, z.B. 'u000000000')
  - '<name>-admin' (Service-/Admin-Accounts, meist aus echtem Nachnamen,
    z.B. 'mustermann-admin')
  - E-Mail-Adressen

Lässt sich einfach erweitern: einfach ein weiteres re.compile(...) in
PATTERNS ergänzen, falls ein neues Format auftaucht.
"""
import re
from config import PLACEHOLDER_USERNAME

PATTERNS = [
    re.compile(r'\bB[A-Z]{2}\d{4}\b'),                              # z.B. BAA0000
    re.compile(r'\bu\d{9}\b'),                                      # z.B. u000000000 (altes Format)
    re.compile(r'\b[a-zA-Z]+-admin\b'),                             # z.B. mustermann-admin
    re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'),  # E-Mail-Adressen
]

_TEXT_EXTENSIONS = ('.xml', '.html', '.htm')


def sanitize_vfs(vfs: dict) -> int:
    """Ersetzt in-place jeden Treffer in jeder Text-Datei im VFS (XML/HTML -
    Bilder/Videos etc. werden übersprungen, auch wenn die verschachtelt in
    repo.zip/oonode.zip stecken, weil CourseManifest das vorher schon flach
    in vfs entpackt hat). Gibt zurück, wie viele Treffer ersetzt wurden, fürs Log."""
    replaced = 0
    for path, data in vfs.items():
        if not path.split('|')[-1].lower().endswith(_TEXT_EXTENSIONS):
            continue
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            continue

        new_text = text
        for pattern in PATTERNS:
            new_text, n = pattern.subn(PLACEHOLDER_USERNAME, new_text)
            replaced += n

        if new_text != text:
            vfs[path] = new_text.encode('utf-8')

    return replaced
