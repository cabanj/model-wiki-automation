#!/usr/bin/env python3
"""Static API reference page: dist/api.html.

Kept apart from legal.py because this page is partly derived: the field tables
are generated from the same constants the payload and the delivery code use
(`api.BENCH_FIELDS`, `events.EVENT_TYPES`, `webhooks.signing`). A hand-written
table would rot silently the first time a field was renamed, and a docs page
that lies is worse than no docs page.

Prose is hand-written. Field names, event types and header names are not.
"""

import json

import events
from api import SCHEMA_VERSION
from render import esc, page, site_url, table
from sources.common import PROVIDER_BASE_URLS

ENDPOINTS = {
    "roster": "/api/v1/roster.json",
    "subscriptions": "/api/v1/subscriptions",
}

# A real event record, in the shape `events.py` writes to data/events.json.
# `build_payload_example()` feeds this to the real signer, so the documented
# example cannot drift from what a subscriber actually receives.
EXAMPLE_EVENT = {
    "id": "3f9c1a7be2d04c85",
    "event": "model.became_paid",
    "at": "2026-09-29T18:00:00Z",
    "model_id": "z-ai/glm-5.2",
    "name": "GLM 5.2",
    "source": "openrouter",
    "pricing": {"prompt": 4e-07, "completion": 1.1e-06},
    "last_seen_free": "2026-09-20T00:00:00Z",
}

# Field reference for the roster payload. `type` is what a client should expect;
# `null` is called out explicitly where that is a legitimate value.
MODEL_FIELDS = [
    ("id", "string", "Normalized model id: lowercase, no trailing <code>:free</code> / <code>-free</code>. Stable across runs and the join key for everything else."),
    ("display_id", "string", "The id as one provider reports it, so it is directly callable on at least one endpoint."),
    ("name", "string", "Display name."),
    ("description", "string", "Provider-supplied summary. May be empty on Zen, which has no descriptions of its own."),
    ("free_basis", "string", "<code>price-0</code>, <code>zen-free</code> or <code>zen-micro</code>. Micro-priced Zen models are labelled, never presented as $0."),
    ("sources", "string[]", "Which sources confirm the model free."),
    ("context_length", "integer | null", "Maximum context in tokens, or <code>null</code> when no source publishes it."),
    ("modalities", "string", "Input/output modalities, e.g. <code>text+image+video-&gt;text</code>."),
    ("tools", "boolean", "Whether tool/function calling is advertised."),
    ("endpoints", "object[]", "Callable endpoints. See below."),
    ("benchmarks", "object", "Artificial Analysis scores. See below."),
]

ENDPOINT_FIELDS = [
    ("provider", "string", "One of the sources above."),
    ("base_url", "string", "OpenAI-compatible base URL."),
    ("model_id", "string", "The id to send on that provider. Not the normalized id &mdash; providers prefix and suffix differently, so the normalized form is often not callable."),
]

TOP_LEVEL_FIELDS = [
    ("schema_version", "integer", f"Currently <code>{SCHEMA_VERSION}</code>. Check this before parsing."),
    ("generated_at", "string", "ISO 8601 UTC. Refreshed once a day by the pipeline."),
    ("counts", "object", "<code>models</code> and <code>sources</code>."),
    ("sources", "object", "Per-source health for the run: <code>ok</code>, <code>count</code>, <code>error</code>. A failing source degrades the roster rather than failing the build."),
    ("models", "object[]", "The roster. See below."),
]

BENCHMARK_NOTES = {
    "matched": "Whether an Artificial Analysis record was matched to this model. <code>false</code> means no score at all, not a zero.",
    "paid_proxy": "The matched AA record is the paid variant of the same model, so the score is indicative rather than a free-tier measurement.",
    "excluded": "The model is in <code>BENCH_EXCLUDE</code>: matched but deliberately kept out of rankings because it is known-broken. The score is still reported.",
}


def build_payload_example():
    """Render the delivery payload with the real signer, not a hand-written blob.

    Passing EXAMPLE_EVENT through unchanged is the point: if the signer's
    output shape ever changes, the documented example changes with it instead
    of quietly going stale.
    """
    from webhooks.signing import build_payload
    return build_payload(EXAMPLE_EVENT)


def _json_block(text):
    return f'<pre class="code-block"><code>{esc(text)}</code></pre>'


def _field_table(rows, caption):
    return table(["Field", "Type", "Meaning"],
                 [[f"<code>{esc(name)}</code>", f"<code>{esc(kind)}</code>", meaning]
                  for name, kind, meaning in rows],
                 caption=caption, row_header=0)


def _bench_table():
    from api import BENCH_FIELDS
    rows = [
        ["<code>source</code>", "<code>string</code>", "Always <code>artificial-analysis</code>."],
        ["<code>matched</code>", "<code>boolean</code>", BENCHMARK_NOTES["matched"]],
        ["<code>aa_name</code>", "<code>string</code>", "Name of the matched Artificial Analysis record, when any."],
        ["<code>paid_proxy</code>", "<code>boolean</code>", BENCHMARK_NOTES["paid_proxy"]],
        ["<code>excluded</code>", "<code>boolean</code>", BENCHMARK_NOTES["excluded"]],
    ]
    for public, _raw in BENCH_FIELDS:
        rows.append([f"<code>{esc(public)}</code>", "<code>number | null</code>",
                     "<code>null</code> when the dataset has no value for this field."])
    return table(["Field", "Type", "Meaning"], rows,
                 caption="benchmarks object, per model", row_header=0)


def _event_table():
    descriptions = {
        "model.became_paid": "The model was free and now is not. Fires once per transition; a model that stays paid does not repeat.",
        "model.added": "A model joined the roster, with the endpoints it is callable on.",
        "model.removed": "A model left the roster. <code>cause</code> is <code>no_longer_free</code>. Removals caused by a source outage are suppressed, not reported.",
        "endpoint.added": "An already-listed model became callable on another provider.",
    }
    rows = []
    for event_type in events.EVENT_TYPES:
        if event_type not in descriptions:
            raise KeyError(f"event type {event_type} is undocumented in api.html; "
                           "add it rather than shipping an undocumented contract")
        rows.append([f"<code>{esc(event_type)}</code>", descriptions[event_type]])
    return table(["Type", "When it fires"], rows,
                 caption="Event types accepted in the events[] filter", row_header=0)


def _curl_examples():
    roster = site_url(ENDPOINTS["roster"].lstrip("/"))
    subs = site_url(ENDPOINTS["subscriptions"].lstrip("/"))
    return (
        "<h3>Fetch the roster</h3>"
        + _json_block(f"curl {roster}")
        + "<p>Anonymous, no key, no parameters. Conditional requests work: send "
          "<code>If-None-Match</code> with the <code>ETag</code> from the previous "
          "response and a changed roster costs you a 304 instead of the full body.</p>"
        + "<h3>Subscribe to changes</h3>"
        + _json_block("\n".join([
            f"curl -X POST {subs} \\",
            "  -H 'Content-Type: application/json' \\",
            "  -d '{\"url\": \"https://example.com/hooks/llmroster\","
            " \"events\": [\"model.became_paid\"]}'",
        ]))
        + "<p>Registration is open &mdash; there is no API key. What stands in for one is "
          "proof that you control the endpoint: we POST a challenge and require your "
          "endpoint to return it. A URL that answers everything with <code>200</code> "
          "is rejected, because that is what a relay target looks like.</p>"
    )


def _signature_section():
    from webhooks.signing import (DELIVERY_HEADER, EVENT_HEADER, SIGNATURE_HEADER,
                                  TIMESTAMP_HEADER)
    body = build_payload_example()
    return (
        "<h2>Verifying a delivery</h2>"
        "<p>Every delivery is signed. Compute the signature over the timestamp and the "
        "body exactly as received &mdash; the timestamp is inside the signed material, so a "
        "captured delivery cannot be replayed with a fresh one.</p>"
        + _json_block("expected = \"sha256=\" + hmac.new(\n"
                      "    secret.encode(),\n"
                      "    timestamp.encode() + b\".\" + body_bytes,\n"
                      "    hashlib.sha256).hexdigest()")
        + "<p>Use <code>hmac.compare_digest</code> rather than <code>==</code> to compare. "
        "Reject anything whose timestamp is older than a few minutes.</p>"
        + _json_block("\n".join([
            f"{EVENT_HEADER}: model.became_paid",
            f"{TIMESTAMP_HEADER}: 1790714400",
            f"{DELIVERY_HEADER}: 42",
            f"{SIGNATURE_HEADER}: sha256=...",
        ]))
        + "<p><code>X-Roster-Delivery</code> is the id of the delivery attempt and is useful "
          "for deduplicating on your side: one event can be delivered more than once if a "
          "retry happens.</p>"
    )


def _payload_section():
    body = build_payload_example()
    return (
        "<h2>What a delivery looks like</h2>"
        + _json_block(body)
        + "<p><code>data</code> carries the fields relevant to the event type. "
          "<code>model.became_paid</code> includes <code>pricing</code>, which is the "
          "observed price that caused the transition.</p>"
    )


def _limits_section():
    return (
        "<h2>Limits and rules</h2>"
        "<ul>"
        "<li><strong>Reads are anonymous and rate limited</strong> to 30 requests per "
        "minute per address, with a burst. Exceeding it returns <code>503</code>, not "
        "<code>429</code>, so it is not confused with a rate-limit page from a proxy in "
        "front of the site.</li>"
        "<li><strong>Registration is limited to 10 requests per minute per address</strong> "
        "and to 5 active subscriptions per address, because each attempt costs us an "
        "outbound request to your endpoint.</li>"
        "<li><strong>Endpoints must be <code>https</code></strong> and publicly routable. "
        "Loopback, private ranges, cloud metadata addresses and IPv4-mapped IPv6 forms of "
        "them are refused.</li>"
        "<li><strong>Retries are bounded.</strong> A delivery is retried with backoff, and "
        "a subscription that keeps failing is disabled rather than retried forever.</li>"
        "</ul>"
    )


def build_body():
    roster_url = site_url(ENDPOINTS["roster"].lstrip("/"))
    subs_url = site_url(ENDPOINTS["subscriptions"].lstrip("/"))
    providers = "".join(
        f"<li><code>{esc(name)}</code> &mdash; <code>{esc(url)}</code></li>"
        for name, url in sorted(PROVIDER_BASE_URLS.items()))

    return f'''<div class="page-body">
<section class="page-head">
  <span class="eyebrow">Developer API</span>
  <h1>API &amp; webhooks</h1>
  <p class="lead">The roster is available as JSON, and changes can be pushed to an
  endpoint you control. No account, no API key, no signup. The data is the same data
  behind the tables on this site, refreshed once a day.</p>
</section>

<div class="metric-strip" aria-label="API summary">
  <div class="metric"><span class="metric-label">Roster</span><strong class="metric-value">GET</strong><span class="metric-note">no key required</span></div>
  <div class="metric"><span class="metric-label">Schema</span><strong class="metric-value">v{SCHEMA_VERSION}</strong><span class="metric-note">check before parsing</span></div>
  <div class="metric"><span class="metric-label">Events</span><strong class="metric-value">{len(events.EVENT_TYPES)}</strong><span class="metric-note">delivered per model</span></div>
</div>

<section>
{_curl_examples()}
</section>

<h2>What the roster returns</h2>
<p>The payload is derived from the same snapshot as this site, so it cannot drift from
the tables. <code>generated_at</code> tells you how fresh it is.</p>
{_field_table(TOP_LEVEL_FIELDS, "Top-level fields")}
{_field_table(MODEL_FIELDS, "Each entry in models[]")}

<h3>endpoints</h3>
<p>A model can be callable on more than one provider, and the id differs between them.
Use <code>endpoints[].model_id</code> with <code>endpoints[].base_url</code> rather than
assuming the normalized <code>id</code> works everywhere.</p>
{_field_table(ENDPOINT_FIELDS, "Each entry in endpoints[]")}
<p>Known base URLs:</p>
<ul>{providers}</ul>

<h3>benchmarks</h3>
{_bench_table()}

<h2>Webhooks</h2>
<p>A webhook is an HTTPS endpoint we POST to when something changes. You choose the
event types; each event is delivered per model rather than as a batch.</p>
{_event_table()}
{_payload_section()}
{_signature_section()}
{_limits_section()}

<h2>Verifying you control an endpoint</h2>
<p>Before a subscription is created we POST a challenge containing a random token in the
<code>X-Roster-Challenge</code> header. Your endpoint must return <code>2xx</code> and
include that token in the response body. This is what stops our service being used to
send unwanted traffic to an address you do not control.</p>
{_json_block(json.dumps({
    "type": "endpoint.verification",
    "challenge": "<token sent in X-Roster-Challenge>",
}, indent=2))}
<p>A response of <code>200</code> that does not echo the token is refused. If you need the
challenge and a real delivery to be distinguishable, the presence of the header tells
them apart.</p>

<blockquote>The secret is returned exactly once, in the <code>201</code> response to
registration. It is not sent again and not recoverable afterwards. Store it before you
discard the response.</blockquote>

<p>Questions or corrections: <a href="contact.html">contact page</a>.</p>
</div>'''


def render_api(generated_at):
    return page("API", "api.html", build_body(), generated_at)