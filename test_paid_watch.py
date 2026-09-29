import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import paid_watch as P
from sources.watch import WatchRecorder

OK = {"ok": True, "count": 1, "error": ""}
DOWN = {"ok": False, "count": 0, "error": "openrouter: timeout"}


def _model(model_id, **over):
    base = {"id": model_id, "name": model_id, "free_basis": "price-0",
            "sources": ["openrouter"]}
    base.update(over)
    return base


def _state(*ids):
    return {"watched": {i: {"name": i, "last_seen_free": "2026-09-01T00:00:00Z"}
                        for i in ids}, "updated_at": ""}


def test_paid_model_emits_one_event():
    state = _state("a/b")
    recorder = WatchRecorder(["a/b"])
    recorder.record("a/b", {"prompt": "0.0000005", "completion": "0.0000012"}, "openrouter")
    state, events = P.update(state, [], recorder, {"openrouter": OK})
    assert len(events) == 1
    event = events[0]
    assert event["event"] == "model.became_paid"
    assert event["model_id"] == "a/b"
    assert event["source"] == "openrouter"
    assert event["pricing"]["prompt"] == 0.0000005
    assert event["pricing"]["completion"] == 0.0000012
    assert event["last_seen_free"] == "2026-09-01T00:00:00Z"


def test_paid_model_does_not_repeat():
    state = _state("a/b")
    recorder = WatchRecorder(["a/b"])
    recorder.record("a/b", {"prompt": "1", "completion": "2"}, "openrouter")
    state, first = P.update(state, [], recorder, {"openrouter": OK})
    assert len(first) == 1
    # A second identical run must stay silent: this is the bug that would
    # otherwise spam every subscriber daily.
    _, second = P.update(state, [], recorder, {"openrouter": OK})
    assert second == []
    _, third = P.update(state, [], recorder, {"openrouter": OK})
    assert third == []


def test_model_back_to_free_then_paid_again_reemits():
    state = _state("a/b")
    paid = WatchRecorder(["a/b"])
    paid.record("a/b", {"prompt": "1", "completion": "2"}, "openrouter")
    state, first = P.update(state, [], paid, {"openrouter": OK})
    assert len(first) == 1

    # Free again: rejoins the roster, sticky notification must clear.
    state, again_free = P.update(state, [_model("a/b")], WatchRecorder(), {"openrouter": OK})
    assert again_free == []
    assert "notified_at" not in state["watched"]["a/b"]

    # Paid a second time is genuinely news.
    paid2 = WatchRecorder(["a/b"])
    paid2.record("a/b", {"prompt": "3", "completion": "4"}, "openrouter")
    state, second = P.update(state, [], paid2, {"openrouter": OK})
    assert len(second) == 1
    assert second[0]["pricing"]["prompt"] == 3.0


def test_failed_source_never_reports_paid():
    # The critical case: an outage looks exactly like "every model vanished".
    # Without the health check this would fire became_paid for the whole roster.
    state = _state("a/b", "c/d")
    recorder = WatchRecorder(["a/b", "c/d"])
    _, events = P.update(state, [], recorder, {"openrouter": DOWN})
    assert events == []


def test_healthy_source_missing_model_is_not_paid():
    # Absent from a healthy catalog with no price seen anywhere: not proof of
    # charging, so it must not fire. It only ages into retirement.
    state = _state("a/b")
    recorder = WatchRecorder(["a/b"])  # observed nothing at all
    _, events = P.update(state, [], recorder, {"openrouter": OK})
    assert events == []
    assert state["watched"]["a/b"]["absent_runs"] == 1


def test_zen_presence_without_price_is_not_paid():
    # Zen publishes no prices; a curated id still listed there is free.
    state = _state("hy3")
    recorder = WatchRecorder(["hy3"])
    recorder.record("hy3-free", None, "opencode-zen")
    _, events = P.update(state, [], recorder, {"opencode-zen": OK})
    assert events == []


def test_provider_prefixed_catalog_id_is_matched_to_bare_watch():
    # Zen models are bare in the roster (`hy3`) but prefixed on OpenRouter
    # (`meta/hy3`); a missed match here means a real price change is invisible.
    state = _state("hy3")
    recorder = WatchRecorder(["hy3"])
    recorder.record("meta/hy3", {"prompt": "0.25", "completion": "1.5"}, "openrouter")
    _, events = P.update(state, [], recorder, {"openrouter": OK})
    assert len(events) == 1
    assert events[0]["model_id"] == "hy3"
    assert events[0]["pricing"]["prompt"] == 0.25


def test_zero_priced_but_absent_from_roster_is_not_paid():
    # Free model dropped by a junk/basis filter, not by pricing.
    state = _state("a/b")
    recorder = WatchRecorder(["a/b"])
    recorder.record("a/b", {"prompt": "0", "completion": "0"}, "openrouter")
    _, events = P.update(state, [], recorder, {"openrouter": OK})
    assert events == []


def test_current_free_models_are_added_to_watch():
    state = {"watched": {}, "updated_at": ""}
    recorder = WatchRecorder()
    state, events = P.update(state, [_model("a/b", name="A B")], recorder, {"openrouter": OK})
    assert events == []
    entry = state["watched"]["a/b"]
    assert entry["name"] == "A B"
    assert entry["free_basis"] == "price-0"
    assert entry["first_seen_free"] == entry["last_seen_free"]


def test_absent_model_retires_after_threshold():
    state = _state("a/b")
    recorder = WatchRecorder(["a/b"])
    for _ in range(P.ABSENT_RETIRE_RUNS):
        state, _events = P.update(state, [], recorder, {"openrouter": OK})
    assert state["watched"]["a/b"].get("retired") is True


def test_watch_file_roundtrip_and_corruption(tmp_path):
    path = str(tmp_path / "paid-watch.json")
    state = _state("a/b")
    P.save_watch(state, path)
    assert P.watched_ids(P.load_watch(path)) == {"a/b"}
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ broken")
    assert P.load_watch(path) == {"watched": {}, "updated_at": ""}
    assert P.load_watch(str(tmp_path / "missing.json")) == {"watched": {}, "updated_at": ""}


def test_paid_watch_appends_into_shared_event_log(tmp_path):
    # paid_watch no longer owns a file: the single log in events.py is what
    # the dispatcher will read, so the two must not drift apart.
    path = str(tmp_path / "events.json")
    state = _state("a/b")
    recorder = WatchRecorder(["a/b"])
    recorder.record("a/b", {"prompt": "1", "completion": "2"}, "openrouter")
    _new_state, events = P.update(state, [], recorder, {"openrouter": OK})
    P.append_events(events, path=path)
    stored = P.load_events(path=path)
    assert [e["event"] for e in stored] == ["model.became_paid"]
    assert stored[0]["model_id"] == "a/b"


def test_recorder_ignores_unwatched_ids():
    recorder = WatchRecorder(["a/b"])
    recorder.record("z/z", {"prompt": "0", "completion": "0"}, "openrouter")
    assert recorder.seen() == {}
    assert recorder.lookup("z/z", "openrouter") is None


def test_recorder_without_filter_records_everything():
    # Used when bootstrapping: no watchlist yet, so everything is interesting.
    recorder = WatchRecorder()
    recorder.record("z/z", {"prompt": "0", "completion": "0"}, "openrouter")
    assert set(recorder.seen()) == {"z/z"}


def test_load_events_missing(tmp_path):
    assert P.load_events(path=str(tmp_path / "none.json")) == []
