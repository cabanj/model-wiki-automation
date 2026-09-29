"""HMAC signing and the ownership challenge.

Two separate jobs live here because they answer different questions:

- `sign` answers "did this really come from llmroster.dev?". The subscriber
  holds the secret, so a forged payload cannot produce a valid signature.
- `verify_endpoint` answers "does the person registering this URL actually
  control it?". This is what stops the service being used as a relay against
  someone else's address. A 2xx alone is not enough for the relay case, so the
  challenge additionally requires the endpoint to echo a random token: that
  proves the response came from an endpoint that read our request, not from a
  blanket catch-all that returns 200 to everything.
"""

import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.request

from .urls import validate_url

SIGNATURE_HEADER = "X-Roster-Signature"
EVENT_HEADER = "X-Roster-Event"
DELIVERY_HEADER = "X-Roster-Delivery"
TIMESTAMP_HEADER = "X-Roster-Timestamp"
CHALLENGE_HEADER = "X-Roster-Challenge"
USER_AGENT = "llmroster-webhooks/1.0"


def new_secret():
    """A per-subscription signing secret. Returned once, never stored in clear
    in a log, and never re-sent after creation."""
    return secrets.token_hex(32)


def new_id():
    return secrets.token_hex(8)


def new_challenge_token():
    return secrets.token_urlsafe(24)


def sign(secret, body, timestamp):
    """`sha256=<hex>` over `timestamp.body`.

    The timestamp is inside the signed material, not just a header, so a
    captured delivery cannot be replayed later with a fresh timestamp.
    """
    if isinstance(body, str):
        body = body.encode("utf-8")
    material = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_payload(event, attempt=1):
    """The JSON body a subscriber receives.

    Only public roster facts: there is nothing here about the subscriber, and
    nothing here that is not already on the site or in the public API.
    """
    return json.dumps({
        "id": event.get("id"),
        "type": event.get("event"),
        "at": event.get("at"),
        "attempt": attempt,
        "data": {k: v for k, v in event.items() if k not in ("id", "event", "at")},
    }, ensure_ascii=False, sort_keys=True)


def _post(url, body, headers, timeout, allow_private):
    request = urllib.request.Request(url, data=body, method="POST")
    for name, value in headers.items():
        request.add_header(name, value)
    # No redirect following: a 30x to an internal address would bypass the
    # target validation we just did on the original URL.
    opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(request, timeout=timeout)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify_endpoint(url, secret, config, now=None):
    """Prove the caller controls `url`. Returns (ok, detail).

    Success requires a 2xx that echoes the challenge token. A plain 2xx with
    the wrong body is treated as a failure on purpose: that is the shape of a
    URL that answers everything with 200, which is exactly the relay case.
    """
    try:
        validate_url(url, allow_private=config.allow_private_targets)
    except Exception as error:
        return False, str(error)

    token = new_challenge_token()
    body = json.dumps({"type": "endpoint.verification", "challenge": token})
    headers = {
        "Content-Type": "application/json",
        CHALLENGE_HEADER: token,
        SIGNATURE_HEADER: sign(secret, body, int(now or time.time())),
        "User-Agent": USER_AGENT,
    }

    detail = ""
    for attempt in range(1, max(1, config.verify_attempts) + 1):
        try:
            with _post(url, body.encode("utf-8"), headers,
                       config.verify_timeout, config.allow_private_targets) as response:
                status = response.status
                payload = response.read(config.max_bytes).decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            status = error.code
            payload = ""
            detail = f"HTTP {status}"
        except Exception as error:
            status = 0
            payload = ""
            detail = f"{type(error).__name__}: {error}"

        if 200 <= status < 300 and token in payload:
            return True, f"verified with HTTP {status}"
        if not detail:
            detail = f"HTTP {status} (challenge token not echoed)"
    return False, detail or "verification failed"


def deliver(url, secret, event, config, delivery_id, attempt, now=None):
    """One delivery attempt. Returns (ok, status_code, detail)."""
    body = build_payload(event, attempt=attempt)
    timestamp = int(now or time.time())
    headers = {
        "Content-Type": "application/json",
        EVENT_HEADER: event.get("event", ""),
        DELIVERY_HEADER: delivery_id,
        TIMESTAMP_HEADER: str(timestamp),
        SIGNATURE_HEADER: sign(secret, body, timestamp),
        "User-Agent": USER_AGENT,
    }
    try:
        with _post(url, body.encode("utf-8"), headers,
                   config.deliver_timeout, config.allow_private_targets) as response:
            response.read(config.max_bytes)
            status = response.status
        if 200 <= status < 300:
            return True, status, "ok"
        # 4xx other than 408/429 is a permanent refusal: a malformed URL or a
        # revoked subscription will not start working on retry.
        if 400 <= status < 500 and status not in (408, 429):
            return False, status, f"permanent HTTP {status}"
        return False, status, f"HTTP {status}"
    except urllib.error.HTTPError as error:
        status = error.code
        if 400 <= status < 500 and status not in (408, 429):
            return False, status, f"permanent HTTP {status}"
        return False, status, f"HTTP {status}"
    except Exception as error:
        return False, 0, f"{type(error).__name__}: {error}"
