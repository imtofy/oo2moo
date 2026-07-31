"""Bereinigt rohes OLAT-HTML, damit es unverändert in Moodle funktioniert.

OLAT-HTML enthält Dinge, die Moodle so nicht versteht: relative Bild-/
Dateipfade statt @@PLUGINFILE@@-Referenzen, tote interne OLAT-Links, leere
Absätze und HTML5-Tags, die Moodles Editor nicht rendert. sanitize_for_moodle()
ist der einzige öffentliche Einstiegspunkt dieses Moduls.
"""

import urllib.parse
import re
from bs4 import BeautifulSoup

# Server-interne OLAT-/Shibboleth-Pfade, die nach der Migration ins Leere
# zeigen würden (Login-/SSO-Endpunkte auf dem alten Server, keine
# Kursdateien) - werden wie /auth/-Links behandelt: entfernt statt als
# Datei-Asset gesucht.
_OLAT_INTERNAL_PATH_PREFIXES = ('/auth/', '/Shibboleth.sso/', '/login/')

# Erkennt einen href-Wert, der eine blanke E-Mail-Adresse OHNE 'mailto:'-
# Präfix ist (OLAT-Exportfehler/Tippfehler) - kein Dateipfad, sondern ein
# kaputter Link, der sich reparieren lässt statt als Asset gesucht zu werden.
_BARE_EMAIL_PATTERN = re.compile(r'^[^\s@/]+@[^\s@/]+\.[^\s@/]+$')

# OLAT kodiert kursinterne Verweise als javascript:parent.gotonode(<ident>)
# (der <ident> ist die Knoten-ID aus editortreemodel.xml). Daraus lässt
# sich per link_map die Ziel-Aktivität finden.
_GOTONODE_PATTERN = re.compile(r'gotonode\((\d+)\)')

# OLATs eigenes URL-Schema für Baustein-Ansichtsseiten (/RepositoryEntry/
# <Kurs-ID>/CourseNode/<Knoten-ID>) - institutionsunabhängig, jede OLAT-
# Instanz nutzt dasselbe Pfadmuster. Ein per <iframe> direkt im HTML
# eingebetteter Inhalt (typischerweise H5P), dessen src auf dieses Muster
# passt, verweist auf die alte OLAT-Quelle zurück und würde nach der
# Migration ins Leere zeigen.
_OLAT_SELF_REFERENCE_PATTERN = re.compile(r'/RepositoryEntry/\d+/CourseNode/\d+')

_LOST_EMBED_STYLE = 'color: #00a3a3; font-weight: bold; font-style: italic;'

# Moodle-Modultypen mit eigener Ansichtsseite und ihr Backup-Link-Token.
# Moodle-Konvention: <MODULNAME_GROSS>VIEWBYID → /mod/<name>/view.php?id=<cmid>,
# beim Restore auf die neue course_module-ID umgeschrieben. 'label' fehlt
# bewusst (Strukturknoten werden zu Labels, die keine Zielseite haben →
# nicht verlinkbar).
MODULE_VIEW_TOKENS = {
    'page': 'PAGEVIEWBYID',
    'folder': 'FOLDERVIEWBYID',
    'resource': 'RESOURCEVIEWBYID',
    'url': 'URLVIEWBYID',
    'forum': 'FORUMVIEWBYID',
    'quiz': 'QUIZVIEWBYID',
    'assign': 'ASSIGNVIEWBYID',
    'feedback': 'FEEDBACKVIEWBYID',
    'choice': 'CHOICEVIEWBYID',
    'wiki': 'WIKIVIEWBYID',
    'book': 'BOOKVIEWBYID',
}

# Nicht-aussagekräftige Linktexte (barrierefrei problematisch, da sie ohne
# umgebenden Satz keinen Sinn ergeben). Solche Links werden rot+fett
# hervorgehoben, damit der Kursautor sie nachbessern kann. Vergleich in
# Kleinschreibung, ohne umschliessende Anführungszeichen/Satzzeichen.
_VAGUE_LINK_TEXTS = {
    'hier', 'klick hier', 'klicke hier', 'hier klicken', 'klicken sie hier',
    'klicken', 'mehr', 'mehr dazu', 'weiterlesen', 'weiter', 'link',
    'here', 'click here', 'more', 'read more', 'this link', 'siehe hier', 'dazu',
}

# Vager Text, der noch einen FUNKTIONIERENDEN Link hat: rot+fett - Hinweis
# an den Autor, den Linktext barrierefrei nachzubessern (Link geht aber).
_VAGUE_LINK_STYLE = 'color: #cc0000; font-weight: bold;'

# Vager Text, dessen Link VERLOREN ging (Ziel nicht auflösbar): cyan+fett+
# kursiv - deutlich abgesetzt, damit sichtbar bleibt, dass hier ein
# Verweis war, der in Moodle manuell neu gesetzt werden muss.
_LOST_LINK_STYLE = 'color: #00a3a3; font-weight: bold; font-style: italic;'


def _is_vague_link_text(text: str) -> bool:
    """Prüft, ob ein Linktext nicht aussagekräftig ist (z.B. 'hier', 'mehr')."""
    normalized = text.strip().strip('"“”«»').strip().rstrip('.!:').lower()
    return normalized in _VAGUE_LINK_TEXTS


def _apply_style(tag, style_value):
    """Ergänzt einen CSS-Style eines Tags, ohne einen vorhandenen zu überschreiben."""
    existing = tag.attrs.get('style', '').rstrip().rstrip(';')
    tag.attrs['style'] = f"{existing}; {style_value}" if existing else style_value


def _resolve_gotonode(tag, link_map):
    """Löst einen gotonode(<ident>)-Verweis über link_map zu (cmid, m_type) auf
    und setzt href auf den Moodle-Platzhalter $@<TOKEN>*<cmid>@$ (True), falls
    der Zieltyp view-fähig ist (MODULE_VIEW_TOKENS). Sonst False - der
    Aufrufer entfernt dann den toten Anker."""
    if not link_map:
        return False
    haystack = ' '.join(str(tag.attrs.get(a, '')) for a in ('href', 'onclick'))
    match = _GOTONODE_PATTERN.search(haystack)
    if not match:
        return False
    target = link_map.get(match.group(1))
    if not target:
        return False
    cmid, m_type = target
    token = MODULE_VIEW_TOKENS.get(m_type)
    if not token:
        return False
    tag.attrs['href'] = f"$@{token}*{cmid}@$"
    for attr in ('onclick', 'target', 'class'):
        tag.attrs.pop(attr, None)
    return True


def _image_gap_sides(tag) -> tuple:
    """Bestimmt, auf welchen horizontalen Seiten ein Bild Abstand zum Text braucht.

    Bei OLATs Bild-neben-Text-Layout sitzt das Bild in einer eigenen
    Tabellenspalte, der Text in der Nachbarspalte - Abstand ist dann nur
    zur Textseite hin sinnvoll, sonst würde er das Bild nur unnötig
    verkleinern. Erste Spalte → Text rechts, letzte Spalte → Text links,
    mittlere Spalte → beide Seiten. Ohne Mehrspalten-Kontext ebenfalls beide.
    """
    cell = tag.find_parent(['td', 'th'])
    if cell is not None:
        row = cell.find_parent('tr')
        if row is not None:
            cells = row.find_all(['td', 'th'], recursive=False)
            if len(cells) > 1:
                idx = next((i for i, c in enumerate(cells) if c is cell), 0)
                if idx == 0:
                    return ('right',)
                if idx == len(cells) - 1:
                    return ('left',)
                return 'left', 'right'
    return 'left', 'right'


def sanitize_for_moodle(raw_html: str, link_map: dict | None = None) -> tuple[str, list, list]:
    """Bereinigt ein OLAT-HTML-Fragment für die Verwendung in Moodle.

    link_map (ident → (cmid, Modultyp), None = keine Auflösung) löst
    kursinterne gotonode-Verweise zu echten Moodle-Links auf. Im Einzelnen:
      - entfernt <script>/<meta>/<head>/<title> und leere <p>-Absätze (außer
        mit Medien-/Tabellen-Element).
      - schreibt src bei <img>/<video>/<audio>/<source>/<embed> sowie poster
        bei <video> auf @@PLUGINFILE@@/<dateiname> um; der Original-Pfad
        wird als "extracted_asset" vorgemerkt, damit die Datei aus dem VFS
        nachgeladen werden kann.
      - gibt Bildern ohne eigene Breiten-/Höhenangabe automatisch
        `max-width:100%; height:auto` - OLAT hält solche Bilder oft nur über
        die umgebende Tabellenzelle klein, ohne das würde z.B. ein 1200px-Foto
        die Moodle-Seite sprengen.
      - entfernt tote OLAT-interne Verweise (leere <a>-Anker,
        javascript:parent.gotonode(...), root-relative Pfade '/auth/',
        '/Shibboleth.sso/', '/login/' - eine ABSOLUTE URL mit '/login/' im
        Pfad bleibt bewusst unangetastet, sonst würden legitime externe
        Links fälschlich entfernt). Der Anker fliegt raus (Text bleibt),
        damit Moodle gleichnamige Aktivitäten automatisch verlinkt; der
        Verweis wird fürs Systemprotokoll vorgemerkt. Relative Links auf
        mitkopierte Dateien werden dagegen NICHT entfernt, sondern auf
        @@PLUGINFILE@@ umgeschrieben.
      - repariert blanke E-Mail-Adressen ohne 'mailto:'-Präfix (OLAT-
        Exportfehler) zu echten mailto:-Links, statt sie als Datei-Asset
        zu behandeln.
      - ersetzt <iframe>-Einbettungen, deren src auf OLATs eigenes
        RepositoryEntry/CourseNode-Ansichtsschema verweist (typischerweise
        H5P), durch eine sichtbare Warnung - die Quelle existiert nach der
        Migration nicht mehr erreichbar, der Verweis wird fürs
        Systemprotokoll vorgemerkt.
      - benennt <section>/<article>/<aside> zu <div> um (Moodles Editor
        kennt diese HTML5-Tags nicht) und fasst 3+ <br>-Tags zu zweien zusammen.

    Gibt (bereinigtes HTML, nachzuladende Asset-Pfade, entfernte Links als
    [{'text', 'href'}, ...]) zurück.
    """
    if not raw_html:
        return "", [], []

    soup = BeautifulSoup(raw_html, 'html.parser')
    extracted_assets = []
    removed_links = []

    for tag in soup(["script", "meta", "head", "title"]):
        tag.decompose()

    for img in soup.find_all('img', class_=re.compile(r'^o_emoticons_')):
        # OLATs Editor fügt Emoticons als <img src=".../transparent.gif"
        # class="o_emoticons_xyz"> ein - das eigentliche Smiley-Bild kommt
        # NUR aus OLATs eigenem CSS-Sprite (background-image über die
        # Klasse), transparent.gif ist bloß ein 1x1-Platzhalter. Weder die
        # Klasse noch das echte Sprite existieren in Moodle - das Bild bliebe
        # so oder so unsichtbar, würde aber einen nie auflösbaren
        # @@PLUGINFILE@@-Verweis auf eine Datei hinterlassen, die es im
        # Kurs-Export gar nicht gibt (transparent.gif ist ein OLAT-
        # Systemasset, kein Kursinhalt). Deshalb komplett entfernen statt
        # als Asset-Pfad zu behandeln.
        img.decompose()

    for p in soup.find_all('p'):
        text_content = p.get_text(strip=True).replace('\xa0', '')
        if not text_content and not p.find(['img', 'iframe', 'video', 'audio', 'figure', 'table']):
            p.decompose()

    def _rewrite_asset_attr(el, attr_name):
        """Schreibt ein Datei-Attribut (src/poster) auf @@PLUGINFILE@@ um und
        merkt den Original-Pfad in extracted_assets zum Nachladen vor."""
        value = el.attrs[attr_name]
        if value.startswith(('http', 'data:', '@@PLUGINFILE@@') + _OLAT_INTERNAL_PATH_PREFIXES):
            return
        asset_url = urllib.parse.urlparse(value)
        asset_path = urllib.parse.unquote(asset_url.path)
        asset_filename = asset_path.split('/')[-1]
        if not asset_filename:
            return
        extracted_assets.append(asset_path)
        el.attrs[attr_name] = f"@@PLUGINFILE@@/{urllib.parse.quote(asset_filename)}"

    for tag in soup.find_all(True):
        if tag.name in ('img', 'video', 'audio', 'source', 'embed') and 'src' in tag.attrs:
            _rewrite_asset_attr(tag, 'src')

        if tag.name == 'img':
            style = tag.attrs.get('style', '')
            # Nur eine eigene STYLE-Größe gilt als "bewusst gesetzt" - reine
            # width/height-HTML-ATTRIBUTE (OLAT exportiert sie sehr häufig,
            # z.B. width="264" height="176") legen nur Platz/Seitenverhältnis
            # fest, werden aber von CSS max-width für die tatsächliche
            # Renderbreite überschrieben - solche Bilder werden wie größenlose
            # behandelt (Sicherheitsbremse + Abstand).
            has_style_size = bool(re.search(r'(?:max-)?(?:width|height)\s*:', style))
            has_max_width = bool(re.search(r'max-width\s*:', style))
            has_own_margin = 'margin' in style

            # Horizontalen Abstand NUR zur Textseite hin geben (siehe
            # _image_gap_sides) - so bleibt das Bild so groß wie möglich und
            # bekommt den Rand genau dort, wo der Nachbartext steht. Da margin
            # im CSS-Boxmodell AUSSERHALB der Box liegt, muss die per max-width
            # erlaubte Breite um exakt diesen horizontalen Margin reduziert
            # werden, sonst läuft das Bild über seine Spalte in den Text.
            h_margin = 15
            sides = _image_gap_sides(tag)
            margin_left = h_margin if 'left' in sides else 0
            margin_right = h_margin if 'right' in sides else 0

            if not has_style_size and not has_own_margin:
                subtract = margin_left + margin_right
                base_style = style.rstrip().rstrip(';')
                extra = f'max-width: calc(100% - {subtract}px); height: auto;'
                style = f"{base_style}; {extra}" if base_style else extra
                tag.attrs['style'] = style
            elif not has_style_size:
                # Autor hat schon margin gesetzt - Größe nur begrenzen.
                base_style = style.rstrip().rstrip(';')
                extra = 'max-width: 100%; height: auto;'
                style = f"{base_style}; {extra}" if base_style else extra
                tag.attrs['style'] = style
            elif not has_max_width:
                # Autor hat eine feste width/height gesetzt, aber kein eigenes
                # max-width - als Sicherheitsnetz gegen Seitenüberlauf trotzdem
                # eins ergänzen (überschreibt die feste Breite nicht, begrenzt
                # sie nur nach oben).
                base_style = style.rstrip().rstrip(';')
                extra = 'max-width: 100%;'
                style = f"{base_style}; {extra}" if base_style else extra
                tag.attrs['style'] = style

            # Abstand ergänzen, falls der Autor noch keinen margin gesetzt hat.
            if not has_own_margin:
                base_style = style.rstrip().rstrip(';')
                if has_style_size:
                    # Bewusste CSS-Größe - nur vertikalen Abstand ergänzen,
                    # horizontaler würde die gesetzte Breite überlaufen.
                    extra = 'margin: 10px 0;'
                else:
                    extra = f'margin: 10px {margin_right}px 10px {margin_left}px;'
                tag.attrs['style'] = f"{base_style}; {extra}" if base_style else extra

        if tag.name == 'video' and 'poster' in tag.attrs:
            _rewrite_asset_attr(tag, 'poster')

        if tag.name == 'iframe' and 'src' in tag.attrs:
            src = tag.attrs['src']
            parsed_src = urllib.parse.urlparse(src)
            if parsed_src.netloc and _OLAT_SELF_REFERENCE_PATTERN.search(parsed_src.path):
                # Direkt im HTML eingebetteter Inhalt (typischerweise H5P) mit
                # einer OLAT-eigenen Ansichtsseite als src - die Quelle existiert
                # nach der Migration nicht mehr erreichbar, es gibt keine
                # automatische Auflösung dafür. Durch eine sichtbare Warnung
                # ersetzen statt einen stillen toten iframe zu hinterlassen.
                removed_links.append({'text': 'Eingebetteter Inhalt (iframe)', 'href': src})
                warning = soup.new_tag('p')
                warning.string = ('⚠ Eingebetteter Inhalt konnte nicht automatisch übernommen werden '
                                  '(verweist auf die alte OLAT-Quelle) - muss in Moodle manuell neu '
                                  'eingebunden werden.')
                _apply_style(warning, _LOST_EMBED_STYLE)
                tag.replace_with(warning)
                continue

        if tag.name == 'a':
            href = tag.attrs.get('href', '')
            has_known_scheme = href.startswith(
                ('http', 'mailto:', 'tel:', '#', 'data:', '@@PLUGINFILE@@'))
            link_text = tag.get_text(strip=True)
            vague = _is_vague_link_text(link_text)

            # Server-internen OLAT-Link nur erkennen, wenn er root-relativ ist
            # (kein Host) UND sein Pfad mit einem der Prefixe BEGINNT. Ein
            # bloßer Substring-Treffer in einer absoluten URL (z.B.
            # https://fremde-uni.de/login/hilfe) würde sonst legitime externe
            # Links fälschlich als tote OLAT-Links entfernen.
            parsed_href = urllib.parse.urlparse(href)
            is_server_internal = (
                not parsed_href.netloc
                and parsed_href.path.startswith(_OLAT_INTERNAL_PATH_PREFIXES))
            gotonode_attrs = ' '.join(str(tag.attrs.get(a, '')) for a in ('href', 'onclick'))
            is_course_internal = (
                not href
                or href.startswith('javascript:')
                or _GOTONODE_PATTERN.search(gotonode_attrs))

            if is_server_internal:
                # Tote OLAT-Server-Links (/auth/, /Shibboleth.sso/, /login/):
                # Anker entfernen, Text bleibt, Verweis ins Systemprotokoll.
                if link_text:
                    removed_links.append({'text': link_text, 'href': href})
                tag.unwrap()
            elif is_course_internal:
                # Kursinterner Verweis (javascript:parent.gotonode(...) oder
                # leerer <a>). Zuerst versuchen, ihn über die link_map zu
                # einem echten Moodle-Link aufzulösen.
                if _resolve_gotonode(tag, link_map):
                    # Link funktioniert wieder. Vager Text → rot+fett.
                    if vague:
                        _apply_style(tag, _VAGUE_LINK_STYLE)
                else:
                    # Nicht auflösbar (leerer <a> ohne Ziel-ID, übersprungenes
                    # Ziel, oder Ziel ist ein Label ohne Ansichtsseite).
                    if link_text:
                        removed_links.append({'text': link_text,
                                              'href': href or 'OLAT-interner Verweis'})
                    if vague:
                        # Vager Text, dessen Link verloren ging → cyan+fett+
                        # kursiv, damit der verlorene Verweis auffällt und in
                        # Moodle manuell neu gesetzt werden kann.
                        tag.name = 'strong'
                        for attr in ('href', 'onclick', 'target', 'class'):
                            tag.attrs.pop(attr, None)
                        _apply_style(tag, _LOST_LINK_STYLE)
                    else:
                        # Aussagekräftiger Text → nur Anker weg, Moodle
                        # verlinkt gleichnamige Aktivitäten automatisch.
                        tag.unwrap()
            elif not has_known_scheme and _BARE_EMAIL_PATTERN.match(href):
                tag.attrs['href'] = f'mailto:{href}'
            elif not has_known_scheme:
                parsed_url = urllib.parse.urlparse(href)
                clean_path = urllib.parse.unquote(parsed_url.path)
                filename = clean_path.split('/')[-1]

                if filename:
                    extracted_assets.append(clean_path)
                    safe_src_name = urllib.parse.quote(filename)
                    tag.attrs['href'] = f"@@PLUGINFILE@@/{safe_src_name}"
                if vague:
                    _apply_style(tag, _VAGUE_LINK_STYLE)
            elif vague:
                # Externer/bekannter Link mit nicht aussagekräftigem Text.
                _apply_style(tag, _VAGUE_LINK_STYLE)

        if tag.name in ['section', 'article', 'aside']:
            tag.name = 'div'

    # OLAT exportiert Tabellen oft mit fester Pixel-Breite (z.B.
    # style="width: 844px") statt relativ - in einer schmaleren Moodle-
    # Spalte reißt das sonst die ganze Seite horizontal auf. max-width:100%
    # deckelt die Tabelle auf ihren Container (CSS: max-width gewinnt immer
    # gegen ein kleineres width) - der Browser staucht die Spalten dafür
    # proportional (Text bricht ggf. mehr um), aber es muss gar nicht mehr
    # gescrollt werden. Die scrollbare Hülle bleibt zusätzlich als
    # Sicherheitsnetz für Fälle, wo selbst gestauchte Spalten (z.B. wegen
    # eines einzelnen langen unumbrechbaren Worts) noch überlaufen.
    for table in soup.find_all('table'):
        existing_style = table.attrs.get('style', '').rstrip().rstrip(';')
        table.attrs['style'] = f"{existing_style}; max-width: 100%;" if existing_style else "max-width: 100%;"
        wrapper = soup.new_tag('div', style='overflow-x:auto;')
        table.wrap(wrapper)

    body = soup.find('body')
    if body:
        clean_html = "".join([str(child) for child in body.children])
    else:
        clean_html = str(soup)

    clean_html = re.sub(r'(<br\s*/?>\s*){3,}', '<br/><br/>', clean_html)

    return clean_html.strip(), extracted_assets, removed_links
