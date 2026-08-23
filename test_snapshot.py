import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(__file__))
import snapshot as S
from sources.common import make_model


def test_diff():
    old = [make_model("a"), make_model("b"), make_model("c")]
    new = [make_model("b"), make_model("c"), make_model("d")]
    d = S.diff(old, new)
    assert d["added"] == ["d"] and d["removed"] == ["a"]
    assert d["unchanged_count"] == 2


def test_snapshot_and_history_roundtrip(tmp_path=None):
    d1 = tempfile.mkdtemp()
    mp, hp = os.path.join(d1, "m.json"), os.path.join(d1, "h.json")
    models = [make_model("x/y:free", name="Y")]
    S.save_snapshot(models, {"openrouter": {"ok": True}}, path=mp)
    snap = S.load_snapshot(mp)
    assert snap["models"][0]["id"] == "x/y"
    S.append_history(S.diff([], models), path=hp)
    S.append_history(S.diff(models, models), path=hp)  # no change -> no entry
    h = S.load_history(path=hp)
    assert len(h) == 1 and h[0]["added"] == ["x/y"]
