"""Click-Wrap-Zustimmung zur APTL-Lizenz: zeigt beim ersten Start (und nach
jeder inhaltlichen Lizenzänderung) ein Pflicht-Dialogfenster mit dem
vollständigen Lizenztext, das vor dem eigentlichen Programmstart bestätigt
werden muss. Ein bloßer Hinweis auf einer Downloadseite reicht für einen
wirksamen Vertragsschluss nicht aus - dieses Modul ist der Mechanismus, der
die in der Präambel der Lizenz genannte "Bestätigung beim erstmaligen
Start" tatsächlich erzwingt.
"""
import hashlib
import json
import os
import re
import sys
import tkinter as tk
import webbrowser
import winreg
from tkinter import messagebox, ttk

import sv_ttk

import config

_REGISTRY_KEY = r"Software\Olat_to_Moodle"
_REGISTRY_VALUE = "LicenseAcceptedHash"

_MUTED_COLORS = {"dark": "#9a9a9a", "light": "#5f5f5f"}
_LINK_COLORS = {"dark": "#4da6ff", "light": "#0b5fc7"}

# Erkennt entweder `code` oder [Text](Ziel) - eine gemeinsame Regel statt
# zwei getrennter Durchläufe, damit beide Token-Arten in der richtigen
# Reihenfolge im Fließtext verarbeitet werden, egal wie sie gemischt vorkommen.
_INLINE_TOKEN = re.compile(r'`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)')


def _fallback_marker_path() -> str:
    """Pfad zur Fallback-Marker-Datei - nur genutzt, wenn die Registry
    weder lesbar noch beschreibbar ist (z.B. in einer eingeschränkten
    Firmenumgebung). Liegt in %APPDATA%, nicht neben der .exe - ein
    Ersetzen/Neuherunterladen der .exe verliert die Zustimmung so nicht."""
    appdata = os.getenv("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(appdata, "Olat_to_Moodle")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "license_accepted.json")


def _read_accepted_hash() -> str | None:
    """Liest den vermerkten Zustimmungs-Hash - zuerst aus der Registry
    (HKEY_CURRENT_USER\\Software\\Olat_to_Moodle), bei Fehlschlag aus der
    Fallback-Datei."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _REGISTRY_VALUE)
            return value
    except OSError:
        pass
    marker_path = _fallback_marker_path()
    if not os.path.exists(marker_path):
        return None
    try:
        with open(marker_path, encoding="utf-8") as f:
            return json.load(f).get("accepted_hash")
    except (OSError, json.JSONDecodeError):
        return None


def _write_accepted_hash(value: str) -> None:
    """Schreibt den Zustimmungs-Hash bevorzugt in die Registry; schlägt das
    fehl (z.B. keine Schreibrechte dort), landet er stattdessen in der
    Fallback-Datei."""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY) as key:
            winreg.SetValueEx(key, _REGISTRY_VALUE, 0, winreg.REG_SZ, value)
        return
    except OSError:
        pass
    with open(_fallback_marker_path(), "w", encoding="utf-8") as f:
        json.dump({"accepted_hash": value}, f)


def _license_hash(license_text: str) -> str:
    """Fingerabdruck des Lizenztexts - jede inhaltliche Änderung ändert den
    Hash und macht eine alte Zustimmung automatisch ungültig."""
    return hashlib.sha256(license_text.encode("utf-8")).hexdigest()


def read_license_text() -> str:
    """Liest LICENSE.md - dieselbe Datei, die auch auf GitHub angezeigt
    wird, kein separat gepflegter Text."""
    with open(config.LICENSE_PATH, encoding="utf-8") as f:
        return f.read()


def has_accepted_current_license() -> bool:
    """True, wenn die aktuell gültige Lizenzfassung bereits bestätigt wurde."""
    return _read_accepted_hash() == _license_hash(read_license_text())


def record_acceptance() -> None:
    """Vermerkt die Zustimmung zur aktuellen Lizenzfassung."""
    _write_accepted_hash(_license_hash(read_license_text()))


def render_into(text_widget: tk.Text, license_text: str) -> None:
    """Baut den Lizenztext mit einfacher Formatierung in ein bestehendes
    Text-Widget (Überschriften fett/größer statt der rohen '#'/'##'-
    Markdown-Zeichen, `code`-Abschnitte in Monospace) - reine Anzeige, kein
    waschechter Markdown-Parser. Genutzt sowohl vom Zustimmungs-Gate als
    auch vom "Lizenz"-Knopf im Hauptfenster (siehe open_viewer)."""
    text_widget.tag_configure("h1", font=("Segoe UI", 14, "bold"), spacing3=10)
    text_widget.tag_configure("h2", font=("Segoe UI", 11, "bold"), spacing1=14, spacing3=6)
    text_widget.tag_configure("body", font=("Segoe UI", 10), spacing3=8)
    text_widget.tag_configure("muted", font=("Segoe UI", 9))
    text_widget.tag_configure("code", font=("Consolas", 9))
    text_widget.tag_configure("link", underline=True)

    for i, line in enumerate(license_text.split("\n")):
        if line.startswith("# "):
            text_widget.insert("end", line[2:] + "\n", "h1")
        elif line.startswith("## "):
            text_widget.insert("end", line[3:].lstrip() + "\n", "h2")
        elif not line.strip():
            text_widget.insert("end", "\n")
        elif i == 0 and line.startswith("Copyright"):
            text_widget.insert("end", line + "\n", "muted")
        else:
            _insert_body_line(text_widget, line)


def _insert_body_line(text_widget: tk.Text, line: str) -> None:
    """Fügt eine normale Textzeile ein, `code`-Abschnitte darin bekommen
    die Monospace-Schrift, [Text](Ziel)-Links werden klickbar (öffnet Ziel
    im Standardbrowser) - der Renderer ist bewusst kein voller
    Markdown-Parser, siehe render_into()."""
    pos = 0
    for match in _INLINE_TOKEN.finditer(line):
        text_widget.insert("end", line[pos:match.start()], "body")
        code_text, link_text, link_target = match.groups()
        if code_text is not None:
            text_widget.insert("end", code_text, ("body", "code"))
        else:
            _insert_link(text_widget, link_text, link_target)
        pos = match.end()
    text_widget.insert("end", line[pos:] + "\n", "body")


def _insert_link(text_widget: tk.Text, text: str, target: str) -> None:
    """Fügt anklickbaren Linktext ein - der Tag-Name leitet sich vom Ziel
    ab, mehrere Vorkommen desselben Ziels teilen sich also denselben Tag
    (erneutes tag_bind() darauf überschreibt nur mit demselben Handler,
    unschädlich)."""
    tag = "link_" + re.sub(r'[^A-Za-z0-9]', '_', target)
    text_widget.insert("end", text, ("body", "link", tag))
    text_widget.tag_bind(tag, "<Button-1>", lambda _e: webbrowser.open(target))
    text_widget.tag_bind(tag, "<Enter>", lambda _e: text_widget.config(cursor="hand2"))
    text_widget.tag_bind(tag, "<Leave>", lambda _e: text_widget.config(cursor=""))


def apply_theme_colors(text_widget: tk.Text) -> None:
    """Färbt ein mit render_into() befülltes Text-Widget passend zum
    aktuellen sv_ttk-Theme ein (tk.Text ist kein ttk-Widget, wird nicht
    automatisch mitgestylt)."""
    theme = sv_ttk.get_theme()
    text_widget.configure(**config.LOG_COLORS[theme])
    text_widget.tag_configure("muted", foreground=_MUTED_COLORS[theme])
    text_widget.tag_configure("link", foreground=_LINK_COLORS[theme])


def open_viewer(parent: tk.Tk) -> None:
    """Öffnet die Lizenz nochmal zum Nachlesen - nicht-modal, nur eine
    Schließen-Schaltfläche, kein Zustimmen/Ablehnen. Anders als
    _LicenseGateFrame ist hier ein normales Toplevel mit grab_set()
    unproblematisch: das Hauptfenster (parent) ist an dieser Stelle längst
    sichtbar. Toplevel+grab_set auf einem Elternfenster, das noch nie
    gezeigt wurde, bleibt auf Windows dagegen komplett unsichtbar (siehe
    _LicenseGateFrame-Docstring)."""
    win = tk.Toplevel(parent)
    win.title("Lizenzbedingungen - Academic and Personal Transparency License (APTL) 1.0")
    win.geometry("640x560")
    win.minsize(480, 380)
    win.transient(parent)

    text_frame = ttk.Frame(win)
    text_frame.pack(fill="both", expand=True, padx=16, pady=16)
    text_widget = tk.Text(
        text_frame, wrap="word", relief="flat", borderwidth=0, padx=10, pady=8, font=("Segoe UI", 10))
    scroll = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
    scroll.pack(side="right", fill="y")
    text_widget.pack(side="left", fill="both", expand=True)
    text_widget.configure(yscrollcommand=scroll.set)

    render_into(text_widget, read_license_text())
    apply_theme_colors(text_widget)
    text_widget.config(state="disabled")

    ttk.Button(win, text="Schließen", command=win.destroy).pack(pady=(0, 16))


class _LicenseGateFrame(ttk.Frame):
    """Füllt das Hauptfenster VOR dem eigentlichen Konverter komplett mit
    Lizenztext + Zustimmen/Ablehnen - bewusst kein separates Toplevel-
    Dialogfenster mit grab_set(): diese Kombination bleibt auf Windows
    unsichtbar, wenn das Elternfenster noch nie gezeigt wurde. Ein
    einzelnes Fenster, das nacheinander zwei verschiedene Inhalte zeigt,
    vermeidet das von vornherein.

    "Zustimmen" bleibt gesperrt, bis bis zum Ende gescrollt wurde - reine
    Textanzeige ohne erzwungenes Lesen wäre keine echte "zumutbare
    Kenntnisnahme" (siehe Modul-Docstring).

    Braucht: master (tk.Tk-Wurzelfenster), license_text (str). Ergebnis
    steht nach master.mainloop() in self.result (True = zugestimmt) -
    _on_accept/_on_reject beenden den mainloop() über master.quit(), ohne
    master selbst zu zerstören.
    """

    def __init__(self, master: tk.Tk, license_text: str):
        """Baut die Zustimmungs-Oberfläche auf und packt sie in master."""
        super().__init__(master)
        self.result = False
        master.protocol("WM_DELETE_WINDOW", self._on_reject)
        self.pack(fill="both", expand=True)

        header = ttk.Frame(self)
        header.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(
            header, text="Bitte die Lizenzbedingungen lesen und bestätigen:",
            font=("Segoe UI", 11, "bold")
        ).pack(side="left")
        self._theme_button = ttk.Button(header, text="🌙 Dunkles Design", command=self._toggle_theme, width=16)
        self._theme_button.pack(side="right")

        text_frame = ttk.Frame(self)
        text_frame.pack(fill="both", expand=True, padx=16)
        self._text_widget = tk.Text(
            text_frame, wrap="word", relief="flat", borderwidth=0, padx=10, pady=8, font=("Segoe UI", 10))
        # Scrollbar VOR dem expandierenden Textfeld packen - andersrum
        # bekommt sie keinen Platz mehr zugeteilt und verschwindet
        # praktisch unsichtbar.
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self._on_scrollbar)
        scroll.pack(side="right", fill="y")
        self._text_widget.pack(side="left", fill="both", expand=True)
        self._text_widget.configure(yscrollcommand=self._on_text_scroll)
        self._scrollbar = scroll

        render_into(self._text_widget, license_text)
        self._text_widget.config(state="disabled")

        self._jump_button = ttk.Button(text_frame, text="⬇ Zum Ende springen", command=self._jump_to_end)
        self._jump_button.place(in_=self._text_widget, relx=1.0, rely=1.0, x=-14, y=-14, anchor="se")

        button_frame = ttk.Frame(self)
        button_frame.pack(fill="x", padx=16, pady=16)
        self._progress_label = ttk.Label(button_frame, text="Noch nicht bis zum Ende gelesen")
        self._progress_label.pack(side="left")
        ttk.Button(button_frame, text="Ablehnen", command=self._on_reject).pack(side="right", padx=(8, 0))
        self._accept_button = ttk.Button(
            button_frame, text="Zustimmen", command=self._on_accept, style="Accent.TButton", state="disabled")
        self._accept_button.pack(side="right")

        self._apply_theme_colors()
        # Passt Zustimmen/Sprung-Button/Hinweistext gleich einmal an den
        # Ist-Zustand an - falls der Text von Anfang an komplett ins
        # Fenster passt, ohne dass je gescrollt werden musste.
        # noinspection PyTypeChecker
        # JetBrains-Bug, nicht fixbar
        self.after_idle(self._update_scroll_gate)

    def _on_text_scroll(self, first, last):
        """yscrollcommand-Callback - hält die Scrollbar synchron und prüft
        bei JEDER Scroll-Ursache (Mausrad, Tastatur, Scrollbar-Ziehen,
        programmatisch) automatisch, ob das Textende erreicht wurde."""
        self._scrollbar.set(first, last)
        self._update_scroll_gate(float(last))

    def _on_scrollbar(self, *args):
        """command-Callback der Scrollbar - reicht die Bewegung ans
        Textfeld weiter, dessen yscrollcommand dann _on_text_scroll auslöst."""
        self._text_widget.yview(*args)

    def _update_scroll_gate(self, bottom_fraction=None):
        """Schaltet Zustimmen frei, sobald das Textende sichtbar ist, und
        blendet den Sprung-Button dann aus."""
        if bottom_fraction is None:
            bottom_fraction = self._text_widget.yview()[1]
        at_bottom = bottom_fraction >= 0.999
        self._accept_button.config(state="normal" if at_bottom else "disabled")
        self._progress_label.config(text="Vollständig gelesen" if at_bottom else "Noch nicht bis zum Ende gelesen")
        if at_bottom:
            self._jump_button.place_forget()
        else:
            self._jump_button.place(in_=self._text_widget, relx=1.0, rely=1.0, x=-14, y=-14, anchor="se")

    def _jump_to_end(self):
        """Springt direkt ans Textende (Klick auf '⬇ Zum Ende springen')."""
        self._text_widget.yview_moveto(1.0)

    def _toggle_theme(self):
        """Wechselt Dark/Light global (wirkt auch auf das noch verborgene
        Hauptfenster) und passt Text-/Hinweisfarben entsprechend an."""
        sv_ttk.toggle_theme()
        self._apply_theme_colors()

    def _apply_theme_colors(self):
        """Färbt das Textfeld passend zum aktuellen sv_ttk-Theme ein und
        passt den Theme-Knopf-Text an."""
        apply_theme_colors(self._text_widget)
        is_dark = sv_ttk.get_theme() == "dark"
        self._theme_button.config(text="☀ Helles Design" if is_dark else "🌙 Dunkles Design")

    def _on_accept(self):
        """Merkt die Zustimmung und beendet den Warte-mainloop() aus enforce()."""
        self.result = True
        self.master.quit()

    def _on_reject(self):
        """Beendet den Warte-mainloop() ohne Zustimmung - Programmstart
        wird danach in enforce() abgebrochen."""
        self.result = False
        self.master.quit()


def enforce(root: tk.Tk) -> None:
    """Zeigt bei Bedarf die Zustimmungs-Oberfläche direkt in root (siehe
    _LicenseGateFrame) und beendet das Programm sofort, falls abgelehnt
    wird. Baut root für die Dauer der Anzeige selbst auf/ab (deiconify beim
    Zeigen, danach wieder withdraw) - der Aufrufer muss root nur einmal vor
    und einmal nach diesem Aufruf behandeln, nicht währenddessen."""
    if has_accepted_current_license():
        return
    license_text = read_license_text()
    root.title("Lizenzbedingungen - Academic and Personal Transparency License (APTL) 1.0")
    root.geometry("640x560")
    root.minsize(480, 380)
    root.deiconify()

    gate = _LicenseGateFrame(root, license_text)
    root.mainloop()  # läuft, bis _on_accept/_on_reject root.quit() auslöst

    root.withdraw()
    gate.destroy()
    # WM_DELETE_WINDOW wieder auf das normale Schließverhalten zurücksetzen -
    # sonst würde ein Schließen des späteren Hauptfensters noch den
    # längst nicht mehr gültigen root.quit()-Reflex aus der Gate-Phase auslösen.
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    if not gate.result:
        messagebox.showinfo(
            "Lizenz abgelehnt",
            "Ohne Zustimmung zu den Lizenzbedingungen kann die Software nicht genutzt werden.")
        sys.exit(0)
    record_acceptance()
