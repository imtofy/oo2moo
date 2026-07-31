"""Tests für sanitize_for_moodle() - der zentrale HTML-Bereinigungsschritt,
den jeder Bausteininhalt vor der Übernahme nach Moodle durchläuft."""

from conversion.html_cleaner import sanitize_for_moodle


def test_empty_input_returns_empty_triple():
    html, assets, removed = sanitize_for_moodle("")
    assert (html, assets, removed) == ("", [], [])


def test_image_src_rewritten_to_pluginfile_and_asset_recorded():
    html, assets, _ = sanitize_for_moodle('<img src="/raw/foo/bild.png">')
    assert '@@PLUGINFILE@@/bild.png' in html
    assert '/raw/foo/bild.png' in assets


def test_absolute_and_pluginfile_image_src_left_untouched():
    html, assets, _ = sanitize_for_moodle('<img src="https://example.com/bild.png">')
    assert 'https://example.com/bild.png' in html
    assert assets == []


def test_olat_emoticon_is_removed_not_treated_as_asset():
    html, assets, _ = sanitize_for_moodle(
        '<p>Text <img class="o_emoticons_grin" src="/raw/images/transparent.gif"> Ende</p>')
    assert 'transparent.gif' not in html
    assert assets == []
    assert 'Text' in html and 'Ende' in html


def test_gotonode_link_resolves_via_link_map():
    link_map = {'123': (42, 'page')}
    html, _, removed = sanitize_for_moodle(
        '<a href="javascript:parent.gotonode(123)">Zur Seite</a>', link_map=link_map)
    assert '$@PAGEVIEWBYID*42@$' in html
    assert removed == []


def test_gotonode_link_without_map_entry_is_removed_and_logged():
    html, _, removed = sanitize_for_moodle(
        '<a href="javascript:parent.gotonode(999)">Zur Seite</a>', link_map={})
    assert 'gotonode' not in html
    assert 'Zur Seite' in html  # Text bleibt, nur der Anker fliegt raus
    assert len(removed) == 1
    assert removed[0]['text'] == 'Zur Seite'


def test_auth_path_link_removed_but_text_kept():
    html, _, removed = sanitize_for_moodle('<a href="/auth/login.php">Anmelden</a>')
    assert '<a' not in html
    assert 'Anmelden' in html
    assert removed == [{'text': 'Anmelden', 'href': '/auth/login.php'}]


def test_absolute_url_containing_login_substring_is_not_removed():
    # Nur root-relative /login/-Pfade gelten als toter OLAT-Server-Link -
    # eine echte externe URL mit '/login/' im Pfad darf nicht kaputtgehen.
    html, _, removed = sanitize_for_moodle(
        '<a href="https://fremde-uni.de/login/hilfe">Hilfe</a>')
    assert 'https://fremde-uni.de/login/hilfe' in html
    assert removed == []


def test_empty_paragraph_is_removed():
    html, _, _ = sanitize_for_moodle('<p>  </p><p>Echter Text</p>')
    assert html.count('<p>') == 1
    assert 'Echter Text' in html


def test_empty_paragraph_with_image_is_kept():
    html, _, _ = sanitize_for_moodle('<p><img src="/raw/bild.png"></p>')
    assert '<img' in html


def test_bare_email_link_repaired_to_mailto():
    html, _, _ = sanitize_for_moodle('<a href="max@example.com">Kontakt</a>')
    assert 'href="mailto:max@example.com"' in html


def test_vague_link_text_gets_highlighted_style():
    html, _, _ = sanitize_for_moodle('<a href="https://example.com">hier klicken</a>')
    assert 'color: #cc0000' in html


def test_iframe_referencing_olat_repository_entry_is_replaced_with_warning():
    html, _, removed = sanitize_for_moodle(
        '<iframe src="https://beispiel-olat.invalid/auth/RepositoryEntry/123/'
        'CourseNode/456?attr=1"></iframe>')
    assert '<iframe' not in html
    assert 'nicht automatisch übernommen werden' in html
    assert len(removed) == 1
    assert 'RepositoryEntry' in removed[0]['href']


def test_iframe_to_external_video_platform_stays_untouched():
    # YouTube/Vimeo/... - jede beliebige externe Videoseite lässt sich per
    # iframe einbetten, nur OLATs eigenes RepositoryEntry/CourseNode-Schema
    # darf als "verweist auf die alte Quelle" erkannt werden.
    src = 'https://beispiel-videoplattform.invalid/embed/12345'
    html, _, removed = sanitize_for_moodle(f'<iframe src="{src}"></iframe>')
    assert src in html
    assert removed == []


def test_own_generated_pdf_embed_iframe_stays_untouched():
    # @@PLUGINFILE@@-Verweise haben keinen Host (kein echtes href) - der
    # eigene PDF-Inline-iframe (node_processor._auto_embed) darf davon nicht
    # betroffen sein.
    html, _, removed = sanitize_for_moodle(
        '<iframe src="@@PLUGINFILE@@/Handout.pdf" style="width:100%;"></iframe>')
    assert '@@PLUGINFILE@@/Handout.pdf' in html
    assert removed == []


def test_html5_semantic_tags_renamed_to_div():
    html, _, _ = sanitize_for_moodle('<section>Inhalt</section>')
    assert '<section' not in html
    assert '<div' in html
    assert 'Inhalt' in html


def test_excessive_br_tags_collapsed_to_two():
    html, _, _ = sanitize_for_moodle('Text<br><br><br><br>Ende')
    assert html.count('<br') == 2


def test_wide_table_gets_scroll_wrapper_and_max_width():
    html, _, _ = sanitize_for_moodle('<table style="width: 900px;"><tr><td>x</td></tr></table>')
    assert 'overflow-x:auto' in html
    assert 'max-width: 100%' in html


def test_relative_file_link_rewritten_to_pluginfile_not_removed():
    html, assets, removed = sanitize_for_moodle('<a href="dokument.pdf">Dokument</a>')
    assert '@@PLUGINFILE@@/dokument.pdf' in html
    assert 'dokument.pdf' in assets
    assert removed == []
