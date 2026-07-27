# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    ['src/app/gui.py'],
    # "src" hier nötig, damit PyInstallers statische Analyse main.py/config.py
    # findet - die liegen bewusst eine Ebene über gui.py (siehe src/app/gui.py,
    # das sys.path zur Laufzeit genauso ergänzt).
    pathex=['src'],
    binaries=[],
    # Die .ico steht zusätzlich unten bei icon= - das setzt aber nur das
    # Symbol der Datei im Explorer. Für das Fenster-Icon zur Laufzeit muss
    # sie als echte Datei mit ins Bundle (siehe config._icon_path). Die drei
    # placeholder.*-Dateien sind die fest vorbereiteten Test-Modus-Vorlagen
    # (siehe tools/placeholder.py, config._placeholder_path) - werden nie
    # zur Laufzeit neu erzeugt, nur mitgeliefert.
    datas=[('src/moodle_musterkurs', 'moodle_musterkurs'), ('../LICENSE.md', '.'),
           ('assets/OLAT2Moodle.ico', '.'), ('assets/placeholder.mp4', '.'),
           ('assets/placeholder.pdf', '.'), ('assets/placeholder.pptx', '.'),
           ] + collect_data_files('sv_ttk'),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Werden von PyInstaller sonst ungefragt mitgebündelt, obwohl der
    # Konverter sie gar nicht braucht. PIL/Pillow ist seit dem Rauswurf von
    # compression.py (siehe compression_standalone/) nirgends mehr
    # importiert - explizit ausschließen, falls ein alter Build-Cache es
    # trotzdem noch mitschleppt. cryptography kommt nur über pypdfs
    # OPTIONALE Unterstützung für verschlüsselte PDFs rein (brauchen wir
    # nicht, unsere PDFs sind nie verschlüsselt) - allein die Rust-Bindings
    # davon sind ~9MB.
    excludes=['numpy', 'lxml', 'Cython', 'PIL', 'cryptography'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Olat_to_Moodle',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Multi-Resolution-.ico (16 bis 256 px) - Windows greift sich je nach
    # Kontext die passende Stufe (Taskleiste, Explorer, Alt-Tab).
    icon='assets/OLAT2Moodle.ico',
)
