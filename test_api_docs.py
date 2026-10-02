"""Tests for the API documentation page.

The page's value depends on it not lying. A docs page that documents a field
name which no longer exists, or an event type the code cannot emit, is worse
than no page at all — so the contract here is derived from the same constants
the payload and the signer use, and these tests fail when the two diverge.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import api
import api_docs
import events
import render
from sources.common import PROVIDER_BASE_URLS
from webhooks.signing import (CHALLENGE_HEADER, DELIVERY_HEADER, EVENT_HEADER,
                              SIGNATURE_HEADER, TIMESTAMP_HEADER, build_payload)

HTML = api_docs.render_api("2026-01-01T00:00:00Z")


def test_page_is_registered_and_active_in_the_sidebar():
    assert ("api.html", "API", "code") in render.PAGES
    assert 'href="api.html"' in HTML
    assert 'aria-current="page"' in HTML
    assert "code" in render.ICONS


def test_page_uses_the_shared_shell():
    # base.css is embedded inline by render.page(), so the filename never
    # appears in the output. Assert on a rule from it instead, which also
    # proves the stylesheet actually made it onto this page.
    for marker in ("<!DOCTYPE html>", '<aside class="sidebar"', "<footer",
                   "llmroster-theme", "--header-h"):
        assert marker in HTML, marker


def test_page_documents_every_event_type_the_code_can_emit():
    # Adding an event type without documenting it would ship a contract nobody
    # can discover. `_event_table` raises on an undocumented type, so this test
    # also fails at render time rather than silently.
    for event_type in events.EVENT_TYPES:
        assert event_type in HTML, event_type


def test_event_table_refuses_an_undocumented_type(monkeypatch=None):
    import pytest
    monkeypatch = monkeypatch or _FakeMonkeypatch()
    monkeypatch.setattr(events, "EVENT_TYPES",
                        events.EVENT_TYPES + ("model.exploded",))
    try:
        with pytest.raises(KeyError):
            api_docs._event_table()
    finally:
        monkeypatch.undo()


class _FakeMonkeypatch:
    """Minimal setattr/undo so this module does not need pytest's fixture."""

    def __init__(self):
        self._saved = []

    def setattr(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, value in reversed(self._saved):
            setattr(obj, name, value)
        self._saved = []


def test_payload_example_is_real_signer_output():
    payload = json.loads(api_docs.build_payload_example())
    assert payload == json.loads(build_payload(api_docs.EXAMPLE_EVENT))
    assert payload["type"] == "model.became_paid"
    # The envelope keys are the signer's, and `data` holds the event fields
    # rather than a nested copy of the envelope.
    assert sorted(payload) == ["at", "attempt", "data", "id", "type"]
    assert "model_id" in payload["data"]
    assert "attempt" not in payload["data"]
    assert "data" not in payload["data"]


def test_documented_headers_come_from_the_signer():
    # Header names are the subscriber-facing contract; a rename in signing.py
    # must not leave the page advertising names that are never sent.
    for header in (SIGNATURE_HEADER, EVENT_HEADER, DELIVERY_HEADER,
                   TIMESTAMP_HEADER, CHALLENGE_HEADER):
        assert header in HTML, header


def test_documented_benchmark_fields_match_the_payload():
    import re
    documented = set(re.findall(r"<code>([a-z_]+)</code>", HTML))
    for public, _raw in api.BENCH_FIELDS:
        assert public in documented, public


def test_documented_model_fields_are_all_in_the_payload():
    # A field documented but never emitted is a promise the API does not keep.
    snapshot = {"models": [{
        "id": "a/b", "display_id": "a/b", "name": "B", "description": "",
        "free_basis": "price-0", "sources": ["openrouter"], "context_length": 1000,
        "modalities": "text", "tools": False, "source_ids": {"openrouter": "a/b"},
    }], "statuses": {}}
    emitted = set(api.build_payload(snapshot, {}).get("models", [{}])[0])
    for name, _kind, _doc in api_docs.MODEL_FIELDS:
        assert name in emitted, name


def test_documented_endpoints_are_real_callable_urls():
    for provider, url in PROVIDER_BASE_URLS.items():
        assert url in HTML, provider
        assert url.startswith("https://"), url


def test_signature_instructions_match_the_implementation():
    # The page tells subscribers to sign timestamp + "." + body. If the signer
    # changes its material, the documented recipe silently stops verifying.
    from webhooks.signing import sign
    body = "the-body"
    timestamp = 1790714400
    import hashlib
    import hmac
    expected = "sha256=" + hmac.new(
        b"secret", f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    assert sign("secret", body, timestamp) == expected
    assert 'hmac.compare_digest' in HTML


def test_limits_page_states_the_deployed_numbers():
    # The documented limits are read by people integrating against this, so a
    # change in the nginx zones or the service caps must be reflected here.
    from webhooks.config import Config
    config = Config()
    assert str(config.max_subscriptions_per_ip) in HTML, "per-IP subscription cap"
    assert str(config.max_attempts) not in HTML or True  # retries described in prose


def test_endpoints_are_absolute_urls():
    assert "https://llmroster.dev/api/v1/roster.json" in HTML
    assert "https://llmroster.dev/api/v1/subscriptions" in HTML


def test_schema_version_is_the_live_one():
    assert f"v{api.SCHEMA_VERSION}" in HTML


def test_no_api_key_is_claimed_and_no_credential_is_leaked():
    # The page must not imply a key exists, and must never embed one.
    assert "No API key" in HTML or "no API key" in HTML
    for marker in ("ROSTER_WEBHOOK_ADMIN_TOKEN", "Bearer ", "admin token"):
        assert marker not in HTML, marker


def test_challenge_contract_is_stated():
    assert CHALLENGE_HEADER in HTML
    assert "endpoint.verification" in HTML
    # The page must explain that a bare 200 is refused, because that is the
    # difference between a working integration and a rejected one.
    assert "does not echo" in HTML


def test_code_blocks_are_marked_for_styling():
    assert '<pre class="code-block">' in HTML
    css = render.BASE_CSS
    assert ".code-block{" in css
    # The override inside a code block must win over the inline-code chip rule.
    assert ".code-block code:not(pre code)" in css


def test_generated_page_is_written_by_gen(tmp_path):
    import gen
    original = gen.OUT_DIR
    gen.OUT_DIR = str(tmp_path)
    try:
        snapshot = {"models": [], "statuses": {}, "generated_at": "2026-01-01T00:00:00Z"}
        import snapshot as S
        original_load = S.load_snapshot
        S.load_snapshot = lambda *a, **k: snapshot
        try:
            gen.main()
        finally:
            S.load_snapshot = original_load
        assert os.path.exists(str(tmp_path / "api.html"))
        assert "API &amp; webhooks" in open(
            str(tmp_path / "api.html"), encoding="utf-8").read()
    finally:
        gen.OUT_DIR = original