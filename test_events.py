import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import events as E

OK_ALL = {"openrouter": {"ok": True, "count": 2, "error": ""},
          "nous": {"ok": True, "count": 1, "error": ""}}
ZEN_DOWN = {"openrouter": {"ok": True, "count": 2, "error": ""},
            "opencode-zen": {"ok": False, "count": 0, "error": "zen: gone"}}


def _model(model_id, sources=("openrouter",), source_ids=None, **over):
    base = {"id": model_id, "display_id": model_id, "name": model_id.title(),
            "free_basis": "price-0", "sources": list(sources),
            "source_ids": source_ids if source_ids is not None else
            {s: model_id for s in sources}}
    base.update(over)
    return base


def _by_type(events, event_type):
    return [e for e in events if e["event"] == event_type]


def test_added_model_emits_one_event_with_endpoints():
    out = E.roster_events([], [_model("a/b", sources=["openrouter", "nous"])], OK_ALL)
    added = _by_type(out, "model.added")
    assert len(added) == 1
    assert added[0]["model_id"] == "a/b"
    providers = {e["provider"] for e in added[0]["endpoints"]}
    assert providers == {"openrouter", "nous"}


def test_new_model_does_not_also_emit_endpoint_added():
    # A new model's endpoints ride along in model.added; firing both would
    # double-count the same news for subscribers.
    out = E.roster_events([], [_model("a/b", sources=["openrouter", "nous"])], OK_ALL)
    assert _by_type(out, "endpoint.added") == []


def test_endpoint_added_when_model_gains_a_provider():
    before = [_model("a/b", sources=["openrouter"])]
    after = [_model("a/b", sources=["openrouter", "nous"])]
    out = E.roster_events(before, after, OK_ALL)
    assert _by_type(out, "model.added") == []
    assert _by_type(out, "model.removed") == []
    added = _by_type(out, "endpoint.added")
    assert len(added) == 1
    assert added[0]["provider"] == "nous"
    assert added[0]["base_url"] == "https://inference-api.nousresearch.com/v1"
    assert added[0]["callable_id"] == "a/b"


def test_endpoint_added_uses_per_source_callable_id():
    before = [_model("a/b", sources=["openrouter"],
                     source_ids={"openrouter": "a/b:free"})]
    after = [_model("a/b", sources=["openrouter", "nous"],
                    source_ids={"openrouter": "a/b:free", "nous": "b:free"})]
    out = E.roster_events(before, after, OK_ALL)
    added = _by_type(out, "endpoint.added")
    assert added[0]["callable_id"] == "b:free"


def test_unchanged_endpoints_emit_nothing():
    model = _model("a/b", sources=["openrouter", "nous"])
    assert E.roster_events([model], [dict(model)], OK_ALL) == []


def test_removed_model_caused_by_paid_pricing_is_reported():
    out = E.roster_events([_model("a/b")], [], OK_ALL)
    removed = _by_type(out, "model.removed")
    assert len(removed) == 1
    assert removed[0]["cause"] == "no_longer_free"
    assert removed[0]["last_sources"] == ["openrouter"]


def test_removal_during_source_outage_is_suppressed():
    # The whole point: an outage must not masquerade as a delisting.
    out = E.roster_events([_model("mimo-v2.5", sources=["opencode-zen"])], [], ZEN_DOWN)
    assert out == []


def test_removal_is_reported_when_any_claiming_source_is_healthy():
    # Listed by two sources, one of them down: the healthy one no longer lists
    # it, so it really is gone.
    before = [_model("a/b", sources=["openrouter", "opencode-zen"])]
    out = E.roster_events(before, [], ZEN_DOWN)
    assert len(_by_type(out, "model.removed")) == 1


def test_event_ids_are_stable_across_timestamps():
    a = E.roster_events([], [_model("a/b")], OK_ALL, now="2026-09-28T00:00:00Z")
    b = E.roster_events([], [_model("a/b")], OK_ALL, now="2026-09-29T18:00:00Z")
    assert a[0]["id"] == b[0]["id"]


def test_event_ids_differ_for_different_transitions():
    a = E.roster_events([], [_model("a/b")], OK_ALL)
    b = E.roster_events([], [_model("c/d")], OK_ALL)
    assert a[0]["id"] != b[0]["id"]


def test_append_dedupes_repeat_transitions(tmp_path):
    path = str(tmp_path / "events.json")
    first = E.roster_events([], [_model("a/b")], OK_ALL)
    stored, added = E.append(first, path=path)
    assert added == 1
    # Same real-world change detected again on a later run.
    stored, added = E.append(first, path=path)
    assert added == 0
    assert len(E.load_events(path=path)) == 1


def test_append_keeps_different_events(tmp_path):
    path = str(tmp_path / "events.json")
    E.append(E.roster_events([], [_model("a/b")], OK_ALL), path=path)
    _stored, added = E.append(E.roster_events([], [_model("c/d")], OK_ALL), path=path)
    assert added == 1
    assert len(E.load_events(path=path)) == 2


def test_log_is_capped(tmp_path):
    path = str(tmp_path / "events.json")
    for i in range(E.MAX_EVENTS + 40):
        E.append([{"event": "model.added", "at": "2026-09-28T00:00:00Z",
                   "model_id": f"a/{i}"}], path=path)
    history = E.load_events(path=path)
    assert len(history) == E.MAX_EVENTS


def test_append_empty_is_noop(tmp_path):
    path = str(tmp_path / "events.json")
    stored, added = E.append([], path=path)
    assert added == 0
    assert stored == []


def test_load_events_missing_and_corrupt(tmp_path):
    assert E.load_events(path=str(tmp_path / "none.json")) == []
    corrupt = tmp_path / "events.json"
    corrupt.write_text("[ broken", encoding="utf-8")
    assert E.load_events(path=str(corrupt)) == []


def test_all_event_types_are_declared():
    # Guards against a typo'd event name silently shipping to subscribers.
    produced = (E.roster_events([], [_model("a/b")], OK_ALL) +
                E.roster_events([_model("a/b")], [], OK_ALL))
    assert {e["event"] for e in produced} <= set(E.EVENT_TYPES)
