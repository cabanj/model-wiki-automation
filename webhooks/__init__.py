"""Webhook delivery service for llmroster.dev.

Runs as two independent processes sharing one SQLite file:
  - the API (subscriptions) and the dispatcher (deliveries) are separate so a
    slow delivery can never delay a registration.
"""

from .config import Config  # noqa: F401
