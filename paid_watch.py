#!/usr/bin/env python3
"""Detect the free -> paid transition and persist it as a one-shot event.

The roster keeps only price==0 models, so a model that starts charging simply
vanishes from `data/models.json` and nothing on disk remembers it was ever
free. `data/paid-watch.json` is that memory: every model ever confirmed free is
remembered with the pricing last seen for it, so a price above zero on a later
run is attributable rather than ambiguous.

Two rules keep the signal honest, and both matter more than the happy path:

- Silence is not evidence. A model missing from a source that FAILED this run
  tells us nothing. Only a source reported healthy can prove a model is gone.
- Notify once. `notified_at` is sticky: a paid model re-fetched every day must
  not produce an event every day. The event resets only when the model returns
  to price==0 and is re-confirmed free.
"""

import json
import os

from sources.common import is_zero_price, normalize_id

WATCH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "paid-watch.json")
# A watch is only interesting while the model is plausibly still around; a
# model absent for this many consecutive healthy runs is retired from the list.
ABSENT_RETIRE_RUNS = 30


def _now():
    from snapshot import _now as snapshot_now
    return snapshot_now()


def load_watch(path=None):
    # Read at call time: a default argument freezes the path at import and
    # makes the file impossible to redirect (tests, dry runs).
    path = path or WATCH_FILE
    if not os.path.exists(path):
        return {"watched": {}, "updated_at": ""}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError:
        return {"watched": {}, "updated_at": ""}
    data.setdefault("watched", {})
    data.setdefault("updated_at", "")
    return data


def save_watch(state, path=None):
    path = path or WATCH_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return state


def watched_ids(state):
    return set((state.get("watched") or {}).keys())


def _paid_observation(recorder, model_id, statuses):
    """Best current evidence about one model's price, or None.

    Returns (is_paid, detail) where detail names the source that decided.
    Prefers a priced source over Zen: Zen publishes no prices, so a Zen-only
    model can only be judged by whether it is still listed there.
    """
    priced = []
    for source, status in (statuses or {}).items():
        if not status.get("ok"):
            # Failed source: its silence carries no information either way.
            continue
        entry = recorder.lookup(model_id, source)
        if not entry or not entry.get("present"):
            continue
        pricing = entry.get("pricing") or {}
        if not pricing:
            # Zen-style presence with no published price: free as far as we know.
            continue
        priced.append((source, pricing))

    for source, pricing in priced:
        if not is_zero_price(pricing):
            return True, {"source": source, "pricing": _clean(pricing)}
    return False, {"source": priced[0][0] if priced else "", "pricing": {}}


def _clean(pricing):
    out = {}
    for key in ("prompt", "completion"):
        value = pricing.get(key)
        if value is None:
            continue
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            out[key] = str(value)
    return out


def update(state, models, recorder, statuses, now=None):
    """Fold this run into the watch state; returns (state, new_events).

    `models` is the merged roster (post free-filter), `recorder` a
    WatchRecorder that observed the full catalogs. Events are per model, one
    per free -> paid transition, never repeated while the model stays paid.
    """
    now = now or _now()
    watched = state.get("watched") or {}
    roster = {normalize_id(m["id"]): m for m in models}
    events = []

    # Every model currently free joins the watch.
    for model_id, model in roster.items():
        entry = watched.setdefault(model_id, {})
        entry.setdefault("first_seen_free", now)
        entry["last_seen_free"] = now
        entry.pop("absent_runs", None)
        entry.pop("last_absent_at", None)
        # A model back at price==0 clears the sticky notification, so if it
        # charges again later that is genuinely news. Both flags must go:
        # clearing only `notified_at` would leave `event_emitted` set and
        # silently swallow the second transition forever.
        entry.pop("notified_at", None)
        entry["event_emitted"] = False
        entry["name"] = model.get("name", "")
        entry["free_basis"] = model.get("free_basis", "")

    for model_id, entry in watched.items():
        if model_id in roster:
            continue
        is_paid, detail = _paid_observation(recorder, model_id, statuses)
        if is_paid:
            entry["notified_at"] = entry.get("notified_at") or now
            entry["last_paid_at"] = now
            entry["paid_pricing"] = detail["pricing"]
            entry["paid_source"] = detail["source"]
            entry.pop("absent_runs", None)
            if entry.get("event_emitted") is not True:
                events.append({
                    "event": "model.became_paid",
                    "at": now,
                    "model_id": model_id,
                    "name": entry.get("name", ""),
                    "source": detail["source"],
                    "pricing": detail["pricing"],
                    "last_seen_free": entry.get("last_seen_free", ""),
                })
                entry["event_emitted"] = True
        else:
            # Free again, or a curated model whose only evidence was Zen
            # presence: not paid. Consecutive healthy absences retire the entry.
            entry["event_emitted"] = False
            entry.pop("paid_pricing", None)
            entry.pop("paid_source", None)
            absent = int(entry.get("absent_runs", 0)) + 1
            entry["absent_runs"] = absent
            entry["last_absent_at"] = now
            if absent >= ABSENT_RETIRE_RUNS:
                entry["retired"] = True

    # Keep the file from growing without bound; retired entries go first.
    active = {k: v for k, v in watched.items() if not v.get("retired")}
    retired = {k: v for k, v in watched.items() if v.get("retired")}
    limit = 500
    if len(active) > limit:
        for key in sorted(active, key=lambda k: active[k].get("last_seen_free", ""))[:len(active) - limit]:
            retired[key] = active.pop(key)
    state = {"watched": {**active, **retired}, "updated_at": now}
    return state, events


def append_events(events, path=None):
    """Persist emitted events into the shared log in `events.py`.

    `paid_watch` only decides WHAT happened; the event log, its cap and its
    dedupe belong to one place so the dispatcher has a single file to read.
    """
    if not events:
        return events
    import events as E
    if path is not None:
        E.append(events, path=path)
    else:
        E.append(events)
    return events


def load_events(limit=None, path=None):
    import events as E
    return E.load_events(limit=limit or E.MAX_EVENTS, path=path or E.EVENT_FILE)
