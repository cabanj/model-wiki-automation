import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import bench as B


def test_hy3_maps_to_paid_proxy():
    free = [{"id": "tencent/hy3", "display_id": "tencent/hy3:free"}]
    aa = [{"name": "Hy3",
           "artificial_analysis_intelligence_index": 42.2,
           "artificial_analysis_coding_index": 58.8,
           "gpqa": 0.897,
           "pricing": {"price_1m_blended_3_to_1": 0.241}}]
    matched = B.match_free(free, aa)
    assert matched.get("tencent/hy3", {}).get("name") == "Hy3"


def test_excluded_model_absent_from_ranking():
    # z-ai/glm-5.2 is persistently 429 as free — must not top free rankings
    assert "z-ai/glm-5.2" in B.BENCH_EXCLUDE
    free = [{"id": "z-ai/glm-5.2", "display_id": "z-ai/glm-5.2:free"},
            {"id": "meituan/longcat-2.0", "display_id": "meituan/longcat-2.0:free"}]
    aa = [{"name": "GLM-5.2 (max)",
           "artificial_analysis_intelligence_index": 99.9,
           "pricing": {"price_1m_blended_3_to_1": 2.15}},
          {"name": "LongCat 2.0",
           "artificial_analysis_intelligence_index": 10.0,
           "pricing": {"price_1m_blended_3_to_1": 0.5}}]
    ranked = B.rank_free_for_field(
        free, aa, "artificial_analysis_intelligence_index", top_n=3)
    ids = [m["id"] for _, m in ranked]
    assert "z-ai/glm-5.2" not in ids
    assert "meituan/longcat-2.0" in ids


def test_paid_proxy_mark():
    assert B.proxy_mark({"pricing": {"price_1m_blended_3_to_1": 0.241}}) == "‡"
    assert B.proxy_mark({"pricing": {"price_1m_blended_3_to_1": 0}}) == ""
    assert B.proxy_mark({}) == ""
    assert B.proxy_mark(None) == ""
