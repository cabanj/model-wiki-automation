"""Delivery loop: read the shared event log, queue it, drain the queue.

Kept separate from the HTTP server on purpose. A delivery can take ten seconds
per attempt, and blocking the API on that would let one slow subscriber delay
subscription creation for everyone. The two processes share only SQLite.
"""

import json
import os
import time

from . import store
from .signing import deliver

PERMANENT = "permanent"


def load_events(config, since=None):
    """Read `data/events.json`, skipping anything already handled.

    The event log is capped and rewritten in place, so there is no offset to
    remember: a high-water mark on the event id is what makes this idempotent
    across restarts.
    """
    if not os.path.exists(config.events_path):
        return []
    try:
        with open(config.events_path, encoding="utf-8") as handle:
            events = json.load(handle)
    except ValueError:
        return []
    if not isinstance(events, list):
        return []
    if since:
        seen = set(since)
        fresh = [e for e in events if e.get("id") and e.get("id") not in seen]
        return fresh
    return [e for e in events if e.get("id")]


def sync_events(connection, config, since=None):
    """Queue unseen events for every matching active subscription."""
    events = load_events(config, since)
    if not events:
        return 0
    created = store.enqueue_many(connection, events, time.time())
    return created


def process_due(connection, config, now=None, limit=100):
    """Attempt every delivery whose backoff has elapsed.

    Returns counters for logging. A 4xx that is not 408/429 is permanent and
    goes straight to dead, because retrying a refused request forever is how a
    queue turns into a denial of service against our own process.
    """
    now = now or time.time()
    stats = {"attempted": 0, "delivered": 0, "retried": 0, "dead": 0, "disabled": 0}

    for row in store.due_deliveries(connection, now, limit=limit):
        subscription = store.get_subscription(connection, row["subscription_id"])
        if not subscription or subscription["status"] != "active":
            # Subscription removed or disabled while this was queued.
            store.mark_dead(connection, row["id"], "subscription inactive", attempts=row["attempts"])
            stats["dead"] += 1
            continue

        attempts = row["attempts"] + 1
        stats["attempted"] += 1
        try:
            event = json.loads(row["payload"])
        except ValueError:
            store.mark_dead(connection, row["id"], "corrupt payload", attempts=attempts)
            stats["dead"] += 1
            continue

        ok, status_code, detail = deliver(
            subscription["url"], subscription["secret"], event, config,
            row["id"], attempts, now=now)

        if ok:
            store.mark_delivered(connection, row["id"], now, status_code)
            store.record_success(connection, subscription["id"], now)
            connection.commit()
            stats["delivered"] += 1
            continue

        if detail.startswith(PERMANENT) or attempts >= config.max_attempts:
            store.mark_dead(connection, row["id"], detail, status_code, attempts=attempts)
            stats["dead"] += 1
        else:
            store.mark_retry(connection, row["id"], now + config.backoff_for(attempts),
                             detail, status_code, attempts=attempts)
            stats["retried"] += 1
        connection.commit()

        failures = store.record_failure(connection, subscription["id"], now)
        if failures >= config.disable_after_failures:
            store.set_status(connection, subscription["id"], "disabled", now)
            stats["disabled"] += 1

    store.prune_old(connection, now - config.delivery_retention_hours * 3600)
    return stats


def run_once(connection, config, limit=100):
    """One dispatcher pass: queue new events, then attempt what is due.

    `process_due` is called with no explicit `now` so it re-reads the clock
    AFTER enqueueing. Passing the pre-enqueue timestamp made every freshly
    queued row look not-yet-due, and the new event silently waited for the
    next pass.
    """
    queued = sync_events(connection, config)
    stats = process_due(connection, config, now=time.time(), limit=limit)
    stats["queued"] = queued
    return stats


def run_forever(config, interval=30, limit=100, iterations=None):
    """Dispatcher loop. `iterations` bounds it for tests."""
    connection = store.connect(config.db_path)
    store.init_db(config.db_path)
    count = 0
    try:
        while iterations is None or count < iterations:
            stats = run_once(connection, config, limit=limit)
            if any(stats.values()):
                print("dispatcher:", json.dumps(stats, sort_keys=True), flush=True)
            count += 1
            if iterations is not None and count >= iterations:
                break
            time.sleep(interval)
    finally:
        connection.close()
