"""End-to-end wiring of the paid watcher inside gen.py.

The unit tests in `test_paid_watch.py` cover `update()` in isolation. These
cover the integration that actually failed once: a model that turns paid must
produce `model.became_paid` on the SAME run it leaves the roster, not on the
run after. That regression was caused by feeding the previous roster back in
as if it were still current, which made the watcher skip the price check for
exactly the models it needed to check.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import events as E
import gen
import paid_watch as P
import snapshot as S
from sources.common import make_model, merge

FREE = {"prompt": "0", "completion": "0"}
PAID = {"prompt": "0.0000004", "completion": "0.0000011"}


def _catalog(turnpaid_is_paid, gain_is_present, new_is_present):
    # `x/gain` is listed by OpenRouter from the start and only later by Nous, so
    # it gains a provider. A model absent from every catalog at first would be
    # an `added` event, not an `endpoint.added` one.
    return {
        "openrouter": [("x/keep:free", FREE),
                       ("x/turnpaid:free", PAID if turnpaid_is_paid else FREE),
                       ("x/new:free", FREE if new_is_present else None),
                       ("x/gain:free", FREE)],
        "nous": [("x/keep:free", FREE),
                 ("x/turnpaid:free", PAID if turnpaid_is_paid else FREE),
                 ("x/gain:free", FREE if gain_is_present else None)],
        "opencode-zen": [],
    }


def _install(tmp_path, **flags):
    """Point gen.py at a fixed catalog and throwaway data/dist paths.

    The module constants are reassigned because every data path is read at call
    time, not bound as a default argument at import. A `def f(p=FILE)` would
    silently ignore this and write to the real data/ directory.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (tmp_path / "dist").mkdir(exist_ok=True)

    def fake_collect(recorder=None):
        out, statuses = [], {}
        for source, entries in _catalog(**flags).items():
            kept = 0
            for model_id, price in entries:
                if price is None:
                    continue
                if recorder is not None:
                    recorder.record(model_id, price, source)
                if price is FREE:
                    kept += 1
                    out.append(make_model(model_id, name=model_id,
                                          context_length=1024, source=source))
            statuses[source] = {"ok": True, "count": kept, "error": ""}
        return merge(out), statuses

    gen.collect_all = fake_collect
    gen.OUT_DIR = str(tmp_path / "dist")
    S.DATA_DIR = str(data_dir)
    S.MODELS_FILE = os.path.join(str(data_dir), "models.json")
    S.HISTORY_FILE = os.path.join(str(data_dir), "history.json")
    P.WATCH_FILE = os.path.join(str(data_dir), "paid-watch.json")
    E.EVENT_FILE = os.path.join(str(data_dir), "events.json")
    return fake_collect


def _run(tmp_path, **flags):
    _install(tmp_path, **flags)
    gen.main()


def _events(tmp_path, event_type):
    return [e for e in E.load_events(path=E.EVENT_FILE) if e["event"] == event_type]


def test_became_paid_fires_on_the_run_it_leaves_the_roster(tmp_path):

    _run(tmp_path, turnpaid_is_paid=False, gain_is_present=False, new_is_present=False)
    assert _events(tmp_path, "model.became_paid") == []

    _run(tmp_path, turnpaid_is_paid=True, gain_is_present=False, new_is_present=False)
    paid = _events(tmp_path, "model.became_paid")
    assert len(paid) == 1, "transition must be reported on the same run"
    assert paid[0]["model_id"] == "x/turnpaid"
    assert paid[0]["pricing"]["prompt"] == 0.0000004


def test_paid_event_supersedes_removal_for_the_same_model(tmp_path):

    _run(tmp_path, turnpaid_is_paid=False, gain_is_present=False, new_is_present=False)
    _run(tmp_path, turnpaid_is_paid=True, gain_is_present=False, new_is_present=False)
    # A model that started charging is reported once, as became_paid, not
    # additionally as an unexplained removal.
    assert [e["model_id"] for e in _events(tmp_path, "model.removed")] == []


def test_gaining_a_provider_emits_endpoint_added(tmp_path):

    _run(tmp_path, turnpaid_is_paid=False, gain_is_present=False, new_is_present=False)
    _run(tmp_path, turnpaid_is_paid=False, gain_is_present=True, new_is_present=False)
    added = _events(tmp_path, "endpoint.added")
    assert [e["model_id"] for e in added] == ["x/gain"]
    assert added[0]["provider"] == "nous"
    assert added[0]["base_url"] == "https://inference-api.nousresearch.com/v1"


def test_new_model_emits_added_but_not_endpoint_added(tmp_path):

    _run(tmp_path, turnpaid_is_paid=False, gain_is_present=False, new_is_present=False)
    # The baseline run legitimately emits `added` for everything it starts
    # with, so only what the SECOND run adds is under test here.
    baseline = {e["id"] for e in _events(tmp_path, "model.added")}
    _run(tmp_path, turnpaid_is_paid=False, gain_is_present=False, new_is_present=True)
    fresh = [e for e in _events(tmp_path, "model.added") if e["id"] not in baseline]
    assert [e["model_id"] for e in fresh] == ["x/new"]
    assert _events(tmp_path, "endpoint.added") == []


def test_repeated_runs_emit_nothing_new(tmp_path):

    # Baseline first: a model that was never free cannot become paid, so the
    # transition needs a run where it IS free before it flips.
    _run(tmp_path, turnpaid_is_paid=False, gain_is_present=True, new_is_present=True)
    flags = dict(turnpaid_is_paid=True, gain_is_present=True, new_is_present=True)
    _run(tmp_path, **flags)
    before = len(E.load_events(path=E.EVENT_FILE))
    _run(tmp_path, **flags)
    _run(tmp_path, **flags)
    assert len(E.load_events(path=E.EVENT_FILE)) == before
    assert len(_events(tmp_path, "model.became_paid")) == 1
