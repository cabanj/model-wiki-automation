#!/usr/bin/env python3
"""Format free-roster changes as a <=280 character X post.

Stdlib only, no network. The X API turned pay-per-use, so there is no free
automated publishing: this module produces the text, a human pastes it.

CLI:
    python x_publisher.py --added "a/b" --removed "c/d"   # print it
    python x_publisher.py --latest                        # newest local diff
"""

import argparse
import json
import os
import sys

CHAR_LIMIT = 280
SITE_URL = "https://llmroster.dev"
HASHTAGS = "#OpenSourceAI #LLM #DevCommunity"
CTA = f"Track live free endpoints & snippets: {SITE_URL}"
HEADER = "Free Model Roster Update"

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "history.json")


def _join_with_budget(prefix, items, budget):
    """'Added: a, b, c (+2 more)' fitting in `budget` chars, or None."""
    picked = []
    for item in items:
        text = f"{prefix}{', '.join(picked + [item])}"
        rest = len(items) - len(picked) - 1
        if rest > 0:
            text = f"{text} (+{rest} more)"
        if len(text) > budget:
            break
        picked.append(item)
    if not picked:
        return None
    text = f"{prefix}{', '.join(picked)}"
    rest = len(items) - len(picked)
    if rest > 0:
        text = f"{text} (+{rest} more)"
    return text


def format_message(added_models, removed_models):
    """Build the post text, guaranteed <= CHAR_LIMIT characters."""
    added = [str(m) for m in (added_models or []) if str(m).strip()]
    removed = [str(m) for m in (removed_models or []) if str(m).strip()]

    tail = [CTA, HASHTAGS]
    lines = [HEADER]
    fixed = len(HEADER) + sum(len(part) + 1 for part in tail)
    # Each change line costs its own newline; reserve one for each present line.
    budget = max(0, CHAR_LIMIT - fixed - 2)

    if added:
        line = _join_with_budget("Added: ", added, budget - 1 if removed else budget)
        if line:
            lines.append(line)
            budget -= len(line) + 1
    if removed:
        line = _join_with_budget("Dropped: ", removed, max(0, budget - 1))
        if line:
            lines.append(line)

    text = "\n".join(lines + tail)
    if len(text) > CHAR_LIMIT:  # last-resort clamp, should not trigger
        text = text[:CHAR_LIMIT - 1].rstrip() + "\u2026"
    return text


def latest_change(path=HISTORY_FILE):
    """Most recent roster change from the local history file, or None."""
    try:
        with open(path, encoding="utf-8") as f:
            history = json.load(f)
    except (OSError, ValueError):
        return None
    for entry in reversed(history or []):
        if entry.get("added") or entry.get("removed"):
            return entry
    return None


def _split_ids(raw):
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Format a roster-change post for X.")
    parser.add_argument("--added", default="", help="comma-separated added model ids")
    parser.add_argument("--removed", default="", help="comma-separated removed model ids")
    parser.add_argument("--latest", action="store_true",
                        help="use the newest change in data/history.json")
    args = parser.parse_args(argv)

    if args.latest:
        entry = latest_change()
        if not entry:
            print("no roster change recorded yet", file=sys.stderr)
            return 1
        added, removed = entry.get("added") or [], entry.get("removed") or []
    else:
        added, removed = _split_ids(args.added), _split_ids(args.removed)

    if not added and not removed:
        print("nothing to post: no additions or removals", file=sys.stderr)
        return 1

    text = format_message(added, removed)
    print(text)
    print(f"--- {len(text)}/{CHAR_LIMIT} chars ---", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
