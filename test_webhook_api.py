"""End-to-end HTTP tests against a real server on a real socket.

The unit tests call handlers and store functions directly. They cannot catch a
route that is never wired up, a method that is not dispatched, or a body that
is not actually parsed off the socket — which is where an API this small tends
to break. So here we run the real server and speak HTTP to it.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from webhooks import store
from webhooks.config import Config
from webhooks.server import serve
from webhooks.signing import CHALLENGE_HEADER

ADMIN = "test-admin-token"


def _config(tmp_path, **over):
    env = {
        "ROSTER_WEBHOOK_DB": str(tmp_path / "w.db"),
        "ROSTER_WEBHOOK_EVENTS": str(tmp_path / "events.json"),
        "ROSTER_WEBHOOK_ADMIN_TOKEN": ADMIN,
        "ROSTER_WEBHOOK_ALLOW_PRIVATE": "1",
        "ROSTER_WEBHOOK_BIND": "127.0.0.1",
        "ROSTER_WEBHOOK_PORT": "0",
    }
    env.update({k: str(v) for k, v in over.items()})
    return Config(env)


class Client:
    def __init__(self, base):
        self.base = base

    def request(self, method, path, body=None, token=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as error:
            payload = error.read().decode()
            try:
                return error.code, json.loads(payload or "{}")
            except ValueError:
                return error.code, {"raw": payload}


def _start(tmp_path, **over):
    _stub_dns()
    config = _config(tmp_path, **over)
    server = serve(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    return server, Client(f"http://{host}:{port}"), config


def _stub_dns():
    """Point hostname validation at a public address.

    URL validation resolves the host BEFORE the ownership challenge runs, so
    tests about HTTP behaviour would otherwise depend on outbound DNS for
    example.com and fail for a reason unrelated to the code. The SSRF policy
    itself is covered in test_webhooks.py with its own resolver stubs.

    Paired with the autouse fixture below: a stubbed resolver left in place
    would silently disarm the SSRF check for every later test in the session,
    which is exactly the failure this must never cause. pytest collects files
    alphabetically, so `test_webhooks.py` can run after this one.
    """
    import webhooks.urls as U
    if getattr(U, "_dns_stubbed", False):
        return
    U._real_resolve = U.resolve_addresses
    U.resolve_addresses = lambda host, allow_private=False: ["93.184.216.34"]
    U._dns_stubbed = True


def _restore_dns():
    import webhooks.urls as U
    if getattr(U, "_dns_stubbed", False):
        U.resolve_addresses = U._real_resolve
        U._dns_stubbed = False


@pytest.fixture(autouse=True)
def _dns_stub_lifecycle():
    """Undo the module-level resolver stub around every test in this file."""
    yield
    _restore_dns()


def _stub_verification(ok=True, detail="HTTP 200 (stub)"):
    """Replace the network call with a fixed result."""
    import webhooks.server as server_module
    server_module.verify_endpoint = lambda url, secret, config, now=None: (ok, detail)
    return server_module.verify_endpoint


def test_health_needs_no_auth(tmp_path):
    server, client, _config_value = _start(tmp_path)
    try:
        status, body = client.request("GET", "/api/v1/health")
        assert status == 200
        assert body["ok"] is True
        assert body["pending"] == 0
    finally:
        server.shutdown()


def test_create_subscription_returns_secret_once(tmp_path):
    import webhooks.server as server_module
    _stub_verification()
    server, client, _ = _start(tmp_path)
    try:
        status, body = client.request(
            "POST", "/api/v1/subscriptions",
            {"url": "https://hooks.example.com/in", "events": ["model.became_paid"]})
        assert status == 201
        assert len(body["secret"]) == 64
        assert body["events"] == ["model.became_paid"]

        # Listing must never echo the secret back.
        status, listed = client.request("GET", "/api/v1/subscriptions", token=ADMIN)
        assert status == 200
        assert "secret" not in listed["subscriptions"][0]
    finally:
        server.shutdown()
        server_module.verify_endpoint = server_module.verify_endpoint


def test_create_subscription_requires_a_body(tmp_path):
    server, client, _ = _start(tmp_path)
    try:
        status, body = client.request("POST", "/api/v1/subscriptions", body=None)
        assert status == 400
        assert "body" in body["error"].lower()
    finally:
        server.shutdown()


def test_create_subscription_rejects_invalid_json(tmp_path):
    server, client, _ = _start(tmp_path)
    try:
        request = urllib.request.Request(
            client.base + "/api/v1/subscriptions", data=b"{ broken", method="POST")
        request.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(request, timeout=10)
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError as error:
            assert error.code == 400
    finally:
        server.shutdown()


def test_private_target_is_refused_before_verification(tmp_path):
    import webhooks.server as server_module
    # The URL must be rejected on policy, not by the challenge. If this failed
    # later, a private target would first receive a real request.
    called = []

    def fake_verify(url, secret, config, now=None):
        called.append(url)
        return True, "should not be reached"

    server_module.verify_endpoint = fake_verify
    # A config WITHOUT allow_private: the default production policy is what
    # this test is about, and the shared test config deliberately relaxes it.
    server, client, _ = _start(tmp_path, ROSTER_WEBHOOK_ALLOW_PRIVATE="0")
    try:
        # The LiteLLM router on 127.0.0.1:4000 is the concrete prize: an
        # open relay pointed at it would be an SSRF into an authenticated API.
        status, body = client.request(
            "POST", "/api/v1/subscriptions", {"url": "https://127.0.0.1:4000/hook"})
        assert status == 400
        assert called == [], "verification must not run for a rejected URL"
    finally:
        server.shutdown()


def test_failed_verification_does_not_create_subscription(tmp_path):
    import webhooks.server as server_module
    server_module.verify_endpoint = lambda url, secret, config, now=None: (False, "HTTP 500")
    server, client, _ = _start(tmp_path)
    try:
        status, body = client.request(
            "POST", "/api/v1/subscriptions", {"url": "https://hooks.example.com/in"})
        assert status == 400
        assert "verification" in body["error"]
        status, listed = client.request("GET", "/api/v1/subscriptions", token=ADMIN)
        assert listed["subscriptions"] == []
    finally:
        server.shutdown()


def test_per_ip_cap_returns_429(tmp_path):
    import webhooks.server as server_module
    server_module.verify_endpoint = lambda url, secret, config, now=None: (True, "ok")
    server, client, _ = _start(tmp_path,
                               ROSTER_WEBHOOK_MAX_SUBS_PER_IP=2)
    try:
        for i in range(2):
            status, _ = client.request(
                "POST", "/api/v1/subscriptions",
                {"url": f"https://hooks.example.com/{i}"},
                headers={"X-Real-IP": "5.5.5.5"})
            assert status == 201
        status, body = client.request(
            "POST", "/api/v1/subscriptions", {"url": "https://hooks.example.com/3"},
            headers={"X-Real-IP": "5.5.5.5"})
        assert status == 429
        # A different address is unaffected: the cap is per IP, not global.
        status, _ = client.request(
            "POST", "/api/v1/subscriptions", {"url": "https://hooks.example.com/4"},
            headers={"X-Real-IP": "6.6.6.6"})
        assert status == 201
    finally:
        server.shutdown()


def test_unknown_event_type_is_rejected(tmp_path):
    import webhooks.server as server_module
    server_module.verify_endpoint = lambda url, secret, config, now=None: (True, "ok")
    server, client, _ = _start(tmp_path)
    try:
        status, body = client.request(
            "POST", "/api/v1/subscriptions",
            {"url": "https://hooks.example.com/in", "events": ["model.exploded"]})
        assert status == 400
        assert "unknown event" in body["error"]
    finally:
        server.shutdown()


def test_admin_routes_require_token(tmp_path):
    server, client, _ = _start(tmp_path)
    try:
        assert client.request("GET", "/api/v1/subscriptions")[0] == 401
        assert client.request("GET", "/api/v1/subscriptions", token="wrong")[0] == 401
        assert client.request("POST", "/api/v1/dispatch")[0] == 401
        assert client.request("DELETE", "/api/v1/subscriptions/" + "a" * 16)[0] == 401
    finally:
        server.shutdown()


def test_delete_subscription(tmp_path):
    import webhooks.server as server_module
    server_module.verify_endpoint = lambda url, secret, config, now=None: (True, "ok")
    server, client, _ = _start(tmp_path)
    try:
        _status, created = client.request(
            "POST", "/api/v1/subscriptions", {"url": "https://hooks.example.com/in"})
        subscription_id = created["id"]
        assert client.request("DELETE", f"/api/v1/subscriptions/{subscription_id}",
                              token=ADMIN)[0] == 200
        assert client.request("DELETE", f"/api/v1/subscriptions/{subscription_id}",
                              token=ADMIN)[0] == 404
    finally:
        server.shutdown()


def test_unknown_route_returns_404(tmp_path):
    server, client, _ = _start(tmp_path)
    try:
        assert client.request("GET", "/api/v1/nope")[0] == 404
        # roster.json is nginx's job, not ours: the service must not serve a
        # second, divergent copy of the public payload.
        assert client.request("GET", "/api/v1/roster.json")[0] == 404
    finally:
        server.shutdown()


def test_dispatch_endpoint_queues_and_attempts(tmp_path):
    import webhooks.dispatcher as dispatcher_module
    events = [{"id": "e1", "event": "model.became_paid", "at": "t", "model_id": "a/b"}]
    (tmp_path / "events.json").write_text(json.dumps(events), encoding="utf-8")

    calls = []
    # Patch the name where it is USED. `server.py` does `from .dispatcher import
    # run_once`, and run_once closes over `deliver` in its own module, so
    # stubbing dispatcher.deliver is the correct target -- but the stub must
    # survive the server being built, which imports run_once at module load.
    original = dispatcher_module.deliver
    dispatcher_module.deliver = lambda *a, **k: (calls.append(1), (True, 200, "ok"))[1]

    import webhooks.server as server_module
    server_module.verify_endpoint = lambda url, secret, config, now=None: (True, "ok")
    server, client, _ = _start(tmp_path)
    try:
        created = client.request("POST", "/api/v1/subscriptions",
                                 {"url": "https://hooks.example.com/in"},
                                 headers={"X-Real-IP": "7.7.7.7"})
        assert created[0] == 201, created
        status, stats = client.request("POST", "/api/v1/dispatch", token=ADMIN)
        assert status == 200
        assert stats["queued"] == 1, stats
        assert stats["delivered"] == 1, stats
        assert len(calls) == 1
    finally:
        server.shutdown()
        dispatcher_module.deliver = original


def test_health_reflects_queue_depth(tmp_path):
    import webhooks.dispatcher as dispatcher_module
    (tmp_path / "events.json").write_text(
        json.dumps([{"id": "e1", "event": "model.became_paid", "at": "t"}]), encoding="utf-8")
    original = dispatcher_module.deliver
    dispatcher_module.deliver = lambda *a, **k: (False, 500, "HTTP 500")

    import webhooks.server as server_module
    server_module.verify_endpoint = lambda url, secret, config, now=None: (True, "ok")
    server, client, _ = _start(tmp_path)
    try:
        client.request("POST", "/api/v1/subscriptions",
                       {"url": "https://hooks.example.com/in"})
        client.request("POST", "/api/v1/dispatch", token=ADMIN)
        _status, health = client.request("GET", "/api/v1/health")
        assert health["pending"] == 1
        assert health["subscriptions"] == 1
    finally:
        server.shutdown()
        dispatcher_module.deliver = original
