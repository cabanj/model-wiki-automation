"""Snapshot persistence + diff/changelog between runs."""

import json
import os
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MODELS_FILE = os.path.join(DATA_DIR, "models.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_snapshot(path=MODELS_FILE):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def diff(old_models, new_models):
    old_ids = {m["id"] for m in (old_models or [])}
    new_ids = {m["id"] for m in new_models}
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    return {"added": added, "removed": removed,
            "unchanged_count": len(old_ids & new_ids)}


def save_snapshot(models, statuses, path=MODELS_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    snap = {"generated_at": _now(), "statuses": statuses, "models": models}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return snap


def append_history(d, path=HISTORY_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    history = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            try:
                history = json.load(f)
            except ValueError:
                history = []
    if d["added"] or d["removed"]:
        history.append({"at": _now(), "added": d["added"], "removed": d["removed"]})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history[-500:], f, ensure_ascii=False, indent=1)
    return history


def load_history(limit=10, path=HISTORY_FILE):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)[-limit:]
