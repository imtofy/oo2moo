"""Ersetzt große Videos/PDFs/PPTX durch vorbereitete, lizenzfreie
Platzhalter-Dateien (assets/placeholder.mp4/.pdf/.pptx) – der einzige
Test-Modus im Hauptprogramm. Echte (aber langsame, CPU-intensive) Kompression
gibt es noch als eigenständiges Zusatzskript unter
compression_standalone/compression.py (Repo-Wurzel) – dort bewusst NICHT
mehr Teil der Haupt-.exe, weil PyMuPDF+Pillow allein die .exe um ~80MB
aufblähten, für ein selten gebrauchtes Feature.

Die drei Vorlagen werden nie zur Laufzeit neu erzeugt (reiner Lorem-Ipsum-
Text, keine Kennzeichnung/Lizenz nötig) – nur PDF/PPTX werden auf die
Seiten-/Folienzahl des jeweiligen Originals heruntergeschnitten (siehe
config.PLACEHOLDER_MAX_PAGES), damit ein Kurs mit z.B. 2-seitigen PDFs nicht
plötzlich 5-seitige Platzhalter bekommt. Mehr als die vorbereiteten 5 Seiten
geht nicht, dann bleibt's bei dieser Obergrenze. Video braucht das nicht –
da gibt es keine "Seitenzahl" zum Anpassen.

Reines Byte-Ersetzen ohne Re-Encode/Rendering – anders als bei der echten
Kompression lohnt sich Parallelisierung hier nicht, das Kopieren selbst ist
schon schnell genug."""

import io
import zipfile

from pypdf import PdfReader, PdfWriter

from config import (PLACEHOLDER_VIDEO_PATH, PLACEHOLDER_PDF_PATH, PLACEHOLDER_PPTX_PATH,
                    PLACEHOLDER_MAX_PAGES)

VIDEO_EXTS = ('.mp4', '.mov', '.webm', '.mkv', '.m4v')
HANDLED_EXTS = VIDEO_EXTS + ('.pdf', '.pptx')

# Erst beim ersten Gebrauch laden, nicht beim Import: der Test-Modus ist
# abschaltbar, eine fehlende Vorlage darf deshalb nicht den Programmstart
# verhindern (app/gui.py importiert dieses Modul auf Modulebene).
_TEMPLATE_CACHE = {}


def _template(path: str) -> bytes:
    """Liest eine Platzhalter-Vorlage einmalig ein und merkt sie sich."""
    if path not in _TEMPLATE_CACHE:
        with open(path, 'rb') as handle:
            _TEMPLATE_CACHE[path] = handle.read()
    return _TEMPLATE_CACHE[path]


def _pdf_page_count(data: bytes) -> int:
    try:
        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return PLACEHOLDER_MAX_PAGES


def _pptx_slide_count(data: bytes) -> int:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return sum(1 for n in zf.namelist()
                      if n.startswith('ppt/slides/slide') and n.endswith('.xml')
                      and '/_rels/' not in n)
    except Exception:
        return PLACEHOLDER_MAX_PAGES


def make_video_placeholder() -> bytes:
    """Die Video-Vorlage unverändert – anders als PDF/PPTX gibt es beim
    Video keine Seitenzahl, die zum Original passen müsste."""
    return _template(PLACEHOLDER_VIDEO_PATH)


def make_pdf_placeholder(original_data: bytes) -> bytes:
    """Schneidet die PDF-Vorlage auf min(Originalseitenzahl, 5) Seiten runter –
    baut die Ziel-Seiten 0..target-1 aus der Vorlage in ein neues PDF, statt
    die Vorlage selbst zu verändern."""
    target = min(_pdf_page_count(original_data), PLACEHOLDER_MAX_PAGES)
    if target >= PLACEHOLDER_MAX_PAGES:
        return _template(PLACEHOLDER_PDF_PATH)
    reader = PdfReader(io.BytesIO(_template(PLACEHOLDER_PDF_PATH)))
    writer = PdfWriter()
    for i in range(max(target, 1)):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _trim_pptx(n: int) -> bytes:
    """Entfernt die Folien n+1..PLACEHOLDER_MAX_PAGES aus der PPTX-Vorlage –
    string-basiert statt vollem XML-Parsing, weil das Template komplett
    selbst gebaut wurde (siehe assets/placeholder.pptx-Entstehung) und sein
    exaktes Format deshalb bekannt ist: durchgehend nummerierte slideN.xml/
    rId(N+1), keine Sonderfälle."""
    with zipfile.ZipFile(io.BytesIO(_template(PLACEHOLDER_PPTX_PATH))) as src:
        content_types = src.read('[Content_Types].xml').decode('utf-8')
        presentation = src.read('ppt/presentation.xml').decode('utf-8')
        pres_rels = src.read('ppt/_rels/presentation.xml.rels').decode('utf-8')

        for i in range(n + 1, PLACEHOLDER_MAX_PAGES + 1):
            content_types = content_types.replace(
                f'<Override PartName="/ppt/slides/slide{i}.xml" '
                f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>\n', '')
            presentation = presentation.replace(
                f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>\n', '')
            pres_rels = pres_rels.replace(
                f'<Relationship Id="rId{i + 1}" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
                f'Target="slides/slide{i}.xml"/>\n', '')

        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, 'w', zipfile.ZIP_DEFLATED) as out:
            for info in src.infolist():
                name = info.filename
                if name.startswith('ppt/slides/'):
                    digits = ''.join(char for char in name if char.isdigit())
                    if digits and int(digits) > n:
                        continue  # diese Folie fällt weg
                    out.writestr(info, src.read(name))
                elif name == '[Content_Types].xml':
                    out.writestr(info, content_types)
                elif name == 'ppt/presentation.xml':
                    out.writestr(info, presentation)
                elif name == 'ppt/_rels/presentation.xml.rels':
                    out.writestr(info, pres_rels)
                else:
                    out.writestr(info, src.read(name))
    return out_buf.getvalue()


def make_pptx_placeholder(original_data: bytes) -> bytes:
    """Schneidet die PPTX-Vorlage auf min(Originalfolienzahl, 5) Folien
    runter – siehe _trim_pptx."""
    target = min(_pptx_slide_count(original_data), PLACEHOLDER_MAX_PAGES)
    if target >= PLACEHOLDER_MAX_PAGES:
        return _template(PLACEHOLDER_PPTX_PATH)
    return _trim_pptx(max(target, 1))


def _replace_entry(name: str, data: bytes, options: dict) -> bytes:
    lower = name.lower()
    if options['video'] and lower.endswith(VIDEO_EXTS):
        return make_video_placeholder()
    if options['pdf'] and lower.endswith('.pdf'):
        return make_pdf_placeholder(data)
    if options['pptx'] and lower.endswith('.pptx'):
        return make_pptx_placeholder(data)
    return data


def _process_nested_zip(data: bytes, threshold: int, options: dict) -> tuple:
    """Gibt (neue Bytes, Anzahl ersetzt, eingesparte Bytes) zurück – die
    Zähler werden bis nach replace_course_zip durchgereicht, für die
    Abschluss-Zeile dort (siehe _report_result für die Einzelzeilen)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return data, 0, 0  # endet zufällig auf '.zip', ist aber gar keins

    replaced_count = 0
    saved_total = 0
    out_buf = io.BytesIO()
    # Beide Archive per with, sonst sammeln sich bei verschachtelten Zips
    # (diese Funktion ruft sich selbst auf) offene ZipFile-Objekte an.
    with archive as src_zf, zipfile.ZipFile(out_buf, 'w', zipfile.ZIP_DEFLATED) as out_zf:
        for info in src_zf.infolist():
            if info.filename.lower().endswith('.zip'):
                nested_data, nested_count, nested_saved = _process_nested_zip(
                    src_zf.read(info.filename), threshold, options)
                out_zf.writestr(info, nested_data)
                replaced_count += nested_count
                saved_total += nested_saved
            elif info.file_size > threshold and info.filename.lower().endswith(HANDLED_EXTS):
                original = src_zf.read(info.filename)
                new_data = _replace_entry(info.filename, original, options)
                out_zf.writestr(info, new_data)
                if _report_result(info.filename, original, new_data):
                    replaced_count += 1
                    saved_total += len(original) - len(new_data)
            else:
                out_zf.writestr(info, src_zf.read(info.filename))
    return out_buf.getvalue(), replaced_count, saved_total


def _report_result(name: str, original: bytes, replaced: bytes) -> bool:
    """Gleiche [KOMPRIMIERT]-Zeile/Streifen wie bei der echten Kompression
    (siehe compression._report_result) – für den Log ist's derselbe
    Vorgang: Datei X wurde kleiner. Gibt zurück, ob tatsächlich gemeldet
    wurde (für die Zähler in replace_course_zip)."""
    if len(replaced) >= len(original):
        return False
    basename = name.rsplit('/', 1)[-1]
    pct = 100 * (1 - len(replaced) / len(original))
    print(f"[KOMPRIMIERT] {basename}: {len(original) / 1e6:.1f} MB -> "
          f"{len(replaced) / 1e6:.2f} MB (-{pct:.0f}%)")
    return True


def replace_course_zip(src_path: str, dst_path: str, *, video: bool, pdf: bool, pptx: bool,
                       threshold_mb: float) -> None:
    """Schreibt eine Kopie von src_path nach dst_path, in der jede Video-/
    PDF-/PPTX-Datei oberhalb threshold_mb durch den passenden Platzhalter
    ersetzt ist. video/pdf/pptx schalten die jeweilige Kategorie einzeln zu."""
    threshold = int(threshold_mb * 1_000_000)
    options = {'video': video, 'pdf': pdf, 'pptx': pptx}
    replaced_count = 0
    saved_total = 0

    with zipfile.ZipFile(src_path) as src_zf:
        with zipfile.ZipFile(dst_path, 'w', zipfile.ZIP_DEFLATED) as dst_zf:
            for info in src_zf.infolist():
                name_lower = info.filename.lower()
                if name_lower.endswith('.zip'):
                    nested_data, nested_count, nested_saved = _process_nested_zip(
                        src_zf.read(info.filename), threshold, options)
                    dst_zf.writestr(info, nested_data)
                    replaced_count += nested_count
                    saved_total += nested_saved
                elif info.file_size > threshold and name_lower.endswith(HANDLED_EXTS):
                    original = src_zf.read(info.filename)
                    new_data = _replace_entry(info.filename, original, options)
                    dst_zf.writestr(info, new_data)
                    if _report_result(info.filename, original, new_data):
                        replaced_count += 1
                        saved_total += len(original) - len(new_data)
                else:
                    dst_zf.writestr(info, src_zf.read(info.filename))

    print(f"\n[*] {replaced_count} Datei(en) ersetzt, ca. {saved_total / 1e6:.1f} MB gespart.")
