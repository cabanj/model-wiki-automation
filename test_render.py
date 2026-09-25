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
    assert render.SITE_CONFIG['support_url'] == ''
    assert render.SITE_CONFIG['site_url'] == ''


def test_footer_and_feed_head_links_are_present():
    html = render.page('Home', 'index.html', '<p>Home</p>', '2026-01-01T00:00:00Z')
    assert 'application/rss+xml' in html
    assert 'href="feed.xml"' in html
    assert 'Model changes feed' in html
    assert 'Support' in html
    assert 'GPU hosting recommendations' in html
    assert 'Generated 2026-01-01 01:00' in html


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
    assert channel.findtext('link') == 'index.html'


def test_rss_feed_is_valid_when_history_is_empty():
    root = ET.fromstring(gen.render_feed([], '2026-02-01T00:00:00Z'))
    assert root.find('channel') is not None
    assert root.find('channel').findall('item') == []
