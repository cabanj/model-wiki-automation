"""Configuration for the webhook service.

Every value comes from the environment so nothing secret lives in the
repository. Defaults are deliberately strict: this process posts to
attacker-supplied URLs, so the safe setting has to be the one you get for
free.
"""

import os


def _int(env, name, default):
    try:
        return int(env.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool(env, name, default):
    return str(env.get(name, default)).strip().lower() in ("1", "true", "yes", "on")


def _int_list(env, name, default):
    raw = env.get(name)
    if not raw:
        return list(default)
    values = []
    for part in str(raw).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            continue
    return values or list(default)


class Config:
    """Resolved once at startup; read-only afterwards."""

    def __init__(self, env=None):
        # Read the passed mapping when given, never os.environ directly: the
        # earlier version accepted `env` and then ignored it, so every caller
        # that passed overrides silently got the production defaults.
        env = env if env is not None else os.environ
        self.db_path = env.get("ROSTER_WEBHOOK_DB", "/var/lib/roster-webhooks/webhooks.db")
        self.events_path = env.get("ROSTER_WEBHOOK_EVENTS", "/opt/model-wiki-automation/data/events.json")
        # Admin token guards subscription management. It is a secret, but a
        # single shared one: per-subscriber keys would be a second auth system
        # for a service that already proves endpoint ownership by challenge.
        self.admin_token = env.get("ROSTER_WEBHOOK_ADMIN_TOKEN", "")
        self.bind_host = env.get("ROSTER_WEBHOOK_BIND", "127.0.0.1")
        self.bind_port = _int(env, "ROSTER_WEBHOOK_PORT", 8090)

        # A challenge must complete fast: a slow endpoint is a bad endpoint,
        # and a long timeout would let one client tie up a worker.
        self.verify_timeout = _int(env, "ROSTER_WEBHOOK_VERIFY_TIMEOUT", 5)
        self.verify_attempts = _int(env, "ROSTER_WEBHOOK_VERIFY_ATTEMPTS", 2)

        self.deliver_timeout = _int(env, "ROSTER_WEBHOOK_DELIVER_TIMEOUT", 10)
        self.max_attempts = _int(env, "ROSTER_WEBHOOK_MAX_ATTEMPTS", 5)
        # Backoff in seconds per attempt; the last entry repeats. Parsed from
        # the environment so tests and operators can shorten it without
        # touching code.
        self.backoff = _int_list(env, "ROSTER_WEBHOOK_BACKOFF",
                                 [60, 300, 1800, 7200, 21600])
        # Consecutive dead deliveries before a subscription is disabled. A
        # subscription that has failed this many times is not "temporarily
        # unhappy", it is abandoned, and retrying it forever is an outage we
        # cause.
        self.disable_after_failures = _int(env, "ROSTER_WEBHOOK_DISABLE_AFTER", 10)

        # Abuse ceilings. The per-IP subscription cap matters more than the
        # request rate: a client behind one NAT must not be able to exhaust
        # the delivery budget for everyone else.
        self.max_subscriptions_per_ip = _int(env, "ROSTER_WEBHOOK_MAX_SUBS_PER_IP", 5)
        self.max_subscriptions_total = _int(env, "ROSTER_WEBHOOK_MAX_SUBS_TOTAL", 1000)
        self.max_bytes = _int(env, "ROSTER_WEBHOOK_MAX_BYTES", 1 << 20)

        # Keep the delivery queue bounded; undeliverable rows are pruned once
        # dead so the table cannot grow without limit.
        self.delivery_retention_hours = _int(env, "ROSTER_WEBHOOK_DELIVERY_RETENTION_H", 168)
        # Set true only in tests: allows http:// and loopback targets.
        self.allow_private_targets = _bool(env, "ROSTER_WEBHOOK_ALLOW_PRIVATE", False)

    def backoff_for(self, attempt):
        """Seconds to wait before `attempt` (1-based). Repeats the last value."""
        if not self.backoff:
            return 0
        index = min(max(attempt - 1, 0), len(self.backoff) - 1)
        return self.backoff[index]
