"""HTTP API for subscriptions. stdlib only, bound to loopback.

Routes:
    GET    /api/v1/health            liveness + queue depth (no auth)
    POST   /api/v1/subscriptions     register; proves endpoint ownership
    GET    /api/v1/subscriptions     list (admin)
    DELETE /api/v1/subscriptions/<id>  remove (admin)
    POST   /api/v1/dispatch          run one delivery pass (admin)

`/api/v1/roster.json` is NOT served here. It is a static file behind nginx,
already rate limited and CORS-enabled; duplicating it in the service would
create a second contract to keep in sync.
"""

import json
import re
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import store
from .config import Config
from .dispatcher import run_once
from .signing import new_id, new_secret, verify_endpoint
from .urls import InvalidTarget, validate_url

EVENT_TYPES = ("model.became_paid", "model.added", "model.removed", "endpoint.added")
SUBSCRIPTION_ID = re.compile(r"^[0-9a-f]{16}$")


def _log_exception(message, error):
    """Print the real traceback to stderr; the client only ever sees `message`.

    An unhandled-exception path that returns a bare 500 with no log is
    undiagnosable once the process is a systemd unit, so the detail goes to the
    journal and the response stays generic.
    """
    traceback.print_exc()
    print(f"webhook api: {message}: {type(error).__name__}: {error}", file=sys.stderr, flush=True)


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "roster-webhooks/1.0"
    protocol_version = "HTTP/1.1"
    config = None

    # --- plumbing ----------------------------------------------------------

    def log_message(self, fmt, *args):
        # Suppress the default stderr access log; the service logs its own
        # structured lines and the admin token must never land in one.
        return

    @property
    def db(self):
        # Per-thread connection: ThreadingHTTPServer gives every request a new
        # thread and SQLite connections cannot cross threads.
        return store.thread_connection(self.config.db_path)

    def _client_ip(self):
        # The service binds to loopback, so the socket peer is always the local
        # nginx proxy. Real attribution comes from X-Real-IP, which nginx sets
        # from the restored client address. Trusted because nothing but nginx
        # can reach this port.
        return self.headers.get("X-Real-IP", self.client_address[0])

    def _authorised(self):
        if not self.config.admin_token:
            return False
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        # Constant-time compare: a timing side channel on a shared secret is
        # cheap to close and this is the only auth in the service.
        import hmac as _hmac
        return _hmac.compare_digest(header[7:].strip(), self.config.admin_token)

    def _require_admin(self):
        if not self._authorised():
            raise ApiError(401, "admin bearer token required")

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ApiError(400, "request body required")
        if length > self.config.max_bytes:
            raise ApiError(413, "request body too large")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "body is not valid JSON")

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # No CORS here: this API is for server-to-server use and the public
        # roster is served statically by nginx with its own permissive headers.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._send(status, {"error": message})

    # --- routes ------------------------------------------------------------

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if path == "/api/v1/health":
                return self._send(200, {
                    "ok": True,
                    "subscriptions": store.count_subscriptions(self.db),
                    "pending": store.pending_count(self.db),
                    "dead": store.dead_count(self.db),
                })
            if path == "/api/v1/subscriptions":
                self._require_admin()
                rows = store.list_subscriptions(self.db)
                for row in rows:
                    # Never echo a secret, not even to the admin.
                    row.pop("secret", None)
                return self._send(200, {"subscriptions": rows})
            raise ApiError(404, "not found")
        except ApiError as error:
            self._error(error.status, error.message)
        except Exception as error:  # pragma: no cover - defensive
            _log_exception("unhandled error in request", error)
            self._error(500, "internal error")

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            if path == "/api/v1/subscriptions":
                return self._create_subscription()
            if path == "/api/v1/dispatch":
                self._require_admin()
                return self._send(200, run_once(self.db, self.config))
            raise ApiError(404, "not found")
        except ApiError as error:
            self._error(error.status, error.message)
        except Exception as error:  # pragma: no cover - defensive
            _log_exception("unhandled error in request", error)
            self._error(500, "internal error")

    def do_DELETE(self):
        try:
            path = urlparse(self.path).path
            match = re.fullmatch(r"/api/v1/subscriptions/([0-9a-f]{16})", path)
            if not match:
                raise ApiError(404, "not found")
            self._require_admin()
            removed = store.delete_subscription(self.db, match.group(1))
            if not removed:
                raise ApiError(404, "no such subscription")
            return self._send(200, {"deleted": match.group(1)})
        except ApiError as error:
            self._error(error.status, error.message)
        except Exception as error:  # pragma: no cover - defensive
            _log_exception("unhandled error in request", error)
            self._error(500, "internal error")

    def _create_subscription(self):
        # Open registration: the abuse ceiling here is the per-IP cap plus the
        # ownership challenge, not a key. A key would add friction without
        # preventing a relay, which is the actual risk.
        body = self._read_json()
        url = body.get("url")
        requested = body.get("events") or ["*"]
        if not isinstance(requested, list) or not all(isinstance(e, str) for e in requested):
            raise ApiError(400, "events must be a list of strings")
        unknown = [e for e in requested if e != "*" and e not in EVENT_TYPES]
        if unknown:
            raise ApiError(400, f"unknown event types: {', '.join(sorted(unknown))}")

        try:
            validate_url(url, allow_private=self.config.allow_private_targets)
        except InvalidTarget as error:
            raise ApiError(400, str(error))

        ip = self._client_ip()
        if store.count_for_ip(self.db, ip) >= self.config.max_subscriptions_per_ip:
            raise ApiError(429, "subscription limit reached for this address")
        if store.count_subscriptions(self.db) >= self.config.max_subscriptions_total:
            raise ApiError(503, "service is at capacity")

        secret = new_secret()
        ok, detail = verify_endpoint(url, secret, self.config)
        if not ok:
            # The caller cannot prove they control the URL, so we do not create
            # the subscription and never store the secret.
            raise ApiError(400, f"endpoint verification failed: {detail}")

        subscription_id = new_id()
        store.create_subscription(self.db, subscription_id, url,
                                  requested, secret, ip, time.time())
        return self._send(201, {
            "id": subscription_id,
            "url": url,
            "events": requested,
            # Returned exactly once. The service stores it and can re-derive
            # signatures, but never sends it again.
            "secret": secret,
            "verified": detail,
        })


def serve(config=None, connection=None):
    config = config or Config()
    store.init_db(config.db_path)
    connection = connection or store.connect(config.db_path)

    handler = type("BoundHandler", (Handler,), {"config": config})
    server = ThreadingHTTPServer((config.bind_host, config.bind_port), handler)
    server.daemon_threads = True
    return server
