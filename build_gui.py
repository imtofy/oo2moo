"""Build-Startzentrale: baut per Knopfdruck die .exe aus olat_to_moodle -
ohne dass dafür ein Terminal geöffnet werden muss.

Ruft dafür exakt dasselbe Kommando auf, das auch von Hand in der Konsole
liefe (PyInstaller). Dieses Skript ist nur eine Oberfläche drumherum, keine
eigene Build-Logik - die bleibt alleine in OLAT2Moodle.spec.

Sitzt bewusst eine Ebene über dem Projektordner (statt darin zu liegen).
Bewusst mitversioniert (siehe .gitignore-Kommentar dazu).
"""

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import sv_ttk

THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = THIS_DIR / "olat_to_moodle"

_BUILD = {
    "label": "Bauen",
    "cwd": PROJECT_DIR,
    "cmd": [sys.executable, "-m", "PyInstaller", "OLAT2Moodle.spec", "--noconfirm"],
    "exe": PROJECT_DIR / "dist" / "Olat_to_Moodle.exe",
}

_LOG_COLORS = {
    "dark": {"bg": "#1c1c1c", "fg": "#e0e0e0", "insertbackground": "#e0e0e0"},
    "light": {"bg": "#ffffff", "fg": "#1a1a1a", "insertbackground": "#1a1a1a"},
}


class BuildLauncherApp:
    """Hauptfenster: ein Build-Button + Log-Fenster.

    Braucht: root (tk.Tk-Wurzelfenster), log_queue (Queue, in die
    _run_build() aus dem Hintergrund-Thread schreibt).
    """

    def __init__(self, root: tk.Tk, log_queue: queue.Queue):
        self.root = root
        self.log_queue = log_queue
        root.title("OLAT2Moodle Build-Zentrale")
        root.geometry("780x540")
        root.minsize(620, 420)

        self._build_running = False
        self._button = None

        self._build_widgets()
        self._apply_log_colors()
        self._poll_log_queue()

    def _build_widgets(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 14))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="OLAT2Moodle Build-Zentrale", font=("Segoe UI", 15, "bold")).grid(
            row=0, column=0, sticky="w")
        self.theme_button = ttk.Button(header, text="☀ Helles Design", command=self._toggle_theme, width=16)
        self.theme_button.grid(row=0, column=1, sticky="e")

        btn_frame = ttk.Frame(outer)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 14))
        btn_frame.columnconfigure(0, weight=1)

        build_btn = ttk.Button(btn_frame, text=_BUILD["label"],
                               command=self._start_build, style="Accent.TButton")
        build_btn.grid(row=0, column=0, sticky="we", ipady=6)
        self._button = build_btn

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.grid(row=2, column=0, columnspan=2, sticky="we", pady=(0, 14))

        ttk.Label(outer, text="Protokoll:").grid(row=3, column=0, sticky="w")
        log_frame = ttk.Frame(outer)
        log_frame.grid(row=4, column=0, columnspan=2, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_widget = tk.Text(log_frame, height=20, state="disabled", font=("Consolas", 9),
                                  relief="flat", borderwidth=0, padx=10, pady=8, wrap="word")
        self.log_widget.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_widget.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_widget.configure(yscrollcommand=log_scroll.set)

        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)

    def _apply_log_colors(self):
        """Färbt das Log-Fenster passend zum aktuellen sv_ttk-Theme ein
        (tk.Text ist kein ttk-Widget, sv_ttk stylt es nicht automatisch)."""
        colors = _LOG_COLORS[sv_ttk.get_theme()]
        self.log_widget.configure(**colors)

    def _toggle_theme(self):
        sv_ttk.toggle_theme()
        self._apply_log_colors()
        is_dark = sv_ttk.get_theme() == "dark"
        self.theme_button.config(text="☀ Helles Design" if is_dark else "🌙 Dunkles Design")

    def _start_build(self):
        """Startet den Build im Hintergrund-Thread, damit die Oberfläche
        währenddessen bedienbar bleibt; sperrt den Button, solange ein
        Build läuft (kein gleichzeitiger zweiter Build)."""
        if self._build_running:
            return
        self._build_running = True
        self._button.config(state="disabled")
        self.progress.start(12)
        self._clear_log()
        thread = threading.Thread(target=self._run_build, daemon=True)
        thread.start()

    def _run_build(self):
        """Läuft im Hintergrund-Thread: startet den Build-Prozess (PyInstaller)
        und leitet dessen Ausgabe zeilenweise über die Log-Queue an den
        GUI-Thread weiter (__DONE__ als Abschlusssignal, um den Button
        wieder freizugeben)."""
        self.log_queue.put(f"=== {_BUILD['label']} ===\n\n")
        try:
            process = subprocess.Popen(
                _BUILD["cmd"], cwd=_BUILD["cwd"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1)
            for line in process.stdout:
                self.log_queue.put(line)
            return_code = process.wait()
            if return_code == 0 and _BUILD["exe"].exists():
                size_mb = _BUILD["exe"].stat().st_size / (1024 * 1024)
                self.log_queue.put(f"\n[ERFOLG] {_BUILD['exe']} ({size_mb:.1f} MB)\n")
            else:
                self.log_queue.put(f"\n[FEHLER] Build fehlgeschlagen (Exit-Code {return_code}).\n")
        except Exception as exc:
            self.log_queue.put(f"\n[FEHLER] {exc}\n")
        finally:
            self.log_queue.put("__DONE__")

    def _clear_log(self):
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.config(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                text = self.log_queue.get_nowait()
                if text == "__DONE__":
                    self._build_running = False
                    self._button.config(state="normal")
                    self.progress.stop()
                    continue
                self.log_widget.config(state="normal")
                self.log_widget.insert(tk.END, text)
                self.log_widget.see(tk.END)
                self.log_widget.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)


def main():
    log_queue = queue.Queue()
    root = tk.Tk()
    sv_ttk.set_theme("dark")
    BuildLauncherApp(root, log_queue)
    root.mainloop()


if __name__ == "__main__":
    main()
