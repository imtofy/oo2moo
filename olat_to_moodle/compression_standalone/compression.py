"""Komprimiert Videos, PDFs und PPTX in einem OLAT-Kursexport verlustbehaftet –
eigenständiges Zusatzprogramm, NICHT Teil der Haupt-.exe.

War ursprünglich als Test-Modus im Hauptprogramm eingebaut, wurde aber wieder
rausgenommen: PyMuPDF+Pillow allein blähten die Haupt-.exe um ~80MB auf, für
ein Feature, das im Alltag kaum gebraucht wird (tools/placeholder.py deckt den
üblichen Testfall – schnell große Dateien loswerden – bereits ab, ohne diese
Abhängigkeiten). Bleibt hier als eigenständiges Skript erhalten, falls doch
nochmal echte, aber kleinere Testdateien gebraucht werden – braucht eigene
requirements (PyMuPDF, Pillow) und ffmpeg auf dem PATH, beides NICHT Teil der
requirements.txt des Hauptprogramms.

Der Originalinhalt bleibt sichtbar/abspielbar, nur in reduzierter Qualität
(siehe TEST_COMPRESSION_LEVELS unten für die genauen Werte).

Videos: ffmpeg-Re-Encode (Auflösung/Framerate/CRF gedeckelt). Braucht ffmpeg
auf dem PATH – fehlt es, wird die Video-Kompression übersprungen (mit
Hinweis), der Rest läuft weiter. Hardware-Encoding (NVENC) wurde getestet,
brachte bei den hier üblichen kleinen Zielauflösungen aber keinen messbaren
Zeitgewinn (Flaschenhals liegt woanders) und ist zudem nicht auf jedem
Rechner verfügbar – deshalb bewusst bei Software-libx264 geblieben.

PDFs: jede Seite wird als Pixmap gerendert und als JPEG neu eingebettet (über
PyMuPDF+Pillow) – das ist die einzige verlässliche Art, eingebettete
Scan-Bilder in einer PDF wirklich kleiner zu kriegen. Bei einer PDF mit
echtem (nicht gescanntem) Text geht dabei die Text-Auswahl/Suche verloren,
der Text selbst bleibt aber lesbar (nur nicht mehr scharf wie Vektortext).

PPTX: bleibt eine echte, weiterhin in PowerPoint öffenbare Datei – PPTX ist
selbst nur ein zip, dessen Bilder/Audio unter ppt/media/ liegen. Bei
Vorlesungsaufzeichnungen mit Folien-Vertonung steckt die eigentliche Größe
fast immer im Audio (M4A/AAC, oft in hoher Stereo-Qualität), nicht in den
Bildern – deshalb wird beides angefasst.

Durchsucht rekursiv auch verschachtelte zips (repo.zip/page.zip/oonode.zip/
oocoursefolder.zip – OLAT legt Inhalte in allen davon ab). Jede gefundene
große Datei ist unabhängig von jeder anderen – deshalb läuft die eigentliche
Kompression über einen ProcessPoolExecutor parallel (siehe compress_course_zip,
Obergrenze TEST_COMPRESSION_MAX_WORKERS unten – alle Kerne gleichzeitig
würde den Rechner nebenbei spürbar lahmlegen), statt Datei für Datei
nacheinander. Bei einem Kurs mit vielen großen Dateien ist das trotzdem noch
ein langsamer, CPU-intensiver Vorgang (echtes Re-Encodieren/Rendern).

Aufruf: python compression.py input.zip output.zip [--video normal|ultra]
        [--pdf normal|ultra] [--pptx normal|ultra] [--threshold-mb 1.0]
"""

import argparse
import concurrent.futures
import io
import os
import shutil
import subprocess
import tempfile
import zipfile

import fitz
from PIL import Image

VIDEO_EXTS = ('.mp4', '.mov', '.webm', '.mkv', '.m4v')
HANDLED_EXTS = VIDEO_EXTS + ('.pdf', '.pptx')

PPTX_RASTER_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.gif')
PPTX_AUDIO_EXTS = ('.m4a', '.mp3', '.wav', '.wma')
_PPTX_AUDIO_FORMATS = {'.m4a': 'ipod', '.mp3': 'mp3', '.wav': 'wav', '.wma': 'ipod'}

# Zwei Stufen: 'normal' bleibt brauchbar (Videos noch ansehnlich, PDFs/PPTX
# noch lesbar), 'ultra' ist bewusst kompromisslos auf Dateigröße getrimmt –
# nur für den reinen Test-Import gedacht, nicht zum Ansehen der Inhalte.
TEST_COMPRESSION_LEVELS = {
    "normal": {
        "video_scale": 1280, "video_fps": None, "video_crf": 28, "video_audio_kbps": 96,
        "pdf_dpi": 150, "pdf_quality": 70,
        "pptx_img_dim": 1280, "pptx_img_quality": 70, "pptx_audio_kbps": 64,
    },
    "ultra": {
        "video_scale": 320, "video_fps": 10, "video_crf": 40, "video_audio_kbps": 24,
        "pdf_dpi": 72, "pdf_quality": 35,
        "pptx_img_dim": 800, "pptx_img_quality": 40, "pptx_audio_kbps": 32,
    },
}

# Obergrenze für den ProcessPoolExecutor – alle CPU-Kerne gleichzeitig
# auszulasten macht den Rechner sonst für alles andere spürbar träge.
TEST_COMPRESSION_MAX_WORKERS = 4


def ffmpeg_available() -> bool:
    return shutil.which('ffmpeg') is not None


def _run_ffmpeg_on_bytes(data: bytes, suffix: str, ffmpeg_args: list) -> bytes:
    """Schickt data durch ffmpeg und gibt die stdout-Bytes zurück.

    Die EINGABE braucht eine echte, zurückspulbare Datei statt pipe:0 – ein
    über eine Pipe gelesenes MP4/MOV/M4A schlägt fehl, sobald sein moov-Atom
    (Metadaten-Index) am Dateiende liegt (üblich bei Rohaufnahmen aus Zoom/
    OBS ohne Nachbearbeitung), weil ffmpeg dafür zurückspulen muss und Pipes
    das nicht können ("Could not find codec parameters", "partial file").
    Die AUSGABE darf weiter über pipe:1 laufen – frag_keyframe+empty_moov
    (siehe Aufrufer) macht ihr moov-Atom bewusst leer/vorne, genau um das
    zu vermeiden."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            ['ffmpeg', '-y', '-i', tmp_path] + ffmpeg_args, capture_output=True, check=True)
        return proc.stdout
    finally:
        os.remove(tmp_path)


def _compress_video(data: bytes, level: dict, suffix: str) -> bytes:
    scale_filter = f"scale='min({level['video_scale']},iw)':-2"
    if level['video_fps']:
        scale_filter += f",fps={level['video_fps']}"
    args = ['-vf', scale_filter, '-c:v', 'libx264', '-crf', str(level['video_crf']),
            '-preset', 'fast', '-c:a', 'aac', '-b:a', f"{level['video_audio_kbps']}k"]
    if level['video_fps']:
        args += ['-ac', '1']
    args += ['-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']
    return _run_ffmpeg_on_bytes(data, suffix, args)


def _compress_pdf(data: bytes, level: dict) -> bytes:
    src = fitz.open(stream=data, filetype='pdf')
    out = fitz.open()
    for page in src:
        pix = page.get_pixmap(dpi=level['pdf_dpi'])
        img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=level['pdf_quality'])
        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(page.rect, stream=buf.getvalue())
    result = out.tobytes(deflate=True, garbage=4)
    # Nur übernehmen, wenn's tatsächlich kleiner wird – manche PDFs (z.B.
    # mit echtem Vektortext statt Scan) werden durchs Rastern eher größer.
    return result if len(result) < len(data) else data


def _shrink_pptx_image(data: bytes, level: dict) -> bytes:
    img = Image.open(io.BytesIO(data))
    img.thumbnail((level['pptx_img_dim'], level['pptx_img_dim']))
    buf = io.BytesIO()
    if img.mode == 'RGBA':
        img.save(buf, format='PNG', optimize=True)
    else:
        img.convert('RGB').save(buf, format='JPEG', quality=level['pptx_img_quality'])
    new_data = buf.getvalue()
    return new_data if len(new_data) < len(data) else data


def _shrink_pptx_audio(data: bytes, ext: str, level: dict) -> bytes:
    fmt = _PPTX_AUDIO_FORMATS[ext]
    args = ['-ac', '1', '-b:a', f"{level['pptx_audio_kbps']}k", '-f', fmt]
    if fmt == 'ipod':
        args += ['-movflags', 'frag_keyframe+empty_moov']
    args += ['pipe:1']
    result = _run_ffmpeg_on_bytes(data, ext, args)
    return result if len(result) < len(data) else data


def _compress_pptx(data: bytes, level: dict, compress_audio: bool) -> bytes:
    """Lässt die PPTX-Struktur unangetastet, verkleinert nur Bilder (und bei
    verfügbarem ffmpeg auch Audio) unter ppt/media/ – bleibt danach eine ganz
    normale, öffenbare PPTX statt einer PDF."""
    src_zf = zipfile.ZipFile(io.BytesIO(data))
    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, 'w', zipfile.ZIP_DEFLATED) as out_zf:
        for info in src_zf.infolist():
            entry_data = src_zf.read(info.filename)
            lower = info.filename.lower()
            if lower.startswith('ppt/media/'):
                try:
                    if lower.endswith(PPTX_RASTER_EXTS):
                        entry_data = _shrink_pptx_image(entry_data, level)
                    elif compress_audio and lower.endswith(PPTX_AUDIO_EXTS):
                        ext = '.' + lower.rsplit('.', 1)[-1]
                        entry_data = _shrink_pptx_audio(entry_data, ext, level)
                except (subprocess.CalledProcessError, OSError):
                    pass  # einzelnes Medium bleibt im Original-Zustand
            out_zf.writestr(info, entry_data)
    result = out_buf.getvalue()
    return result if len(result) < len(data) else data


def _report_result(name: str, original: bytes, compressed: bytes) -> bool:
    """Meldet das Ergebnis einer Kompression auf stdout. Nur eine Zeile pro
    Datei, nicht pro Bild/Audiospur innerhalb einer PPTX – das wäre zu
    kleinteilig. Gibt zurück, ob tatsächlich gemeldet wurde (für die Zähler
    in compress_course_zip)."""
    if len(compressed) >= len(original):
        return False
    basename = name.rsplit('/', 1)[-1]
    pct = 100 * (1 - len(compressed) / len(original))
    print(f"[KOMPRIMIERT] {basename}: {len(original) / 1e6:.1f} MB -> "
          f"{len(compressed) / 1e6:.1f} MB (-{pct:.0f}%)")
    return True


def _category_for(name: str, options: dict) -> str | None:
    lower = name.lower()
    if options['video'] and lower.endswith(VIDEO_EXTS):
        return 'video'
    if options['pdf'] and lower.endswith('.pdf'):
        return 'pdf'
    if options['pptx'] and lower.endswith('.pptx'):
        return 'pptx'
    return None


def _collect_tasks(data: bytes, threshold: int, options: dict,
                   path_chain: tuple, tasks: list) -> None:
    """Durchsucht ein (verschachteltes) zip rekursiv und sammelt jede zu
    komprimierende Datei als (path_chain, name, data, category) in tasks –
    path_chain identifiziert die Fundstelle eindeutig (Kette der
    zip-Dateinamen bis dahin), damit _rebuild sie später wiederfindet.
    Komprimiert hier noch NICHTS – das passiert gesammelt und parallel in
    compress_course_zip."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return  # endet zufällig auf '.zip', ist aber gar keins

    for info in zf.infolist():
        lower = info.filename.lower()
        if lower.endswith('.zip'):
            _collect_tasks(zf.read(info.filename), threshold, options,
                          path_chain + (info.filename,), tasks)
        elif info.file_size > threshold:
            category = _category_for(info.filename, options)
            if category:
                tasks.append((path_chain + (info.filename,), info.filename,
                             zf.read(info.filename), category))


def _compress_task(task: tuple) -> tuple:
    """Läuft in einem Worker-Prozess (siehe compress_course_zip) – komprimiert
    genau eine Datei. Gibt (path_chain, name, komprimierte/Original-Bytes,
    Fehlertext-oder-None) zurück, druckt selbst nichts (Prints aus
    Worker-Prozessen kämen im Hauptprozess durcheinander an)."""
    path_chain, name, data, category, level, pptx_audio_ok = task
    try:
        if category == 'video':
            suffix = '.' + name.rsplit('.', 1)[-1]
            result = _compress_video(data, level, suffix)
        elif category == 'pdf':
            result = _compress_pdf(data, level)
        else:
            result = _compress_pptx(data, level, compress_audio=pptx_audio_ok)
        return path_chain, name, result, None
    except Exception as exc:
        return path_chain, name, data, str(exc)


def _rebuild(data: bytes, path_chain: tuple, results: dict) -> bytes:
    """Baut ein (verschachteltes) zip aus data neu auf: Dateien, deren
    path_chain in results steckt, werden durch ihr Kompressions-Ergebnis
    ersetzt, alles andere (inkl. zips ohne einen einzigen Treffer darin)
    unverändert durchgereicht."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return data

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, 'w', zipfile.ZIP_DEFLATED) as out_zf:
        for info in zf.infolist():
            lower = info.filename.lower()
            chain = path_chain + (info.filename,)
            if lower.endswith('.zip'):
                out_zf.writestr(info, _rebuild(zf.read(info.filename), chain, results))
            elif chain in results:
                out_zf.writestr(info, results[chain])
            else:
                out_zf.writestr(info, zf.read(info.filename))
    return out_buf.getvalue()


def compress_course_zip(src_path: str, dst_path: str, *, video_level: str | None,
                        pdf_level: str | None, pptx_level: str | None,
                        threshold_mb: float) -> None:
    """Schreibt eine test-komprimierte Kopie von src_path nach dst_path.

    Jede Kategorie hat ihre eigene Stufe (None = unangetastet lassen, sonst
    ein Schlüssel aus TEST_COMPRESSION_LEVELS) – wer nur PDFs braucht, lässt
    Videos/PPTX auf None. Die eingebetteten Audiospuren einer PPTX brauchen
    ffmpeg genau wie Video, hängen aber an der PPTX-Stufe, nicht an der
    Video-Stufe – beide sind unabhängig voneinander abschaltbar.

    Läuft zweistufig: erst _collect_tasks sammelt ALLE zu komprimierenden
    Dateien über die ganze (verschachtelte) zip-Struktur hinweg, dann
    komprimiert ein ProcessPoolExecutor sie parallel über alle CPU-Kerne –
    jede Datei ist unabhängig von jeder anderen, bei vielen großen Dateien
    ist das der Unterschied zwischen "dauert ewig" und einem Bruchteil
    davon. Erst danach baut _rebuild die zip-Struktur mit den Ergebnissen
    neu zusammen."""
    ffmpeg_ok = ffmpeg_available()
    if video_level and not ffmpeg_ok:
        print("[!] ffmpeg nicht gefunden (PATH) - Video-Kompression wird übersprungen.")
        video_level = None
    pptx_audio_ok = ffmpeg_ok
    if pptx_level and not ffmpeg_ok:
        print("[!] ffmpeg nicht gefunden (PATH) - PPTX-Audiospuren bleiben unangetastet, "
              "nur Bilder werden komprimiert.")

    threshold = int(threshold_mb * 1_000_000)
    options = {'video': video_level, 'pdf': pdf_level, 'pptx': pptx_level}
    levels = {'video': video_level and TEST_COMPRESSION_LEVELS[video_level],
             'pdf': pdf_level and TEST_COMPRESSION_LEVELS[pdf_level],
             'pptx': pptx_level and TEST_COMPRESSION_LEVELS[pptx_level]}

    tasks = []
    with zipfile.ZipFile(src_path) as src_zf:
        for info in src_zf.infolist():
            lower = info.filename.lower()
            if lower.endswith('.zip'):
                _collect_tasks(src_zf.read(info.filename), threshold, options,
                              (info.filename,), tasks)
            elif info.file_size > threshold:
                category = _category_for(info.filename, options)
                if category:
                    tasks.append(((info.filename,), info.filename,
                                 src_zf.read(info.filename), category))

    results = {}
    replaced_count = 0
    saved_total = 0
    if tasks:
        print(f"[*] {len(tasks)} große Datei(en) werden parallel komprimiert...")
        originals = {path_chain: data for path_chain, _, data, _ in tasks}
        pool_tasks = [(path_chain, name, data, category, levels[category], pptx_audio_ok)
                     for path_chain, name, data, category in tasks]
        # as_completed statt pool.map, damit jede Zeile erscheint, sobald IHRE
        # Datei fertig ist, statt erst alle auf einmal nach Ende des
        # langsamsten Tasks – fühlt sich bei vielen Dateien lebendiger an.
        with concurrent.futures.ProcessPoolExecutor(max_workers=TEST_COMPRESSION_MAX_WORKERS) as pool:
            futures = [pool.submit(_compress_task, t) for t in pool_tasks]
            for future in concurrent.futures.as_completed(futures):
                path_chain, name, result, error = future.result()
                if error:
                    print(f"[!] '{name}' konnte nicht komprimiert werden ({error}), bleibt Original.")
                elif _report_result(name, originals[path_chain], result):
                    replaced_count += 1
                    saved_total += len(originals[path_chain]) - len(result)
                results[path_chain] = result

    with zipfile.ZipFile(src_path) as src_zf:
        with zipfile.ZipFile(dst_path, 'w', zipfile.ZIP_DEFLATED) as dst_zf:
            for info in src_zf.infolist():
                lower = info.filename.lower()
                chain = (info.filename,)
                if lower.endswith('.zip'):
                    dst_zf.writestr(info, _rebuild(src_zf.read(info.filename), chain, results))
                elif chain in results:
                    dst_zf.writestr(info, results[chain])
                else:
                    dst_zf.writestr(info, src_zf.read(info.filename))

    print(f"\n[*] {replaced_count} Datei(en) komprimiert, ca. {saved_total / 1e6:.1f} MB gespart.")


if __name__ == "__main__":
    # freeze_support() ist hier nicht nötig – dieses Skript läuft nur als
    # normales Python-Skript, nicht als PyInstaller-.exe mit ProcessPoolExecutor
    # (siehe Docstring oben, wieso das bei der Haupt-.exe nötig war).
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_zip")
    parser.add_argument("output_zip")
    parser.add_argument("--video", choices=["normal", "ultra"], default=None)
    parser.add_argument("--pdf", choices=["normal", "ultra"], default=None)
    parser.add_argument("--pptx", choices=["normal", "ultra"], default=None)
    parser.add_argument("--threshold-mb", type=float, default=1.0)
    args = parser.parse_args()

    compress_course_zip(
        args.input_zip, args.output_zip,
        video_level=args.video, pdf_level=args.pdf, pptx_level=args.pptx,
        threshold_mb=args.threshold_mb,
    )
