import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import api
import bench as B


def _model(model_id, **over):
    base = {"id": model_id, "display_id": model_id, "name": model_id,
            "description": "", "context_length": 1000, "modalities": "text",
            "tools": False, "sources": ["openrouter"], "source_ids": {},
            "free_basis": "price-0"}
    base.update(over)
    return base


def test_endpoints_use_per_source_id():
    # The normalized id is not always callable: OpenRouter and Nous prefix /
    # suffix it differently, so the endpoint must carry the per-source id.
    model = _model("inclusionai/ling-3.0-flash-fin",
                   source_ids={"openrouter": "inclusionai/ling-3.0-flash-fin",
                               "nous": "ling-3.0-flash-fin:free"},
                   sources=["openrouter", "nous"])
    endpoints = {e["provider"]: e for e in api.build_endpoints(model)}
    assert endpoints["openrouter"]["base_url"] == "https://openrouter.ai/api/v1"
    assert endpoints["openrouter"]["model_id"] == "inclusionai/ling-3.0-flash-fin"
    assert endpoints["nous"]["base_url"] == "https://inference-api.nousresearch.com/v1"
    assert endpoints["nous"]["model_id"] == "ling-3.0-flash-fin:free"


def test_endpoints_skip_non_callable_source():
    # models.dev enriches Zen metadata but is not a callable endpoint.
    model = _model("mimo-v2.5", sources=["opencode-zen", "models.dev"],
                   source_ids={"opencode-zen": "mimo-v2.5-free",
                               "models.dev": "mimo-v2.5"})
    assert [e["provider"] for e in api.build_endpoints(model)] == ["opencode-zen"]


def test_endpoints_fall_back_to_display_id_without_source_ids():
    # Old snapshots predate source_ids; the payload must still build.
    model = _model("z-ai/glm-5.2", display_id="z-ai/glm-5.2:free")
    model.pop("source_ids")
    assert api.build_endpoints(model)[0]["model_id"] == "z-ai/glm-5.2:free"


def test_payload_shape_and_counts():
    snapshot = {
        "generated_at": "2026-09-26T20:35:20Z",
        "statuses": {"openrouter": {"ok": True, "count": 1, "error": ""}},
        "models": [_model("a/b")],
    }
    payload = api.build_payload(snapshot, {})
    assert payload["schema_version"] == api.SCHEMA_VERSION
    assert payload["generated_at"] == "2026-09-26T20:35:20Z"
    assert payload["counts"] == {"models": 1, "sources": 1}
    assert payload["sources"]["openrouter"]["ok"] is True
    model = payload["models"][0]
    for key in ("id", "display_id", "name", "free_basis", "sources",
                "context_length", "modalities", "tools", "endpoints", "benchmarks"):
        assert key in model, key
    assert model["benchmarks"]["matched"] is False
    assert model["benchmarks"]["intelligence_index"] is None


def test_benchmarks_agree_with_rendered_matching():
    # The API must reuse bench.match_free, not a second mapping that can drift.
    free = [_model("tencent/hy3", display_id="tencent/hy3:free")]
    aa = [{"name": "Hy3",
           "artificial_analysis_intelligence_index": 42.2,
           "gpqa": 0.897,
           "pricing": {"price_1m_blended_3_to_1": 0.241}}]
    index = B.build_index(free, aa)
    record = index["tencent/hy3"]
    assert record["aa_matched"] is True
    assert record["aa_name"] == "Hy3"
    assert record["paid_proxy"] is True
    assert record["artificial_analysis_intelligence_index"] == 42.2

    payload = api.build_payload({"models": free, "statuses": {}}, index)
    b = payload["models"][0]["benchmarks"]
    assert b["matched"] is True
    assert b["intelligence_index"] == 42.2
    assert b["gpqa"] == 0.897
    assert b["paid_proxy"] is True


def test_excluded_model_flagged_but_still_scored():
    free = [_model("z-ai/glm-5.2")]
    aa = [{"name": "GLM-5.2 (max)",
           "artificial_analysis_intelligence_index": 99.9,
           "pricing": {"price_1m_blended_3_to_1": 2.15}}]
    record = B.build_index(free, aa)["z-ai/glm-5.2"]
    assert record["excluded"] is True
    assert record["artificial_analysis_intelligence_index"] == 99.9


def test_benchmark_index_roundtrip(tmp_path):
    free = [_model("meituan/longcat-2.0")]
    aa = [{"name": "LongCat 2.0", "artificial_analysis_coding_index": 12.5,
           "pricing": {"price_1m_blended_3_to_1": 0}}]
    path = str(tmp_path / "benchmarks.json")
    B.save_index(free, aa, "2026-09-26T20:35:20Z", path=path)
    loaded = B.load_index(path)
    assert loaded["meituan/longcat-2.0"]["artificial_analysis_coding_index"] == 12.5
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["generated_at"] == "2026-09-26T20:35:20Z"


def test_load_index_missing_or_corrupt(tmp_path):
    assert B.load_index(str(tmp_path / "nope.json")) == {}
    corrupt = tmp_path / "benchmarks.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert B.load_index(str(corrupt)) == {}


def test_write_is_atomic_and_leaves_no_tmp(tmp_path):
    path = str(tmp_path / "api" / "v1" / "roster.json")
    api.write(api.build_payload({"models": [_model("a/b")], "statuses": {}}, {}), path)
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["counts"]["models"] == 1
    assert not os.path.exists(path + ".tmp")
