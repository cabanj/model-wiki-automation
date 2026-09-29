import hashlib
import hmac
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from webhooks import store
from webhooks.config import Config
from webhooks.dispatcher import process_due, run_once, sync_events
from webhooks.signing import (CHALLENGE_HEADER, EVENT_HEADER, DELIVERY_HEADER,
                              build_payload, new_secret, sign, verify_endpoint)
from webhooks.urls import InvalidTarget, validate_url

SECRET = "a" * 64
PRIVATE = Config({"ROSTER_WEBHOOK_ALLOW_PRIVATE": "1"})


def _event(event_id="e1", event_type="model.became_paid", **over):
    base = {"id": event_id, "event": event_type, "at": "2026-09-28T18:00:00Z",
            "model_id": "a/b"}
    base.update(over)
    return base


def _config(**over):
    env = {"ROSTER_WEBHOOK_ALLOW_PRIVATE": "1"}
    env.update({k: str(v) for k, v in over.items()})
    return Config(env)


# --- URL validation: the SSRF boundary -------------------------------------

def test_rejects_non_https():
    for url in ("http://example.com/hook", "ftp://example.com/hook", "file:///etc/passwd"):
        try:
            validate_url(url)
            raise AssertionError(f"{url} should be rejected")
        except InvalidTarget:
            pass


def test_rejects_loopback_private_and_metadata():
    # Each of these reaches something valuable on the VPS itself: the LiteLLM
    # router on 4000, the admin ports, and cloud instance metadata.
    for host in ("127.0.0.1", "localhost", "10.0.0.5", "192.168.1.1",
                 "172.16.0.1", "169.254.169.254", "[::1]", "0.0.0.0"):
        try:
            validate_url(f"https://{host}/hook", allow_private=False)
            raise AssertionError(f"{host} should be rejected")
        except InvalidTarget:
            pass


def test_rejects_ipv4_mapped_ipv6_loopback():
    # ::ffff:127.0.0.1 is localhost wearing a disguise; a naive is_loopback check
    # on the outer address does not catch it.
    try:
        validate_url("https://[::ffff:127.0.0.1]/hook", allow_private=False)
        raise AssertionError("IPv4-mapped loopback should be rejected")
    except InvalidTarget:
        pass


def test_rejects_credentials_in_url():
    try:
        validate_url("https://user:pass@example.com/hook")
        raise AssertionError("credentials should be rejected")
    except InvalidTarget as error:
        assert "credential" in str(error)


def test_rejects_empty_and_oversized():
    for url in ("", "   ", None):
        try:
            validate_url(url)
            raise AssertionError("empty url should be rejected")
        except InvalidTarget:
            pass
    try:
        validate_url("https://example.com/" + "a" * 3000)
        raise AssertionError("oversized url should be rejected")
    except InvalidTarget:
        pass


def test_allows_public_https():
    # Resolution is stubbed: this asserts the policy, not DNS availability, and
    # a test that needs example.com to resolve fails on a machine with no
    # outbound DNS for a reason that has nothing to do with the code.
    import webhooks.urls as U
    original = U.resolve_addresses
    U.resolve_addresses = lambda host, allow_private=False: ["93.184.216.34"]
    try:
        assert validate_url("https://hooks.example.com/incoming").hostname == "hooks.example.com"
    finally:
        U.resolve_addresses = original


def test_hostname_resolving_to_private_is_rejected(monkeypatch=None):
    # A public hostname whose DNS points at 127.0.0.1 is the standard bypass of
    # a hostname-only check, so validation happens after resolution.
    import webhooks.urls as U
    original = U.resolve_addresses
    U.resolve_addresses = lambda host, allow_private=False: ["127.0.0.1"]
    try:
        try:
            validate_url("https://sneaky.example.com/hook", allow_private=False)
            raise AssertionError("private-resolving host should be rejected")
        except InvalidTarget as error:
            assert "127.0.0.1" in str(error)
    finally:
        U.resolve_addresses = original


def test_one_public_one_private_address_is_rejected():
    import webhooks.urls as U
    original = U.resolve_addresses
    U.resolve_addresses = lambda host, allow_private=False: ["93.184.216.34", "127.0.0.1"]
    try:
        try:
            validate_url("https://mixed.example.com/hook", allow_private=False)
            raise AssertionError("mixed public/private should be rejected")
        except InvalidTarget:
            pass
    finally:
        U.resolve_addresses = original


# --- signing ----------------------------------------------------------------

def test_signature_verifies_and_detects_tampering():
    body = build_payload(_event())
    signature = sign(SECRET, body, 1700000000)
    expected = "sha256=" + hmac.new(SECRET.encode(),
                                    b"1700000000." + body.encode(),
                                    hashlib.sha256).hexdigest()
    assert signature == expected


def test_signature_covers_the_timestamp():
    # Replaying a captured body with a fresh timestamp must not produce a
    # signature that verifies, or the timestamp is decorative.
    body = build_payload(_event())
    assert sign(SECRET, body, 1700000000) != sign(SECRET, body, 1700009999)


def test_wrong_secret_does_not_verify():
    body = build_payload(_event())
    assert sign(SECRET, body, 1700000000) != sign("b" * 64, body, 1700000000)


def test_payload_excludes_internal_fields():
    payload = json.loads(build_payload(_event()))
    assert payload["type"] == "model.became_paid"
    assert payload["id"] == "e1"
    assert payload["data"]["model_id"] == "a/b"
    assert "event" not in payload["data"]


def test_new_secret_is_unique_and_long():
    secrets = {new_secret() for _ in range(50)}
    assert len(secrets) == 50
    assert all(len(s) >= 64 for s in secrets)


# --- ownership challenge ----------------------------------------------------

def test_verification_requires_echoed_token():
    # A 2xx that does not echo the challenge is exactly a catch-all endpoint,
    # which is what a relay attempt looks like. It must not pass.
    import webhooks.signing as S
    captured = {}

    class FakeResponse:
        status = 200

        def read(self, _n):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_post(url, body, headers, timeout, allow_private):
        captured.update(headers)
        return FakeResponse()

    original = S._post
    S._post = fake_post
    try:
        ok, detail = verify_endpoint("https://example.com/hook", SECRET, PRIVATE)
        assert ok is False
        assert "challenge" in detail.lower()
    finally:
        S._post = original


def test_verification_succeeds_when_token_echoed():
    import webhooks.signing as S
    captured = {}

    class FakeResponse:
        status = 200

        def read(self, _n):
            return captured["_body"]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_post(url, body, headers, timeout, allow_private):
        captured["_body"] = json.dumps({"challenge": headers[CHALLENGE_HEADER]}).encode()
        return FakeResponse()

    original = S._post
    S._post = fake_post
    try:
        ok, detail = verify_endpoint("https://example.com/hook", SECRET, PRIVATE)
        assert ok is True, detail
    finally:
        S._post = original


def test_verification_fails_on_network_error():
    import webhooks.signing as S

    def fake_post(*a, **k):
        raise OSError("connection refused")

    original = S._post
    S._post = fake_post
    try:
        ok, detail = verify_endpoint("https://example.com/hook", SECRET, PRIVATE)
        assert ok is False
        assert "refused" in detail
    finally:
        S._post = original


# --- store ------------------------------------------------------------------

def test_enqueue_is_idempotent_per_event(tmp_path):
    connection = store.connect(str(tmp_path / "w.db"))
    store.init_db(str(tmp_path / "w.db"))
    store.create_subscription(connection, "a" * 16, "https://x.example/hook",
                              ["*"], SECRET, "1.2.3.4", time.time())
    assert store.enqueue(connection, "a" * 16, _event(), time.time()) is True
    # A replay after a crash must not become a second notification.
    assert store.enqueue(connection, "a" * 16, _event(), time.time()) is False
    assert store.pending_count(connection) == 1
    connection.close()


def test_subscription_filtering(tmp_path):
    path = str(tmp_path / "w.db")
    connection = store.connect(path)
    store.init_db(path)
    store.create_subscription(connection, "a" * 16, "https://x.example/h", ["model.added"],
                              SECRET, "1.1.1.1", time.time())
    store.create_subscription(connection, "b" * 16, "https://y.example/h", ["*"],
                              SECRET, "1.1.1.2", time.time())
    store.enqueue_many(connection, [_event("e1", "model.added"),
                                    _event("e2", "model.became_paid")], time.time())
    pending = connection.execute(
        "SELECT subscription_id, event_id FROM deliveries ORDER BY subscription_id").fetchall()
    pairs = {(r["subscription_id"], r["event_id"]) for r in pending}
    assert pairs == {("a" * 16, "e1"), ("b" * 16, "e1"), ("b" * 16, "e2")}
    connection.close()


def test_inactive_subscription_receives_nothing(tmp_path):
    path = str(tmp_path / "w.db")
    connection = store.connect(path)
    store.init_db(path)
    store.create_subscription(connection, "a" * 16, "https://x.example/h", ["*"],
                              SECRET, "1.1.1.1", time.time())
    store.set_status(connection, "a" * 16, "disabled", time.time())
    assert store.enqueue_many(connection, [_event()], time.time()) == 0
    connection.close()


def test_delete_removes_queue_and_subscription(tmp_path):
    path = str(tmp_path / "w.db")
    connection = store.connect(path)
    store.init_db(path)
    store.create_subscription(connection, "a" * 16, "https://x.example/h", ["*"],
                              SECRET, "1.1.1.1", time.time())
    store.enqueue_many(connection, [_event()], time.time())
    assert store.delete_subscription(connection, "a" * 16) is True
    assert store.get_subscription(connection, "a" * 16) is None
    assert store.pending_count(connection) == 0
    connection.close()


def test_per_ip_cap_counts_only_active(tmp_path):
    path = str(tmp_path / "w.db")
    connection = store.connect(path)
    store.init_db(path)
    for i in range(3):
        store.create_subscription(connection, f"{i:016x}", "https://x.example/h",
                                  ["*"], SECRET, "9.9.9.9", time.time())
    assert store.count_for_ip(connection, "9.9.9.9") == 3
    store.set_status(connection, f"{0:016x}", "disabled", time.time())
    assert store.count_for_ip(connection, "9.9.9.9") == 2
    connection.close()


def test_corrupt_json_returns_empty(tmp_path):
    bad = tmp_path / "events.json"
    bad.write_text("{ broken", encoding="utf-8")
    config = _config()
    config.events_path = str(bad)
    assert sync_events(store.connect(str(tmp_path / "w.db")), config) == 0


def test_events_without_id_are_skipped(tmp_path):
    path = tmp_path / "events.json"
    path.write_text(json.dumps([{"event": "model.added"}]), encoding="utf-8")
    config = _config()
    config.events_path = str(path)
    connection = store.connect(str(tmp_path / "w.db"))
    store.init_db(str(tmp_path / "w.db"))
    assert sync_events(connection, config) == 0
    connection.close()


# --- delivery loop ----------------------------------------------------------

def _prepare(tmp_path, subscription_status="active"):
    path = str(tmp_path / "w.db")
    connection = store.connect(path)
    store.init_db(path)
    store.create_subscription(connection, "a" * 16, "https://x.example/h", ["*"],
                              SECRET, "1.1.1.1", time.time())
    if subscription_status != "active":
        store.set_status(connection, "a" * 16, subscription_status, time.time())
    return connection


def test_successful_delivery_is_marked_once(tmp_path):
    import webhooks.dispatcher as D
    connection = _prepare(tmp_path)
    store.enqueue_many(connection, [_event()], time.time())
    calls = []

    original = D.deliver
    D.deliver = lambda *a, **k: (calls.append(1), (True, 200, "ok"))[1]
    try:
        stats = process_due(connection, _config(), now=time.time())
    finally:
        D.deliver = original
    assert stats["delivered"] == 1
    assert store.pending_count(connection) == 0
    # A second pass must not redeliver the same event.
    stats2 = process_due(connection, _config(), now=time.time())
    assert stats2["attempted"] == 0
    assert len(calls) == 1
    connection.close()


def test_failed_delivery_retries_with_backoff(tmp_path):
    import webhooks.dispatcher as D
    connection = _prepare(tmp_path)
    store.enqueue_many(connection, [_event()], time.time())
    original = D.deliver
    D.deliver = lambda *a, **k: (False, 500, "HTTP 500")
    try:
        now = time.time()
        stats = process_due(connection, _config(), now=now)
        assert stats["retried"] == 1
        row = connection.execute("SELECT * FROM deliveries").fetchone()
        assert row["attempts"] == 1
        assert row["next_attempt"] > now, "retry must be scheduled in the future"
    finally:
        D.deliver = original
    connection.close()


def test_permanent_4xx_is_not_retried(tmp_path):
    # A 400 will not become a 200 on retry; retrying it forever would pin a
    # worker on a request that can never succeed.
    import webhooks.dispatcher as D
    connection = _prepare(tmp_path)
    store.enqueue_many(connection, [_event()], time.time())
    original = D.deliver
    D.deliver = lambda *a, **k: (False, 400, "permanent HTTP 400")
    try:
        stats = process_due(connection, _config(), now=time.time())
    finally:
        D.deliver = original
    assert stats["dead"] == 1
    assert stats["retried"] == 0
    assert store.pending_count(connection) == 0
    connection.close()


def test_408_and_429_are_retried(tmp_path):
    # Each status gets its own database: reusing one path would collide on the
    # UNIQUE(subscription_id, event_id) constraint, not on the behaviour under
    # test.
    import webhooks.dispatcher as D
    for index, status in enumerate((408, 429)):
        directory = tmp_path / f"case{index}"
        directory.mkdir()
        connection = _prepare(directory)
        store.enqueue_many(connection, [_event(f"e{index}")], time.time())
        original = D.deliver
        D.deliver = lambda *a, **k: (False, status, f"HTTP {status}")
        try:
            stats = process_due(connection, _config(), now=time.time())
        finally:
            D.deliver = original
        assert stats["retried"] == 1, status
        connection.close()


def test_delivery_gives_up_after_max_attempts(tmp_path):
    import webhooks.dispatcher as D
    connection = _prepare(tmp_path)
    store.enqueue_many(connection, [_event()], time.time())
    original = D.deliver
    D.deliver = lambda *a, **k: (False, 500, "HTTP 500")
    try:
        config = _config(ROSTER_WEBHOOK_MAX_ATTEMPTS=3, ROSTER_WEBHOOK_BACKOFF="0")
        # Drive attempts forward by making each retry due immediately.
        for _ in range(5):
            connection.execute("UPDATE deliveries SET next_attempt = 0")
            connection.commit()
            process_due(connection, config, now=time.time())
        row = connection.execute("SELECT * FROM deliveries").fetchone()
        assert row["status"] == "dead"
        assert row["attempts"] == 3
    finally:
        D.deliver = original
    connection.close()


def test_subscription_disabled_after_repeated_failures(tmp_path):
    import webhooks.dispatcher as D
    connection = _prepare(tmp_path)
    store.enqueue_many(connection, [_event()], time.time())
    original = D.deliver
    D.deliver = lambda *a, **k: (False, 500, "HTTP 500")
    try:
        config = _config(ROSTER_WEBHOOK_MAX_ATTEMPTS=100,
                         ROSTER_WEBHOOK_DISABLE_AFTER=3)
        for _ in range(3):
            connection.execute("UPDATE deliveries SET next_attempt = 0")
            connection.commit()
            process_due(connection, config, now=time.time())
        subscription = store.get_subscription(connection, "a" * 16)
        assert subscription["status"] == "disabled"
    finally:
        D.deliver = original
    connection.close()


def test_success_resets_failure_counter(tmp_path):
    import webhooks.dispatcher as D
    connection = _prepare(tmp_path)
    store.enqueue_many(connection, [_event()], time.time())
    original = D.deliver
    try:
        D.deliver = lambda *a, **k: (False, 500, "HTTP 500")
        connection.execute("UPDATE deliveries SET next_attempt = 0")
        process_due(connection, _config(), now=time.time())
        assert store.get_subscription(connection, "a" * 16)["failures"] == 1
        D.deliver = lambda *a, **k: (True, 200, "ok")
        connection.execute("UPDATE deliveries SET next_attempt = 0")
        process_due(connection, _config(), now=time.time())
        assert store.get_subscription(connection, "a" * 16)["failures"] == 0
    finally:
        D.deliver = original
    connection.close()


def test_delivery_to_removed_subscription_is_dropped(tmp_path):
    connection = _prepare(tmp_path)
    store.enqueue_many(connection, [_event()], time.time())
    store.delete_subscription(connection, "a" * 16)
    # Re-insert the queue row to simulate a row outliving its subscription.
    # created_at must be recent: process_due prunes settled rows older than the
    # retention window, and a zero timestamp would be pruned before we assert.
    connection.execute(
        "INSERT INTO deliveries (subscription_id, event_id, event_type, payload,"
        " next_attempt, created_at) VALUES (?, 'e1', 'model.became_paid', '{}', 0, ?)",
        ("a" * 16, time.time()))
    connection.commit()
    stats = process_due(connection, _config(), now=time.time())
    assert stats["attempted"] == 0
    assert store.dead_count(connection) == 1
    connection.close()


def test_corrupt_payload_is_dead_not_crashing(tmp_path):
    connection = _prepare(tmp_path)
    connection.execute(
        "INSERT INTO deliveries (subscription_id, event_id, event_type, payload,"
        " next_attempt, created_at) VALUES (?, 'e1', 'model.became_paid', 'not json', 0, ?)",
        ("a" * 16, time.time()))
    connection.commit()
    stats = process_due(connection, _config(), now=time.time())
    assert stats["dead"] == 1
    connection.close()


def test_delivery_sends_expected_headers(tmp_path):
    import webhooks.signing as S
    seen = {}

    class FakeResponse:
        status = 200

        def read(self, _n):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_post(url, body, headers, timeout, allow_private):
        seen.update(headers)
        seen["_body"] = body.decode()
        seen["_url"] = url
        return FakeResponse()

    original = S._post
    S._post = fake_post
    try:
        ok, status, detail = S.deliver("https://x.example/h", SECRET, _event(),
                                       PRIVATE, "d1", 2, now=1700000000)
    finally:
        S._post = original
    assert ok is True
    assert seen[EVENT_HEADER] == "model.became_paid"
    assert seen[DELIVERY_HEADER] == "d1"
    assert seen[CHALLENGE_HEADER] if CHALLENGE_HEADER in seen else True
    assert "X-Roster-Signature" in seen
    body = json.loads(seen["_body"])
    assert body["attempt"] == 2
    # The signature must cover exactly the bytes we send.
    assert seen["X-Roster-Signature"] == sign(SECRET, seen["_body"], 1700000000)


def test_run_once_delivers_in_the_same_pass(tmp_path):
    # Regression: run_once used to capture `now` before enqueueing, so a
    # freshly queued event looked not-yet-due and waited a whole interval. A
    # model.became_paid one pass late is a notification that arrives after the
    # subscriber has already acted on the change.
    from webhooks.dispatcher import run_once
    import webhooks.dispatcher as D
    (tmp_path / "events.json").write_text(
        json.dumps([_event()]), encoding="utf-8")
    config = _config()
    config.events_path = str(tmp_path / "events.json")
    connection = store.connect(str(tmp_path / "w.db"))
    store.init_db(str(tmp_path / "w.db"))
    store.create_subscription(connection, "a" * 16, "https://x.example/h", ["*"],
                              SECRET, "1.1.1.1", time.time())
    original = D.deliver
    D.deliver = lambda *a, **k: (True, 200, "ok")
    try:
        stats = run_once(connection, config)
        assert stats["queued"] == 1
        assert stats["delivered"] == 1, stats
    finally:
        D.deliver = original
        connection.close()


def test_config_backoff_repeats_last_value():
    config = Config({"ROSTER_WEBHOOK_BACKOFF": "1,2,3"})
    assert config.backoff == [1, 2, 3]
    assert config.backoff_for(1) == 1
    assert config.backoff_for(3) == 3
    assert config.backoff_for(99) == 3, "last value repeats"
    assert Config().backoff == [60, 300, 1800, 7200, 21600]


def test_config_honours_overrides_instead_of_ambient_environment(monkeypatch=None):
    # A regression guard: `_int`/`_bool` used to read os.environ directly, so
    # every override below was silently ignored and production defaults were
    # used during tests. That hides exactly the behaviour under test.
    import os
    os.environ["ROSTER_WEBHOOK_MAX_ATTEMPTS"] = "99"
    try:
        config = Config({"ROSTER_WEBHOOK_MAX_ATTEMPTS": "3"})
        assert config.max_attempts == 3
        assert config.disable_after_failures == 10  # default, not ambient
        assert Config().max_attempts == 99           # ambient is honoured
    finally:
        del os.environ["ROSTER_WEBHOOK_MAX_ATTEMPTS"]
