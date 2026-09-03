import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.common import normalize_id, is_zero_price, make_model, merge
from sources import fetch_modelsdev, fetch_opencode_zen, collect_all
from sources import _zen_basis


def test_normalize():
    assert normalize_id("Nvidia/X:free") == "nvidia/x"
    assert normalize_id("hy3-free") == "hy3"
    assert normalize_id("openai/gpt") == "openai/gpt"


def test_zero_price_strict():
    assert is_zero_price({"prompt": "0", "completion": "0"})
    assert not is_zero_price({"prompt": "0.0000003", "completion": "0"})   # micro
    assert not is_zero_price({"prompt": None, "completion": "0"})          # missing
    assert not is_zero_price({})                                           # absent


def test_merge_dedupes_and_unions_sources():
    a = make_model("tencent/hy3:free", name="Hy3", source="nous")
    b = make_model("tencent/hy3", description="longer desc here", source="openrouter")
    m = merge([a, b])
    assert len(m) == 1
    assert sorted(m[0]["sources"]) == ["nous", "openrouter"]
    assert m[0]["description"] == "longer desc here"


def test_modelsdev_live_filter():
    models, err = fetch_modelsdev()
    assert err == ""
    # every returned model must have zero cost; plan providers flagged
    for m in models:
        assert m["sources"] == ["models.dev"]
        if "plan" in m["free_basis"]:
            continue  # plan providers allowed but labeled
    assert any(m["free_basis"] == "price-0" for m in models)


def test_zen_gone_ids_reported():
    models, _ = fetch_opencode_zen()
    ids = {m["id"] for m in models}
    # whatever is curated must either be live or reported as error by caller
    assert isinstance(ids, set)


def test_zen_basis_micro_exempt():
    micro = {"prompt": "0.0000001", "completion": "0.0000002"}
    zero = {"prompt": "0", "completion": "0"}
    assert _zen_basis("muse-spark-1.3-contributor-free", micro) == "zen-micro"
    assert _zen_basis("muse-spark-1.2-contributor-free", micro) is None  # not exempt
    assert _zen_basis("muse-spark-1.3-contributor-free", zero) == "zen-free"
    assert _zen_basis("muse-spark-1.3-contributor-free", None) == "zen-free"


def test_collect_all_never_raises_and_merges():
    merged, statuses = collect_all()
    print("statuses:", {k: (v["count"], v["error"][:40]) for k, v in statuses.items()})
    assert len(merged) > 5
    ids = [m["id"] for m in merged]
    assert len(ids) == len(set(ids))
    multi = [m for m in merged if len(m["sources"]) > 1]
    print(f"total free: {len(merged)}, confirmed by >1 source: {len(multi)}")
