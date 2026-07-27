"""Grafische Oberfläche für den OLAT-zu-Moodle-Konverter.

Ruft main.convert_olat_to_moodle() unverändert auf und leitet dessen
print()-Ausgaben in ein Log-Fenster um - auch technisch nötig, da
sys.stdout in einem PyInstaller-Windowed-Build sonst None ist und jedes
print() crashen würde. Nutzt sv_ttk für Windows-11-Fluent-Optik mit
Dark-/Light-Umschalter (muss beim Build als Datenverzeichnis mit, siehe
OLAT2Moodle.spec, da es eigene .tcl-Theme-Dateien lädt).
"""

import ctypes
import os
import subprocess
import sys
import queue
import tempfile
import threading
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import sv_ttk

# gui.py liegt in app/, main.py und config.py aber bewusst weiterhin direkt
# in src/ (siehe Struktur-Entscheidung) - Python setzt beim Start eines
# Skripts automatisch nur dessen EIGENEN Ordner auf sys.path (hier also
# app/, nicht dessen Elternordner src/). Ohne diese Zeile fände Python
# "main" deshalb nicht mehr.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import license_gate
from app import single_instance
import main as converter
from tools import placeholder
from config import LOG_COLORS, STRIPE_COLORS, ICON_PATH, APP_MODEL_ID, TEST_COMPRESSION_THRESHOLD_MB


class _QueueWriter:
    """Ersetzt sys.stdout/sys.stderr, damit print()-Ausgaben im Log-Fenster landen.

    Braucht: q (queue.Queue, in die geschriebener Text gelegt wird).

    Wie: implementiert nur write()/flush() - genau das, was print() intern
    aufruft. Der eigentliche GUI-Thread holt die Textstücke später über
    _poll_log_queue() wieder ab, da Tkinter-Widgets nicht direkt aus einem
    anderen Thread heraus verändert werden dürfen.
    """

    def __init__(self, q: queue.Queue):
        """Merkt sich die Queue, in die spätere write()-Aufrufe schreiben."""
        self.q = q

    def write(self, text):
        """Legt den Text in die Queue - macht diese Klasse fürs stdout/stderr-Umleiten nutzbar."""
        if text:
            self.q.put(text)

    def flush(self):
        """No-op, aber nötig: print() ruft flush() auf jedem Ausgabe-Objekt auf."""
        pass


# Farbiger Rand am Zeilenanfang statt Emoji-Symbolen: Windows rendert
# Emoji in Tk nur als Schwarz-Weiß-Umrisse (GDI kennt keine Farb-Font-
# Tabellen, siehe config.LOG_COLORS-Kommentar). Der Rand wird deshalb als
# eigenes kleines Canvas mit abgerundeten Enden gezeichnet und pro Zeile
# eingebettet (siehe _make_stripe_canvas) - Tks eingebaute Randfärbung
# (lmargincolor) kann nur ein rechteckiges Feld ohne Formkontrolle füllen.
_STRIPE_WIDTH = 3
_STRIPE_HEIGHT = 13
_STRIPE_GAP = "   "

_LINE_CATEGORIES = {
    "[+] ": "ok",
    "[ERFOLG] ": "ok",
    "[!] ": "warn",
    "[FEHLER] ": "warn",
    "[*] ": "info",
    "[KOMPRIMIERT] ": "compress",
}


def _format_log_line(line: str):
    """Übersetzt eine rohe print()-Zeile aus main.py & Co. für die Anzeige
    im Log-Fenster: [DEBUG]-Zeilen (interne Selbstchecks/Tracing, nur für
    CLI-Debugging gedacht) werden komplett unterdrückt. Gibt (Text ohne
    Präfix, Kategorie) zurück - Kategorie ist None ohne erkanntes Präfix -
    oder None, wenn die Zeile unterdrückt werden soll."""
    stripped = line.lstrip()
    if stripped.startswith("[DEBUG]"):
        return None
    leading_ws = line[:len(line) - len(stripped)]
    for prefix, category in _LINE_CATEGORIES.items():
        if stripped.startswith(prefix):
            return leading_ws + stripped[len(prefix):], category
    return line, None


class ConverterApp:
    """Hauptfenster: Datei-Auswahl für OLAT-ZIP/Ziel-.mbz, Start-Button, Log-Ausgabe.

    Braucht: root (tk.Tk-Wurzelfenster), log_queue (dieselbe Queue, in die
    _QueueWriter schreibt).
    """

    def __init__(self, root: tk.Tk, log_queue: queue.Queue):
        """Baut das Fenster auf und verkabelt alle Widgets."""
        self.root = root
        self.log_queue = log_queue
        root.title("OLAT zu Moodle Konverter")
        root.geometry("760x660")
        root.minsize(600, 480)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        # Test-Modus ist immer sichtbar (kein Klapp-Bereich, siehe
        # _build_test_mode_section) - Default "aus", damit ein normaler
        # Kurs-Import nicht aus Versehen Inhalte reduziert.
        self.test_mode_method = tk.StringVar(value="aus")
        # Zielpfad des zuletzt ERFOLGREICH erzeugten Backups - erst dann darf
        # der "Zielordner öffnen"-Button darauf zeigen.
        self._last_output = None
        # Sammelt Textstücke aus der Log-Queue, bis eine vollständige Zeile
        # dasteht - print() liefert nicht zwingend ganze Zeilen auf einmal
        # an write() (siehe _QueueWriter).
        self._log_buffer = ""
        self._last_log_line_blank = True
        # Referenzen auf alle eingebetteten Streifen-Canvases (siehe
        # _make_stripe_canvas) - Text.delete() zerstört eingebettete
        # Fenster nicht von selbst, und bei Theme-Wechsel muss ihr
        # Hintergrund passend zu LOG_COLORS nachgezogen werden.
        self._stripe_canvases = []
        # Bleibt True, solange der Nutzer das Ziel-.mbz-Feld nie selbst
        # angefasst hat - dann wird es bei jeder neuen ZIP-Auswahl
        # automatisch mitgeführt. Sobald der Nutzer manuell tippt oder
        # "Speichern unter..." nutzt, wird sein Ziel respektiert und nicht
        # mehr überschrieben (siehe _on_output_changed/_choose_input).
        self._output_auto = True
        self._suppress_output_trace = False
        self.output_path.trace_add("write", self._on_output_changed)

        self._build_widgets()
        self._apply_log_colors()
        self._poll_log_queue()

    def _build_widgets(self):
        """Baut alle Widgets des Hauptfensters auf (Eingabefelder, Buttons, Log-Bereich)."""
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 14))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="OLAT → Moodle Konverter", font=("Segoe UI", 15, "bold")).grid(
            row=0, column=0, sticky="w")
        ttk.Button(header, text="Lizenz", command=self._show_license).grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.theme_button = ttk.Button(header, text="☀ Helles Design", command=self._toggle_theme, width=16)
        self.theme_button.grid(row=0, column=2, sticky="e")

        ttk.Label(outer, text="OLAT-Export (.zip):").grid(row=1, column=0, sticky="w")
        ttk.Entry(outer, textvariable=self.input_path).grid(row=2, column=0, sticky="we", padx=(0, 8))
        ttk.Button(outer, text="Durchsuchen...", command=self._choose_input).grid(row=2, column=1)

        ttk.Label(outer, text="Ziel-.mbz:").grid(row=3, column=0, sticky="w", pady=(14, 0))
        ttk.Entry(outer, textvariable=self.output_path).grid(row=4, column=0, sticky="we", padx=(0, 8))
        ttk.Button(outer, text="Speichern unter...", command=self._choose_output).grid(row=4, column=1)

        self._build_test_mode_section(outer, row=5)

        action_frame = ttk.Frame(outer)
        action_frame.grid(row=6, column=0, columnspan=2, pady=18, sticky="we")
        action_frame.columnconfigure(0, weight=1)

        self.start_button = ttk.Button(
            action_frame, text="Konvertieren", command=self._start_conversion, style="Accent.TButton")
        self.start_button.grid(row=0, column=0, sticky="we", ipady=6)

        # Erst nach erfolgreicher Konvertierung sichtbar (siehe _poll_log_queue).
        self.open_button = ttk.Button(
            action_frame, text="Zielordner öffnen", command=self._open_output_folder)

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.grid(row=7, column=0, columnspan=2, sticky="we", pady=(0, 14))

        ttk.Label(outer, text="Protokoll:").grid(row=8, column=0, sticky="w")
        log_frame = ttk.Frame(outer)
        log_frame.grid(row=9, column=0, columnspan=2, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_widget = tk.Text(
            log_frame, height=18, state="disabled", font=("Consolas", 10),
            relief="flat", borderwidth=0, padx=10, pady=8, wrap="word")
        self.log_widget.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_widget.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_widget.configure(yscrollcommand=log_scroll.set)

        # lmargin1 = 0: die erste Anzeigezeile eines Absatzes beginnt direkt
        # mit dem eingebetteten Streifen-Canvas (siehe _append_log_line),
        # der schon selbst _STRIPE_WIDTH breit ist - ein zusätzlicher
        # lmargin1 würde ihn nur nach rechts verschieben. lmargin2 gilt für
        # durch Zeilenumbruch (wrap="word") entstandene Folgezeilen, die
        # keinen eigenen Streifen mehr bekommen, und ist deshalb auf die
        # gemessene Breite von Streifen + Lücke gesetzt, damit umgebrochener
        # Text bündig unter dem eigentlichen Textanfang weiterläuft statt
        # unter dem Streifen. spacing1 (Abstand VOR der ersten Zeile eines
        # Absatzes) trennt unterschiedliche Log-Einträge optisch - gilt
        # bewusst nicht für Folgezeilen (kein spacing2), die eng an ihrer
        # eigenen ersten Zeile bleiben sollen, nicht wie ein neuer Eintrag.
        log_font = tkfont.Font(font=self.log_widget.cget("font"))
        continuation_indent = _STRIPE_WIDTH + log_font.measure(_STRIPE_GAP)
        self.log_widget.tag_configure(
            "wrapped", lmargin1=0, lmargin2=continuation_indent, spacing1=2)

        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(9, weight=1)

    def _build_test_mode_section(self, outer, row):
        """Baut den Test-Modus-Bereich: zwei gleichrangige Modus-Knöpfe
        (Aus/Platzhalter, gebunden an test_mode_method). Echte Kompression
        (Original-Inhalt bleibt erkennbar, nur kleiner) gibt es nicht mehr
        hier im Hauptprogramm - siehe compression_standalone/compression.py
        in der Repo-Wurzel, ausgelagert weil PyMuPDF+Pillow allein die .exe
        um ~80MB aufgebläht hätten, für ein selten gebrauchtes Feature.
        "Platzhalter" ersetzt beim Ausführen einheitlich alle Kategorien
        (siehe _run_conversion). Für einen echten Kurs-Import bleibt hier
        "Aus"."""
        frame = ttk.LabelFrame(outer, text="Test-Modus: Größe reduzieren")
        frame.grid(row=row, column=0, columnspan=2, sticky="we", pady=(4, 0))
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text="Nur fürs Testsystem – für den echten Kurs-Import auf \"Original\" lassen.",
            wraplength=680, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(6, 10))

        # Echte ttk.Radiobutton/"Toolbutton"-Optik zeigt den gewählten Zustand
        # nur über einen dünnen Rand - in beiden sv_ttk-Themes kaum zu sehen
        # (siehe Nutzer-Feedback). Deshalb stattdessen zwei normale Buttons,
        # deren Style beim Klick manuell umgeschaltet wird: "Accent.TButton"
        # (derselbe kräftige Blauton wie der Konvertieren-Knopf, in beiden
        # Themes bewusst deutlich sichtbar) für den gewählten Modus, normales
        # "TButton" für den Rest - kein Verlass auf Toolbuttons state-Map.
        method_frame = ttk.Frame(frame)
        method_frame.grid(row=1, column=0, sticky="we", padx=10, pady=(0, 10))
        # uniform statt nur weight: sonst bestimmt die jeweils EIGENE
        # Textlänge die Mindestbreite jeder Spalte, und ein Knopf bleibt
        # trotz gleichem weight schmaler als der andere (siehe Nutzer-
        # Feedback: Original/Größe reduzieren waren unterschiedlich breit).
        # uniform zwingt beide Spalten auf dieselbe (die größere) Breite.
        method_frame.columnconfigure(0, weight=1, uniform="test_mode_btn")
        method_frame.columnconfigure(1, weight=1, uniform="test_mode_btn")

        self._test_mode_buttons = {}
        for col, (value, text) in enumerate((
                ("aus", "Original"),
                ("placeholder", "Größe reduzieren"))):
            btn = ttk.Button(method_frame, text=text, command=lambda v=value: self._set_test_mode(v))
            # Lücke zwischen den Knöpfen symmetrisch auf beide Seiten
            # verteilen (3+3 statt 6+0) - sonst frisst das padx nur EINEM
            # Knopf Breite weg und sie sind trotz uniform-Spalten optisch
            # unterschiedlich breit (siehe Nutzer-Feedback).
            btn.grid(row=0, column=col, sticky="we", padx=(0, 3) if col == 0 else (3, 0))
            self._test_mode_buttons[value] = btn
        self._refresh_test_mode_buttons()

    def _set_test_mode(self, value: str):
        """Klick-Handler der Test-Modus-Knöpfe (siehe _build_test_mode_section)."""
        self.test_mode_method.set(value)
        self._refresh_test_mode_buttons()

    def _refresh_test_mode_buttons(self):
        """Färbt den aktuell gewählten Test-Modus-Knopf ein (Accent-Blau),
        alle anderen normal - einziger Ort, der test_mode_method mit der
        Button-Optik synchron hält."""
        selected = self.test_mode_method.get()
        for value, btn in self._test_mode_buttons.items():
            btn.config(style="Accent.TButton" if value == selected else "TButton")

    def _apply_log_colors(self):
        """Färbt das Log-Fenster passend zum aktuellen sv_ttk-Theme ein.

        Wie: sv_ttk stylt nur echte ttk-Widgets automatisch. Das Log ist ein
        klassisches tk.Text (für Scrollbar-Steuerung per yview nötig) und
        bekommt seine Farben deshalb hier von Hand aus LOG_COLORS gesetzt.
        """
        colors = LOG_COLORS[sv_ttk.get_theme()]
        self.log_widget.configure(**colors)
        # Die Streifen-Canvases sind eigene Widgets mit eigenem Hintergrund
        # (siehe _make_stripe_canvas) - der wird von obigem configure()
        # nicht mit erfasst und muss deshalb hier separat nachgezogen werden.
        for canvas in self._stripe_canvases:
            canvas.configure(bg=colors["bg"])

    def _toggle_theme(self):
        """Wechselt zwischen Dark- und Light-Design und passt Button-Text +
        Log-Fenster-Farben entsprechend an."""
        sv_ttk.toggle_theme()
        self._apply_log_colors()
        is_dark = sv_ttk.get_theme() == "dark"
        self.theme_button.config(text="☀ Helles Design" if is_dark else "🌙 Dunkles Design")

    def _show_license(self):
        """Öffnet die Lizenzbedingungen nochmal zum Nachlesen (Lizenz-Knopf im Header)."""
        license_gate.open_viewer(self.root)

    def _on_output_changed(self, *_args):
        """Reagiert auf JEDE Änderung des Ziel-.mbz-Felds - auch direktes
        Tippen, nicht nur die Dialoge. Läuft die Änderung nicht gerade aus
        der eigenen Auto-Vorschlag-Logik (siehe _choose_input), zählt es als
        bewusste Nutzerentscheidung: das Feld wird danach nie mehr
        automatisch überschrieben."""
        if not self._suppress_output_trace:
            self._output_auto = False

    def _choose_input(self):
        """Öffnet den Dateidialog für die OLAT-ZIP und schlägt automatisch einen
        passenden .mbz-Zieldateinamen im Downloads-Ordner vor - so lange, wie
        der Nutzer das Ziel-Feld noch nicht selbst angefasst hat (siehe
        _output_auto), damit eine neu gewählte ZIP den alten Zielnamen auch
        bei einer zweiten/dritten Auswahl mitzieht statt beim ersten hängen
        zu bleiben."""
        path = filedialog.askopenfilename(
            title="OLAT-Export auswählen", filetypes=[("ZIP-Archive", "*.zip"), ("Alle Dateien", "*.*")])
        if path:
            self.input_path.set(path)
            if self._output_auto or not self.output_path.get():
                stem = os.path.splitext(os.path.basename(path))[0]
                downloads = os.path.join(os.path.expanduser("~"), "Downloads")
                self._suppress_output_trace = True
                self.output_path.set(os.path.join(downloads, f"{stem}.mbz"))
                self._suppress_output_trace = False
                self._output_auto = True

    def _choose_output(self):
        """Öffnet den Speichern-unter-Dialog für die Ziel-.mbz - eine so
        gewählte Datei ist eine bewusste Nutzerentscheidung und wird von
        _choose_input danach nicht mehr automatisch überschrieben."""
        path = filedialog.asksaveasfilename(
            title="Moodle-Backup speichern unter", defaultextension=".mbz",
            filetypes=[("Moodle-Backup", "*.mbz"), ("Alle Dateien", "*.*")])
        if path:
            self.output_path.set(path)

    def _open_output_folder(self):
        """Öffnet den Windows-Explorer und markiert die erzeugte .mbz darin."""
        if not self._last_output or not os.path.exists(self._last_output):
            messagebox.showinfo("Hinweis", "Es gibt noch keine erzeugte Datei zum Anzeigen.")
            return
        # explorer /select markiert die Datei im geöffneten Ordner. Kein
        # os.startfile(pfad), das würde die .mbz zu öffnen VERSUCHEN.
        subprocess.Popen(["explorer", "/select,", os.path.normpath(self._last_output)])

    def _start_conversion(self):
        """Validiert die Eingaben und startet die Konvertierung in einem
        Hintergrund-Thread, damit die Oberfläche währenddessen bedienbar bleibt."""
        in_path = self.input_path.get().strip()
        out_path = self.output_path.get().strip()

        if not in_path or not os.path.isfile(in_path):
            messagebox.showerror("Fehler", "Bitte eine gültige OLAT-ZIP-Datei auswählen.")
            return
        if not out_path:
            messagebox.showerror("Fehler", "Bitte einen Ziel-Dateinamen für die .mbz angeben.")
            return

        # Muss hier im GUI-Thread gelesen werden, nicht erst drüben in
        # _run_conversion - das läuft im Hintergrund-Thread, und Tkinter-
        # Variablen von dort aus zu lesen ist nicht zuverlässig (genau wie
        # in_path/out_path hier und nicht dort gelesen werden).
        test_mode_method = self.test_mode_method.get()

        self.start_button.config(state="disabled", text="Konvertiere...")
        self.open_button.grid_remove()
        self.progress.start(12)
        self._clear_log()
        thread = threading.Thread(
            target=self._run_conversion, args=(in_path, out_path, test_mode_method), daemon=True)
        thread.start()

    def _run_conversion(self, in_path: str, out_path: str, test_mode_method: str):
        """Läuft im Hintergrund-Thread: reduziert bei Bedarf erst per
        Test-Modus (siehe _build_test_mode_section) in eine temporäre Kopie,
        ruft dann convert_olat_to_moodle() auf dieser (oder sonst direkt auf
        in_path) auf und meldet Erfolg/Fehler über die Log-Queue an den
        GUI-Thread zurück (__SUCCESS__/__DONE__ als Signale für den
        GUI-Thread). test_mode_method kommt fertig aus _start_conversion
        (siehe dortiger Kommentar, warum das nicht hier gelesen wird):
        "aus" (nichts tun) oder "placeholder" (tools/placeholder.py,
        vorbereitete Ersatzdateien - ersetzt immer alle Kategorien)."""
        compressed_path = None
        try:
            convert_input = in_path
            if test_mode_method == "placeholder":
                fd, compressed_path = tempfile.mkstemp(suffix=".zip")
                os.close(fd)
                self.log_queue.put("[*] Test-Modus: ersetze große Inhalte durch Platzhalter...\n")
                placeholder.replace_course_zip(
                    in_path, compressed_path, video=True, pdf=True, pptx=True,
                    threshold_mb=TEST_COMPRESSION_THRESHOLD_MB)
                convert_input = compressed_path

            converter.convert_olat_to_moodle(convert_input, out_path)
            self.log_queue.put("\n[ERFOLG] Konvertierung abgeschlossen.\n")
            self.log_queue.put(f"__SUCCESS__{out_path}")
        except Exception:
            self.log_queue.put(f"\n[FEHLER] Konvertierung abgebrochen:\n{traceback.format_exc()}\n")
        finally:
            if compressed_path and os.path.exists(compressed_path):
                os.remove(compressed_path)
            self.log_queue.put("__DONE__")

    def _clear_log(self):
        """Leert das Log-Fenster (Text-Widget ist read-only, deshalb kurz aufsperren).

        Text.delete() entfernt eingebettete Streifen-Canvases nicht von
        selbst (sind eigene Fenster, keine reinen Zeichen) - deshalb hier
        zusätzlich explizit zerstören, sonst hängen sie unsichtbar herum.
        """
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.config(state="disabled")
        for canvas in self._stripe_canvases:
            canvas.destroy()
        self._stripe_canvases = []
        self._log_buffer = ""
        self._last_log_line_blank = True

    def _make_stripe_canvas(self, color: str) -> tk.Canvas:
        """Zeichnet den farbigen Rand als eigenes kleines Canvas mit
        abgerundeten Enden (zwei Ovale als Kappen, Rechteck dazwischen) -
        Tks eingebaute Randfärbung (lmargincolor) kann nur ein Rechteck ohne
        Ecken-Kontrolle füllen, siehe Kommentar bei STRIPE_COLORS."""
        bg = self.log_widget.cget("bg")
        canvas = tk.Canvas(self.log_widget, width=_STRIPE_WIDTH, height=_STRIPE_HEIGHT,
                           highlightthickness=0, bd=0, bg=bg)
        r = _STRIPE_WIDTH
        canvas.create_oval(0, 0, r, r, fill=color, outline="")
        canvas.create_rectangle(0, r / 2, r, _STRIPE_HEIGHT - r / 2, fill=color, outline="")
        canvas.create_oval(0, _STRIPE_HEIGHT - r, r, _STRIPE_HEIGHT, fill=color, outline="")
        self._stripe_canvases.append(canvas)
        return canvas

    def _append_log_line(self, line: str):
        """Filtert/übersetzt eine vollständige Zeile über _format_log_line()
        und hängt sie bei Bedarf ans Log-Fenster an. Mehrere Leerzeilen in
        Folge werden zu einer zusammengefasst - sonst blieben an den jetzt
        komplett unterdrückten [DEBUG]-Blöcken (die oft mit einer eigenen
        Leerzeile umrahmt sind) leere Lücken im Log stehen."""
        result = _format_log_line(line)
        if result is None:
            return
        text, category = result
        if not text.strip():
            if self._last_log_line_blank:
                return
            self._last_log_line_blank = True
        else:
            self._last_log_line_blank = False
        self.log_widget.config(state="normal")
        if category:
            canvas = self._make_stripe_canvas(STRIPE_COLORS[category])
            self.log_widget.window_create(tk.END, window=canvas, align="center")
            self.log_widget.insert(tk.END, _STRIPE_GAP + text + "\n", "wrapped")
        else:
            self.log_widget.insert(tk.END, text + "\n", "wrapped")
        self.log_widget.see(tk.END)
        self.log_widget.config(state="disabled")

    def _poll_log_queue(self):
        """Holt alle wartenden Textstücke aus der Queue und hängt vollständige,
        gefilterte Zeilen ans Log-Fenster an.

        Wie: läuft alle 100ms im GUI-Thread (root.after-Selbstaufruf), da
        Tkinter-Widgets nur aus dem Hauptthread heraus verändert werden
        dürfen - der Konvertierungs-Thread schreibt nur in die Queue,
        niemals direkt ins Widget. Textstücke werden gepuffert, bis eine
        vollständige Zeile dasteht (print() liefert nicht zwingend ganze
        Zeilen auf einmal), erst dann geht's durch _format_log_line().
        """
        try:
            while True:
                text = self.log_queue.get_nowait()
                if text == "__DONE__":
                    if self._log_buffer:
                        self._append_log_line(self._log_buffer)
                        self._log_buffer = ""
                    self.start_button.config(state="normal", text="Konvertieren")
                    self.progress.stop()
                    continue
                if text.startswith("__SUCCESS__"):
                    self._last_output = text[len("__SUCCESS__"):]
                    self.open_button.grid(row=1, column=0, sticky="we", pady=(8, 0))
                    continue
                self._log_buffer += text
                while "\n" in self._log_buffer:
                    line, self._log_buffer = self._log_buffer.split("\n", 1)
                    self._append_log_line(line)
        except queue.Empty:
            pass
        # noinspection PyTypeChecker
        # JetBrains-Bug, nicht fixbar
        self.root.after(100, self._poll_log_queue)


def main():
    """Startet die GUI: leitet stdout/stderr um, setzt das sv_ttk-Dark-Theme
    und öffnet dann das Hauptfenster."""
    # Muss vor der ersten Fenster-Erzeugung passieren: ohne DPI-Awareness
    # skaliert Windows bei Anzeige-Skalierung >100% das ganze Tkinter-Fenster
    # nachträglich als Bitmap hoch - Text wirkt dann unscharf, obwohl die
    # Schriftart selbst (z.B. Consolas) identisch ist.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass

    # Ebenfalls vor der ersten Fenster-Erzeugung: Windows ordnet Fenster in
    # der Taskleiste anhand der AppUserModelID einem Programm zu. Ohne eigene
    # ID erbt der Prozess die des Hosts - beim Start aus dem Quellcode also
    # die von python.exe, dessen Icon dann in der Taskleiste steht statt des
    # Fenster-Icons.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_MODEL_ID)
    except (AttributeError, OSError):
        pass

    log_queue = queue.Queue()
    sys.stdout = _QueueWriter(log_queue)
    sys.stderr = sys.stdout

    root = tk.Tk()
    root.withdraw()

    # Icon für Titelleiste und Taskleiste. Das über OLAT2Moodle.spec in die
    # .exe eingebettete Icon gilt nur für die Datei im Explorer - ein
    # laufendes Fenster holt sich seines von Tk und zeigt sonst dessen
    # Standard-Feder. default=True vererbt es an alle weiteren Fenster
    # (messagebox, Dateiauswahl), die sonst wieder die Feder tragen würden.
    try:
        root.iconbitmap(default=ICON_PATH)
    except tk.TclError:
        # Fehlende Icon-Datei darf den Start nicht verhindern.
        pass

    if single_instance.already_running():
        messagebox.showwarning(
            "Bereits geöffnet",
            "Der OLAT zu Moodle Konverter läuft schon in einem anderen Fenster.")
        sys.exit(0)

    sv_ttk.set_theme("dark")

    # Zeigt bei Bedarf die Zustimmungs-Oberfläche DIREKT in root (siehe
    # license_gate.enforce) und kehrt erst zurück, wenn root wieder leer
    # und versteckt ist - danach erst wird das eigentliche Hauptfenster
    # hineingebaut, nie beides gleichzeitig im selben Fenster.
    license_gate.enforce(root)

    ConverterApp(root, log_queue)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
