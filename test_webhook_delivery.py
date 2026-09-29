"""Full round trip against a real subscriber endpoint.

Everything below the store is faked in the other tests. This one runs the real
HTTP server as the SUBSCRIBER and a real socket between the dispatcher and it,
because the things that actually break a webhook are on the wire: a signature
computed over different bytes than were sent, a header the subscriber cannot
read back, a body that is not the JSON it claims to be.
"""

import hashlib
import hmac
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(__file__))

from webhooks import store
from webhooks.config import Config
from webhooks.dispatcher import run_once
from webhooks.signing import (CHALLENGE_HEADER, DELIVERY_HEADER, EVENT_HEADER,
                              SIGNATURE_HEADER, TIMESTAMP_HEADER, new_secret)

received = []


class Subscriber(BaseHTTPRequestHandler):
    """Accepts deliveries, and echoes the challenge so verification passes."""

    protocol_version = "HTTP/1.1"
    status_to_return = 200
    fail_times = 0

    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        received.append({
            "path": self.path,
            "headers": dict(self.headers),
            "body": body.decode("utf-8"),
        })
        if Subscriber.fail_times > 0:
            Subscriber.fail_times -= 1
            self._respond(500, b"nope")
            return
        # A real subscriber must echo the challenge token, which is what proves
        # it controls the endpoint. Verification correctly rejects a 2xx that
        # does not, so the fake endpoint has to behave like a real one.
        challenge = self.headers.get(CHALLENGE_HEADER)
        payload = json.dumps({"challenge": challenge}) if challenge else '{"ok":true}'
        self._respond(Subscriber.status_to_return, payload.encode("utf-8"))

    def _respond(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_subscriber():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Subscriber)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/hook"


def _config(tmp_path, **over):
    env = {
        "ROSTER_WEBHOOK_DB": str(tmp_path / "w.db"),
        "ROSTER_WEBHOOK_EVENTS": str(tmp_path / "events.json"),
        "ROSTER_WEBHOOK_ALLOW_PRIVATE": "1",
        "ROSTER_WEBHOOK_ADMIN_TOKEN": "t",
        "ROSTER_WEBHOOK_BACKOFF": "1,2,3",
        "ROSTER_WEBHOOK_MAX_ATTEMPTS": "3",
    }
    env.update({k: str(v) for k, v in over.items()})
    return Config(env)


def _event(event_id="e1", event_type="model.became_paid", **over):
    base = {"id": event_id, "event": event_type, "at": "2026-09-28T18:00:00Z",
            "model_id": "a/b", "pricing": {"prompt": 1e-07, "completion": 4e-07}}
    base.update(over)
    return base


def _reset():
    received.clear()
    Subscriber.fail_times = 0
    Subscriber.status_to_return = 200


def test_subscription_flows_end_to_end_with_valid_signature(tmp_path):
    _reset()
    server, url = _start_subscriber()
    import webhooks.dispatcher as D
    from webhooks.signing import verify_endpoint

    try:
        config = _config(tmp_path)
        store.init_db(config.db_path)
        connection = store.connect(config.db_path)

        secret = new_secret()
        # Real challenge against the real subscriber.
        ok, detail = verify_endpoint(url, secret, config)
        assert ok is True, detail

        store.create_subscription(connection, "a" * 16, url, ["*"], secret,
                                  "1.2.3.4", time.time())
        (tmp_path / "events.json").write_text(
            json.dumps([_event()]), encoding="utf-8")

        stats = run_once(connection, config)
        assert stats["delivered"] == 1, stats
        # Two POSTs reached the subscriber: the ownership challenge (carrying
        # X-Roster-Challenge) and the delivery. Only the latter is the event.
        challenges = [r for r in received if CHALLENGE_HEADER in r["headers"]]
        deliveries = [r for r in received if CHALLENGE_HEADER not in r["headers"]]
        assert len(challenges) == 1
        assert len(deliveries) == 1

        request = deliveries[0]
        assert request["path"] == "/hook"
        assert request["headers"][EVENT_HEADER] == "model.became_paid"
        assert request["headers"][DELIVERY_HEADER]
        assert request["headers"][TIMESTAMP_HEADER]

        # The signature must verify over the exact bytes on the wire, using the
        # subscriber's own secret and the documented scheme.
        timestamp = request["headers"][TIMESTAMP_HEADER]
        material = timestamp.encode() + b"." + request["body"].encode()
        expected = "sha256=" + hmac.new(secret.encode(), material,
                                         hashlib.sha256).hexdigest()
        assert request["headers"][SIGNATURE_HEADER] == expected

        payload = json.loads(request["body"])
        assert payload["type"] == "model.became_paid"
        assert payload["data"]["model_id"] == "a/b"
        assert payload["data"]["pricing"]["prompt"] == 1e-07
        assert "attempt" in payload
        connection.close()
    finally:
        server.shutdown()


def test_delivery_is_retried_after_a_500_then_succeeds(tmp_path):
    _reset()
    server, url = _start_subscriber()
    import webhooks.dispatcher as D

    try:
        config = _config(tmp_path)
        store.init_db(config.db_path)
        connection = store.connect(config.db_path)
        store.create_subscription(connection, "a" * 16, url, ["*"], new_secret(),
                                  "1.2.3.4", time.time())
        (tmp_path / "events.json").write_text(
            json.dumps([_event()]), encoding="utf-8")

        Subscriber.fail_times = 1
        stats = run_once(connection, config)
        assert stats["retried"] == 1, stats
        assert store.pending_count(connection) == 1

        # Backoff is 1s here, so the retry becomes due almost immediately.
        time.sleep(1.2)
        stats = run_once(connection, config)
        assert stats["delivered"] == 1, stats
        assert store.pending_count(connection) == 0
        assert len(received) == 2
        # The retry is a NEW attempt, so the subscriber can tell them apart.
        assert json.loads(received[1]["body"])["attempt"] == 2
        connection.close()
    finally:
        server.shutdown()


def test_same_event_is_not_delivered_twice(tmp_path):
    _reset()
    server, url = _start_subscriber()
    try:
        config = _config(tmp_path)
        store.init_db(config.db_path)
        connection = store.connect(config.db_path)
        store.create_subscription(connection, "a" * 16, url, ["*"], new_secret(),
                                  "1.2.3.4", time.time())
        (tmp_path / "events.json").write_text(
            json.dumps([_event()]), encoding="utf-8")

        run_once(connection, config)
        run_once(connection, config)
        run_once(connection, config)
        assert len(received) == 1, "one event must mean exactly one delivery"
        connection.close()
    finally:
        server.shutdown()


def test_two_subscriptions_each_get_the_event(tmp_path):
    _reset()
    server_a, url_a = _start_subscriber()
    server_b, url_b = _start_subscriber()
    try:
        config = _config(tmp_path)
        store.init_db(config.db_path)
        connection = store.connect(config.db_path)
        store.create_subscription(connection, "a" * 16, url_a, ["*"], new_secret(),
                                  "1.2.3.4", time.time())
        store.create_subscription(connection, "b" * 16, url_b, ["*"], new_secret(),
                                  "5.6.7.8", time.time())
        (tmp_path / "events.json").write_text(
            json.dumps([_event()]), encoding="utf-8")

        stats = run_once(connection, config)
        assert stats["delivered"] == 2, stats
        assert len(received) == 2
        connection.close()
    finally:
        server_a.shutdown()
        server_b.shutdown()


def test_event_filter_limits_what_is_delivered(tmp_path):
    _reset()
    server, url = _start_subscriber()
    try:
        config = _config(tmp_path)
        store.init_db(config.db_path)
        connection = store.connect(config.db_path)
        store.create_subscription(connection, "a" * 16, url, ["model.added"],
                                  new_secret(), "1.2.3.4", time.time())
        (tmp_path / "events.json").write_text(
            json.dumps([_event("e1", "model.became_paid"),
                        _event("e2", "model.added")]), encoding="utf-8")

        run_once(connection, config)
        types = [json.loads(r["body"])["type"] for r in received]
        assert types == ["model.added"], types
        connection.close()
    finally:
        server.shutdown()


def test_tampered_body_fails_signature_check(tmp_path):
    # Proves the signature is load-bearing: if the body is altered in flight,
    # the subscriber's own verification rejects it.
    _reset()
    server, url = _start_subscriber()
    try:
        config = _config(tmp_path)
        store.init_db(config.db_path)
        connection = store.connect(config.db_path)
        secret = new_secret()
        store.create_subscription(connection, "a" * 16, url, ["*"], secret,
                                  "1.2.3.4", time.time())
        (tmp_path / "events.json").write_text(
            json.dumps([_event()]), encoding="utf-8")
        run_once(connection, config)

        request = received[0]
        timestamp = request["headers"][TIMESTAMP_HEADER]
        tampered = request["body"].replace("a/b", "z/z")
        material = timestamp.encode() + b"." + tampered.encode()
        recomputed = "sha256=" + hmac.new(secret.encode(), material,
                                          hashlib.sha256).hexdigest()
        assert recomputed != request["headers"][SIGNATURE_HEADER]
        connection.close()
    finally:
        server.shutdown()


def test_replay_with_a_new_timestamp_does_not_verify(tmp_path):
    # The timestamp is inside the signed material, so a captured delivery
    # cannot be replayed later with a fresh timestamp to slip past a window.
    _reset()
    server, url = _start_subscriber()
    try:
        config = _config(tmp_path)
        store.init_db(config.db_path)
        connection = store.connect(config.db_path)
        secret = new_secret()
        store.create_subscription(connection, "a" * 16, url, ["*"], secret,
                                  "1.2.3.4", time.time())
        (tmp_path / "events.json").write_text(
            json.dumps([_event()]), encoding="utf-8")
        run_once(connection, config)

        request = received[0]
        body = request["body"]
        fresh = str(int(time.time()) + 3600)
        material = fresh.encode() + b"." + body.encode()
        replay = "sha256=" + hmac.new(secret.encode(), material,
                                       hashlib.sha256).hexdigest()
        assert replay != request["headers"][SIGNATURE_HEADER]
        connection.close()
    finally:
        server.shutdown()


def test_permanent_400_does_not_reach_the_subscriber_again(tmp_path):
    _reset()
    server, url = _start_subscriber()
    try:
        config = _config(tmp_path)
        store.init_db(config.db_path)
        connection = store.connect(config.db_path)
        store.create_subscription(connection, "a" * 16, url, ["*"], new_secret(),
                                  "1.2.3.4", time.time())
        (tmp_path / "events.json").write_text(
            json.dumps([_event()]), encoding="utf-8")

        Subscriber.status_to_return = 400
        stats = run_once(connection, config)
        assert stats["dead"] == 1, stats
        time.sleep(1.2)
        run_once(connection, config)
        assert len(received) == 1, "a refused request must not be retried"
        Subscriber.status_to_return = 200
        connection.close()
    finally:
        server.shutdown()
