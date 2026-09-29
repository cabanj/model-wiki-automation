"""SQLite persistence for subscriptions and delivery attempts.

The queue is a table, not an in-memory list, for one reason: a subscriber's
delivery must survive a restart of the service. Losing a pending retry because
the process was reloaded would mean silently dropping a `model.became_paid`
that we had already accepted, which is the one thing a webhook cannot do.
"""

import json
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id            TEXT PRIMARY KEY,
    url           TEXT NOT NULL,
    events        TEXT NOT NULL,
    secret        TEXT NOT NULL,
    ip            TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    REAL NOT NULL,
    last_ok_at    REAL,
    failures      INTEGER NOT NULL DEFAULT 0,
    verified_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subs_status ON subscriptions(status);

CREATE TABLE IF NOT EXISTS deliveries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id TEXT NOT NULL,
    event_id       TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    payload        TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    attempts       INTEGER NOT NULL DEFAULT 0,
    next_attempt   REAL NOT NULL,
    last_error     TEXT,
    last_status    INTEGER,
    created_at     REAL NOT NULL,
    delivered_at   REAL,
    UNIQUE (subscription_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_deliv_due ON deliveries(status, next_attempt);
CREATE INDEX IF NOT EXISTS idx_deliv_sub  ON deliveries(subscription_id, status);
"""


def connect(db_path):
    """Open a connection. One per thread — see `thread_connection`.

    `check_same_thread=False` alone is not enough: a single connection shared
    by a threaded server interleaves transactions between requests, so a
    rollback in one handler would discard another's committed work.
    """
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    # WAL keeps a long delivery transaction from blocking the API's reads.
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


_local = threading.local()


def thread_connection(db_path):
    """The calling thread's connection, opened on first use.

    ThreadingHTTPServer handles every request on a fresh thread, and SQLite
    forbids sharing a connection across threads. One connection per thread
    keeps each request's transactions isolated from every other request's.
    """
    existing = getattr(_local, "connections", None)
    if existing is None:
        existing = _local.connections = {}
    if db_path not in existing:
        existing[db_path] = connect(db_path)
    return existing[db_path]


def init_db(db_path):
    connection = connect(db_path)
    try:
        connection.executescript(SCHEMA)
        connection.commit()
    finally:
        connection.close()


# --- subscriptions ---------------------------------------------------------

def create_subscription(connection, subscription_id, url, events, secret, ip, now):
    connection.execute(
        "INSERT INTO subscriptions (id, url, events, secret, ip, created_at, verified_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (subscription_id, url, json.dumps(sorted(events)), secret, ip, now, now))
    connection.commit()


def get_subscription(connection, subscription_id):
    row = connection.execute(
        "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
    return dict(row) if row else None


def list_subscriptions(connection, status=None):
    if status:
        rows = connection.execute(
            "SELECT * FROM subscriptions WHERE status = ? ORDER BY created_at",
            (status,)).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM subscriptions ORDER BY created_at").fetchall()
    return [dict(row) for row in rows]


def count_subscriptions(connection, status="active"):
    return connection.execute(
        "SELECT COUNT(*) FROM subscriptions WHERE status = ?", (status,)).fetchone()[0]


def count_for_ip(connection, ip):
    return connection.execute(
        "SELECT COUNT(*) FROM subscriptions WHERE ip = ? AND status = 'active'",
        (ip,)).fetchone()[0]


def delete_subscription(connection, subscription_id):
    """Remove the subscription and its queue. Hard delete: a subscriber asking
    to be removed must not leave a secret on disk."""
    connection.execute("DELETE FROM deliveries WHERE subscription_id = ?", (subscription_id,))
    cursor = connection.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
    connection.commit()
    return cursor.rowcount > 0


def set_status(connection, subscription_id, status, now=None):
    connection.execute("UPDATE subscriptions SET status = ? WHERE id = ?",
                       (status, subscription_id))
    if status == "active":
        connection.execute(
            "UPDATE subscriptions SET failures = 0, last_ok_at = ? WHERE id = ?",
            (now or time.time(), subscription_id))
    connection.commit()


def record_success(connection, subscription_id, now):
    connection.execute(
        "UPDATE subscriptions SET failures = 0, last_ok_at = ? WHERE id = ?",
        (now, subscription_id))


def record_failure(connection, subscription_id, now):
    """Increment the failure counter and report the new value."""
    connection.execute(
        "UPDATE subscriptions SET failures = failures + 1 WHERE id = ?", (subscription_id,))
    connection.commit()
    row = connection.execute(
        "SELECT failures FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
    return row["failures"] if row else 0


# --- delivery queue --------------------------------------------------------

def enqueue(connection, subscription_id, event, now):
    """Queue one event for one subscription. Idempotent on (sub, event_id).

    A crash between "event detected" and "delivery recorded" replays the same
    event, and the unique constraint turns that into a no-op rather than a
    duplicate notification.
    """
    cursor = connection.execute(
        "INSERT OR IGNORE INTO deliveries"
        " (subscription_id, event_id, event_type, payload, next_attempt, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (subscription_id, event["id"], event["event"],
         json.dumps(event, ensure_ascii=False), now, now))
    return cursor.rowcount > 0


def enqueue_many(connection, events, now, event_types=None):
    """Queue events for every active subscription that asked for them.

    Returns the number of rows created so the caller can log work done rather
    than work attempted.
    """
    subscriptions = list_subscriptions(connection, status="active")
    created = 0
    for subscription in subscriptions:
        wanted = set(json.loads(subscription["events"]))
        for event in events:
            if event_types and event["event"] not in event_types:
                continue
            if "*" not in wanted and event["event"] not in wanted:
                continue
            if enqueue(connection, subscription["id"], event, now):
                created += 1
    return created


def due_deliveries(connection, now, limit=100):
    rows = connection.execute(
        "SELECT * FROM deliveries WHERE status = 'pending' AND next_attempt <= ?"
        " ORDER BY next_attempt LIMIT ?", (now, limit)).fetchall()
    return [dict(row) for row in rows]


def mark_delivered(connection, delivery_id, now, status_code):
    connection.execute(
        "UPDATE deliveries SET status = 'delivered', delivered_at = ?,"
        " attempts = attempts + 1, last_status = ?, last_error = NULL WHERE id = ?",
        (now, status_code, delivery_id))


def mark_retry(connection, delivery_id, next_attempt, error, status_code=None, attempts=None):
    if attempts is None:
        connection.execute(
            "UPDATE deliveries SET attempts = attempts + 1, next_attempt = ?,"
            " last_error = ?, last_status = ? WHERE id = ?",
            (next_attempt, str(error)[:500], status_code, delivery_id))
    else:
        connection.execute(
            "UPDATE deliveries SET attempts = ?, next_attempt = ?, last_error = ?,"
            " last_status = ? WHERE id = ?",
            (attempts, next_attempt, str(error)[:500], status_code, delivery_id))


def mark_dead(connection, delivery_id, error, status_code=None, attempts=None):
    if attempts is None:
        connection.execute(
            "UPDATE deliveries SET status = 'dead', attempts = attempts + 1,"
            " last_error = ?, last_status = ? WHERE id = ?",
            (str(error)[:500], status_code, delivery_id))
    else:
        connection.execute(
            "UPDATE deliveries SET status = 'dead', attempts = ?, last_error = ?,"
            " last_status = ? WHERE id = ?",
            (attempts, str(error)[:500], status_code, delivery_id))


def pending_count(connection):
    return connection.execute(
        "SELECT COUNT(*) FROM deliveries WHERE status = 'pending'").fetchone()[0]


def dead_count(connection):
    return connection.execute(
        "SELECT COUNT(*) FROM deliveries WHERE status = 'dead'").fetchone()[0]


def prune_old(connection, before):
    """Drop settled rows so the queue file does not grow forever."""
    connection.execute(
        "DELETE FROM deliveries WHERE status IN ('delivered', 'dead') AND created_at < ?",
        (before,))
    connection.commit()
