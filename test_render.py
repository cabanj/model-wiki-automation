import bench as B
import gen
import render
from sources.common import make_model


def test_table_has_accessible_headers_and_caption():
    html = render.table(["Model", "Score"], [["model-a", "1.0"]], caption="Scores", row_header=0)
    assert '<caption>Scores</caption>' in html
    assert '<th scope="col">Model</th>' in html
    assert '<th scope="row">model-a</th>' in html


def test_model_directory_has_search_and_use_case_metadata():
    model = make_model("vendor/longcat-model:free", name="Longcat Model", description="Long context model")
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
    model = {"id": "vendor/longcat-model", "display_id": "vendor/longcat-model:free", "modalities": "text"}
    aa = [{"name": "Longcat Model", "artificial_analysis_intelligence_index": 20,
           "artificial_analysis_coding_index": 15, "gpqa": 0.7,
           "terminalbench_hard": 0.4,
           "pricing": {"price_1m_blended_3_to_1": 0}}]
    monkeypatch.setattr(B, "fetch_aa", lambda: (aa, ""))
    html = B.render([model], "2026-01-01T00:00:00Z")
    assert 'summary-card' in html
    assert 'Overall intelligence' in html
    assert 'free models and paid reference' in html
    assert 'Longcat Model' in html
