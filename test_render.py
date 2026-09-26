import bench as B
import gen
import render
from sources.common import make_model
from xml.etree import ElementTree as ET


def test_table_has_accessible_headers_and_caption():
    html = render.table(["Model", "Score"], [["model-a", "1.0"]], caption="Scores", row_header=0)
    assert '<caption>Scores</caption>' in html
    assert '<th scope="col">Model</th>' in html
    assert '<th scope="row">model-a</th>' in html


def test_model_directory_has_search_and_use_case_metadata():
    model = make_model("vendor/longcat-model:free", name="Longcat Model", description="Long context model", source="openrouter")
    html = gen.render_ranking([model], "2026-01-01T00:00:00Z")
    assert 'data-model-filter' in html
    assert 'data-model-filter>\n  <div class="filter-bar"' in html
    assert 'data-model-row' in html
    assert 'data-model-search=' in html
    assert 'data-model-role="Long-context work"' in html
    assert 'Free models for Long-context work' in html


def test_model_directory_columns_match_model_row_cells():
    model = make_model("vendor/longcat-model:free", name="Longcat Model", description="Long context model", source="openrouter")
    html = gen.render_ranking([model], "2026-01-01T00:00:00Z")
    table_start = html.index('<div class="table-wrap model-table">')
    table_end = html.index('</table>', table_start)
    table_html = html[table_start:table_end]
    assert table_html.count('<th scope="col">') == 8
    assert table_html.count('<td') + table_html.count('<th scope="row"') == 8


def test_router_changes_page_is_not_exposed():
    html = render.page("Home", "index.html", "<p>Home</p>", "2026-01-01T00:00:00Z")
    assert "comparisons-router-changelog.html" not in html
    assert "Router changes" not in html


def test_benchmark_render_has_summary_and_paid_reference(monkeypatch):
    model = {"id": "vendor/longcat-model", "display_id": "vendor/longcat-model:free", "name": "Longcat Model", "modalities": "text"}
    aa = [{"name": "Longcat Model", "artificial_analysis_intelligence_index": 20,
           "artificial_analysis_coding_index": 15, "gpqa": 0.7,
           "terminalbench_hard": 0.4,
           "pricing": {"price_1m_blended_3_to_1": 0}}]
    monkeypatch.setattr(B, "fetch_aa", lambda: (aa, ""))
    html = B.render([model], "2026-01-01T00:00:00Z")
    assert 'summary-card' in html
    assert 'Overall intelligence' in html
    assert 'free models and paid reference' in html
    assert 'vendor/longcat-model:free' in html


def test_copyable_model_ids_and_shared_clipboard_behavior():
    model = make_model("vendor/longcat-model:free", name="Longcat Model")
    html = render.page(
        "Directory", "comparisons-free-models-ranking.html",
        render.model_rows([model])[0][1], "2026-01-01T00:00:00Z")
    assert 'data-copy-value="vendor/longcat-model:free"' in html
    assert 'aria-label="Copy model ID: vendor/longcat-model:free"' in html
    assert 'navigator.clipboard.writeText' in html
    assert '1500' in html
    assert 'aria-live="polite"' in html


def test_openrouter_quick_start_uses_current_roster_model():
    models = [
        make_model("first/model:free", source="nous"),
        make_model("openrouter/qwen-test:free", source="openrouter"),
    ]
    html = gen.render_index(models, {"added": [], "removed": [], "unchanged_count": 2}, [],
                            {"openrouter": {"ok": True, "count": 1}}, "2026-01-01T00:00:00Z")
    assert '<details class="quickstart">' in html
    assert 'Developer quick start' in html
    assert 'https://openrouter.ai/api/v1' in html
    assert 'openrouter/qwen-test:free' in html
    for label in ('cURL', 'Python', 'TypeScript / Node.js'):
        assert label in html
    assert html.index('Developer quick start') < html.index('Find a free model')


def test_external_link_and_configuration_placeholders():
    html = render.external_link('Provider', 'https://example.com/?ref=YOUR_REF_CODE', sponsored=True)
    assert 'rel="noopener noreferrer sponsored"' in html
    assert 'target="_blank"' in html
    assert set(render.PROVIDER_CONFIG) == {'openrouter', 'nous', 'opencode-zen'}
    assert render.SITE_CONFIG['support_url'] == 'https://ko-fi.com/jacekcaban'
    assert render.SITE_CONFIG['site_url'] == 'https://llmroster.dev'


def test_site_url_builds_absolute_paths():
    assert render.site_url() == 'https://llmroster.dev'
    assert render.site_url('feed.xml') == 'https://llmroster.dev/feed.xml'
    assert render.site_url('/feed.xml') == 'https://llmroster.dev/feed.xml'


def test_meta_tags_are_absolute_and_site_scoped():
    html = render.page('Home', 'index.html', '<p>Home</p>', '2026-01-01T00:00:00Z')
    assert '<link rel="canonical" href="https://llmroster.dev">' in html
    assert '<meta property="og:url" content="https://llmroster.dev">' in html
    assert 'content="llmroster.dev"' in html
    assert 'href="https://llmroster.dev/feed.xml"' in html
    assert 'href="feed.xml"' not in html.split('</head>', 1)[0]


def test_footer_and_feed_head_links_are_present():
    html = render.page('Home', 'index.html', '<p>Home</p>', '2026-01-01T00:00:00Z')
    assert 'application/rss+xml' in html
    assert 'href="feed.xml"' in html
    assert 'Model changes feed' in html
    assert '>Support</span></a>' in html
    assert 'LLM Roster' in html
    assert 'Hermes Model Wiki' not in html
    assert 'Hermes Wiki' not in html
    assert 'href="https://ko-fi.com/jacekcaban"' in html
    assert '>RunPod</a> &mdash; affiliate link' in html
    assert 'rel="noopener noreferrer sponsored">RunPod</a>' in html
    assert '<header class="header" role="banner">' in html
    assert 'header-links' in html
    assert html.index('header-links') < html.index('</header>')
    assert 'footer-links' in html
    assert 'GPU compute: <a' not in html.split('<footer class="footer">', 1)[1].split('</footer>', 1)[0]
    assert 'Generated 2026-01-01 01:00' in html


def test_theme_toggle_is_present_and_persists_choice():
    html = render.page('Home', 'index.html', '<p>Home</p>', '2026-01-01T00:00:00Z')
    assert '<meta name="color-scheme" content="light dark">' in html
    assert 'id="theme-color-meta"' in html
    assert 'data-theme-toggle' in html
    assert 'localStorage.getItem(\'llmroster-theme\')' in html
    assert 'localStorage.setItem(\'llmroster-theme\',next)' in html
    # The restoring script must run before the body paints to avoid a palette flash.
    assert html.index('llmroster-theme') < html.index('<body>')
    assert html.index('data-theme-toggle') < html.index('</header>')
    # The nav toggle must sit inside .header-start, not as a fourth header child: the
    # header is a 1fr/auto/1fr grid and a stray child would claim a track of its own.
    assert 'class="header-start"' in html
    start = html.index('class="header-start"')
    assert start < html.index('class="nav-toggle"') < html.index('class="htitle"') < html.index('class="header-meta"')


def test_palette_defines_light_default_and_both_dark_paths():
    css = render.BASE_CSS
    assert ':root[data-theme="dark"]' in css
    assert '@media (prefers-color-scheme: dark)' in css
    assert ':root:not([data-theme="light"])' in css
    assert 'prefers-color-scheme: light)' not in css
    assert 'color-scheme: light' in css and 'color-scheme: dark' in css
    # The near-black OLED-crushed background must be gone.
    assert '#0b0d10' not in css


def test_header_centres_its_meta_block_with_a_three_track_grid():
    css = render.BASE_CSS
    # A 1fr/auto/1fr grid is what actually centres .header-meta. flex + space-between
    # cannot, because the left and right groups differ in width.
    assert 'grid-template-columns:1fr auto 1fr' in css
    assert '.header-meta{' in css and 'justify-self:center' in css
    # An auto margin on a header side group would absorb all free space and collapse the
    # meta block against the title. (margin-left:auto is legitimate elsewhere - .main>*
    # and .filter-count both rely on it - so scope the check to the header rules.)
    assert '.header-right{display:flex;align-items:center;justify-self:end;gap:var(--space-3)}' in css
    header_rules = '\n'.join(line for line in css.splitlines()
                             if line.startswith('.header') or 'header-meta' in line or 'header-right' in line)
    assert 'margin-left:auto' not in header_rules
    # The mobile drawer dim must follow the theme too, not a hardcoded black.
    assert 'rgba(0,0,0,.5)' not in css


def test_sidebar_rules_bleed_to_the_column_edges_and_content_stays_left_anchored():
    css = render.BASE_CSS
    # The two horizontal rules (brand divider, Support divider) must span the full sidebar
    # column, so the sidebar's line and the footer's line read as one boundary. The sidebar
    # padding is var(--space-4) per side, so the bleed has to cancel exactly that much.
    for sel in ('.sidebar-brand', '.sidebar-support'):
        idx = css.index(sel)
        block = css[idx:css.index('}', idx)]
        assert 'calc(-1 * var(--space-4))' in block, sel
        assert 'padding-left:var(--space-4)' in block, sel
        assert 'padding-right:var(--space-4)' in block, sel
    # Content must stay left-anchored: margin:auto here made the gutter grow with the
    # viewport (32px at 1440, 196px at 1920) and the rules drifted apart.
    content_rule = [l for l in css.splitlines() if l.startswith('.main>*')][0]
    assert 'margin-left:auto' not in content_rule and 'margin-right:auto' not in content_rule
    assert 'max-width:1280px' in content_rule


def test_rss_feed_is_valid_and_limited_to_twenty_newest_events():
    history = [{"at": f"2026-01-{day:02d}T00:00:00Z", "added": [f"vendor/model-{day}<x>"],
                "removed": [f"old/model-{day}"]} for day in range(1, 23)]
    xml = gen.render_feed(history, "2026-02-01T00:00:00Z")
    root = ET.fromstring(xml)
    assert root.tag == 'rss' and root.attrib['version'] == '2.0'
    channel = root.find('channel')
    assert channel is not None
    items = channel.findall('item')
    assert len(items) == 20
    assert 'model-22<x>' in items[0].findtext('description')
    assert items[0].findtext('guid').startswith('urn:model-wiki:change:')
    assert channel.findtext('link') == 'https://llmroster.dev'
    self_link = channel.find('{http://www.w3.org/2005/Atom}link')
    assert self_link is not None and self_link.attrib['href'] == 'https://llmroster.dev/feed.xml'


def test_rss_feed_is_valid_when_history_is_empty():
    root = ET.fromstring(gen.render_feed([], '2026-02-01T00:00:00Z'))
    assert root.find('channel') is not None
    assert root.find('channel').findall('item') == []
