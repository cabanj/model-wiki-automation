#!/usr/bin/env python3
"""The public event log: `data/events.json`.

One append-only JSON array is the single hand-off point to the webhook
dispatcher. Everything that subscribers care about lands here with a stable
`id`, so a retry or a re-run can never deliver the same transition twice.

`paid_watch` produces the pricing transitions and the roster diff produces the
membership ones; this module owns the persistence both share, plus the rule for
what must NOT become an event.
"""

import hashlib
import json
import os

from sources.common import PROVIDER_BASE_URLS

EVENT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "events.json")
MAX_EVENTS = 500

EVENT_TYPES = (
    "model.became_paid",
    "model.added",
    "model.removed",
    "endpoint.added",
)


def _now():
    from snapshot import _now as snapshot_now
    return snapshot_now()


def event_id(event):
    """Content-addressed id. Same transition -> same id, so `append` dedupes.

    The `at` timestamp is excluded on purpose: a re-run of the same real-world
    change is the same event, and including the clock would make dedupe useless
    exactly when it is needed.
    """
    material = {k: v for k, v in event.items() if k not in ("at", "id")}
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _endpoints(model):
    """(provider, base_url, model_id) triples for a model, same rule as the API."""
    source_ids = model.get("source_ids") or {}
    out = set()
    for source in model.get("sources", []):
        base_url = PROVIDER_BASE_URLS.get(source)
        if not base_url:
            continue
        out.add((source, base_url,
                 source_ids.get(source) or model.get("display_id") or model["id"]))
    return out


def _removal_cause(model, statuses):
    """Why a model left the roster, or None when the reason is not trustworthy.

    A model that was only ever listed by a source which is DOWN right now has
    not been removed by anyone — the outage removed it. Emitting that as a
    removal would tell subscribers a model was delisted when the truth is that
    we simply stopped being able to see it. Suppressed, not reclassified.

    A model that a healthy source used to list and no longer does is a real
    removal, whatever the other sources are doing.
    """
    sources = model.get("sources") or []
    if not sources:
        return "no_longer_free"
    healthy = [s for s in sources if (statuses.get(s) or {}).get("ok")]
    if healthy:
        return "no_longer_free"
    return None


def roster_events(old_models, new_models, statuses, now=None):
    """Per-model events for what changed between two rosters.

    `endpoint.added` is deliberately limited to models that were already on the
    roster: a brand-new model already has `model.added` carrying its endpoints,
    and firing both would double-count the same news.
    """
    now = now or _now()
    old_by_id = {m["id"]: m for m in (old_models or [])}
    new_by_id = {m["id"]: m for m in (new_models or [])}
    events = []

    for model_id in sorted(set(new_by_id) - set(old_by_id)):
        model = new_by_id[model_id]
        events.append({
            "event": "model.added",
            "at": now,
            "model_id": model_id,
            "name": model.get("name", ""),
            "free_basis": model.get("free_basis", ""),
            "sources": list(model.get("sources", [])),
            "endpoints": [{"provider": p, "base_url": b, "model_id": i}
                          for p, b, i in sorted(_endpoints(model))],
        })

    for model_id in sorted(set(old_by_id) - set(new_by_id)):
        model = old_by_id[model_id]
        cause = _removal_cause(model, statuses)
        if cause is None:
            continue
        events.append({
            "event": "model.removed",
            "at": now,
            "model_id": model_id,
            "name": model.get("name", ""),
            "cause": cause,
            "last_sources": list(model.get("sources", [])),
        })

    for model_id in sorted(set(old_by_id) & set(new_by_id)):
        added = _endpoints(new_by_id[model_id]) - _endpoints(old_by_id[model_id])
        for provider, base_url, callable_id in sorted(added):
            events.append({
                "event": "endpoint.added",
                "at": now,
                "model_id": model_id,
                "name": new_by_id[model_id].get("name", ""),
                "provider": provider,
                "base_url": base_url,
                "callable_id": callable_id,
            })

    return [dict(e, id=event_id(e)) for e in events]


def load_events(limit=None, path=None):
    # Paths are read at call time, not bound as default arguments: a default
    # would freeze the value at import, so nothing (a test, a dry run) could
    # redirect the log to another directory.
    if path is None:
        path = EVENT_FILE
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)[-(limit or MAX_EVENTS):]
    except ValueError:
        return []


def append(events, path=None, limit=None):
    """Merge new events into the log, dropping ids already present.

    Returns (stored, added_count). Dedupe is bounded by the file itself: once
    an event scrolls out of the capped window it could in principle be
    re-delivered, which is why `delivered_at` exists for the dispatcher to set
    and check rather than relying on presence in this file.
    """
    path = path or EVENT_FILE
    limit = limit or MAX_EVENTS
    if not events:
        return load_events(path=path, limit=limit), 0
    history = load_events(path=path, limit=limit)
    known = {e.get("id") for e in history if e.get("id")}
    added = []
    for event in events:
        event = dict(event)
        event.setdefault("id", event_id(event))
        if event["id"] in known:
            continue
        known.add(event["id"])
        added.append(event)
    if not added:
        return history, 0
    history = (history + added)[-limit:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return history, len(added)
