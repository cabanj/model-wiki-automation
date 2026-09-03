#!/usr/bin/env python3
"""model-wiki generator: fetch all sources -> diff vs snapshot -> render HTML pages."""

import os
import sys
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources import collect_all
from sources.common import normalize_id, is_junk
import snapshot as S
from render import page, table, model_rows, esc, fmt_ts

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")

# Use-case role heuristics: keyword -> (role label, priority for sorting within use case)
USE_CASES = [
    ("Deep reasoning / research", ["reasoning", "ultra", "thinking", "r1", "nemotron-3-ultra"]),
    ("Agentic coding", ["cod", "laguna", "devstral"]),
    ("Long-context work", ["longcat"]),
    ("Vision / multimodal", ["vision", "omni", "vl-", "-vl", "gemma"]),
    ("Fast / lightweight", ["lightning", "flash", "nano", "mini", "lfm"]),
    ("General purpose fallback", []),
]


def assign_role(m):
    hay = m["id"].lower() + " " + m.get("description", "").lower()[:200]
    for role, kws in USE_CASES:
        if any(k in hay for k in kws):
            return role
    return USE_CASES[-1][0]


def sort_models(models):
    """Group by primary provider (source), then by model name."""
    def primary_source(m):
        order = {"nous": 0, "opencode-zen": 1, "openrouter": 2}
        return min(order.get(s, 9) for s in m["sources"])
    return sorted(models, key=lambda m: (primary_source(m),
                                         (m.get("name") or m["id"]).lower()))


def render_ranking(models, generated_at):
    models = sort_models(models)
    headers = ["Sources", "Model ID", "Name", "", "Context", "Modalities", "Description"]
    body = f"""
<section class="page-head"><h1>Free Models — Ranked by Use Case</h1>
<p class="lead">Strictly free models only (<strong>price&nbsp;==&nbsp;0</strong>, no micro-pricing).
Auto-discovered from <strong>OpenRouter, Nous Portal and OpenCode Zen</strong> on every refresh.
New free models appear automatically; stale ones are removed.</p></section>
<p class="src-note">{len(models)} free models confirmed by at least one source · badges: $0 = verified zero pricing, zen free = limited-time OpenCode Zen roster, in-plan = $0 within a subscription plan</p>
{table(headers, model_rows(models))}"""
    return page("Free Models — Ranked by Use Case",
                "comparisons-free-models-ranking.html", body, generated_at)


ROUTER_CHANGELOG_PATH = "/opt/hermes-router/data/changelog.json"

ALIAS_LABELS = {
    "free-general": "General",
    "free-fast": "Fast",
    "free-coding": "Coding",
    "free-fallback": "Fallback",
}


def load_router_changelog():
    """Load the router's model-chain changelog. Returns [] on any failure."""
    try:
        with open(ROUTER_CHANGELOG_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _fmt_models(ids):
    if not ids:
        return "—"
    return "<br>".join(f"<code>{esc(i)}</code>" for i in ids)


def render_router_changelog(history, generated_at):
    if not history:
        body = '<section class="page-head"><h1>Router — Model Chain Changes</h1>' \
               '<p class="lead">No router changes recorded yet. The audit run writes here on ' \
               'every config apply.</p></section>'
        return page("Router — Model Chain Changes", "comparisons-router-changelog.html", body, generated_at)

    # Latest entry = current chain state
    latest = history[-1]
    cur_by_alias = {}
    for ch in latest.get("changes", []):
        cur_by_alias[ch["alias"]] = ch["new"]

    # Current chains table
    chain_rows = []
    for alias in ["free-general", "free-fast", "free-coding", "free-fallback"]:
        ids = cur_by_alias.get(alias, [])
        chain_rows.append([
            f"<strong>{ALIAS_LABELS.get(alias, alias)}</strong>",
            _fmt_models(ids),
            str(len(ids)),
        ])
    chains_html = table(["Alias", "Chain (priority order)", "Models"], chain_rows)

    # History table (most recent first)
    hist_rows = []
    for entry in reversed(history):
        ts = entry.get("at", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
            when = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            when = ts[:16]
        for ch in entry.get("changes", []):
            alias = ALIAS_LABELS.get(ch["alias"], ch["alias"])
            hist_rows.append([
                f"<code class='dim'>{when}</code>",
                f"<strong>{alias}</strong>",
                _fmt_models(ch.get("old", [])),
                _fmt_models(ch.get("new", [])),
            ])
    history_html = table(["When", "Alias", "Was", "Now"], hist_rows, cls="hist")

    body = f"""
<section class="page-head"><h1>Router — Model Chain Changes</h1>
<p class="lead">Auto-audit of the Hermes router runs <strong>daily at 06:00 UTC</strong>
against <strong>OpenRouter, Nous Portal and OpenCode Zen</strong>, re-ranks each alias chain,
applies the new <code>config.yaml</code>, smoke-tests all 4 aliases and rolls back on failure.
This page reflects the chain state recorded by the last audit only.</p></section>
<h2 style="margin-top:28px">Current chains (last audit)</h2>
{chains_html}
<h2 style="margin-top:32px">Change history</h2>
{history_html}
"""
    return page("Router — Model Chain Changes", "comparisons-router-changelog.html", body, generated_at)


def render_index(models, d, history, statuses, generated_at):
    n = len(models)
    src_bits = " · ".join(
        f"{name}: {'ok' if st['ok'] else 'ERR'} ({st['count']})"
        for name, st in statuses.items())
    change_html = ""
    if d["added"] or d["removed"]:
        parts = []
        if d["added"]:
            parts.append("<strong>Added:</strong> " + ", ".join(f"<code>{esc(i)}</code>" for i in d["added"]))
        if d["removed"]:
            parts.append("<strong>Removed:</strong> " + ", ".join(f"<code>{esc(i)}</code>" for i in d["removed"]))
        change_html = "<blockquote>This run — " + " · ".join(parts) + "</blockquote>"
    # History table: sorted most recent first, formatted timestamps
    hist_sorted = sorted(history or [], key=lambda h: h.get("at", ""), reverse=True)
    hist_rows = [
        [fmt_ts(h["at"]),
         ", ".join(f"<code>{esc(i)}</code>" for i in h["added"]) or "—",
         ", ".join(f"<code>{esc(i)}</code>" for i in h["removed"]) or "—"]
        for h in hist_sorted[:5]]
    cards = f"""
<a class="card" href="comparisons-benchmarks.html"><div class="c-icon"></div><h3>Benchmarks — Free Roster vs Paid Frontier</h3>
<p>How the current free roster scores on Artificial Analysis benchmarks, with the best paid model as reference.</p><span class="c-type">Comparison</span></a>
<a class="card" href="comparisons-free-models-ranking.html"><div class="c-icon"></div><h3>Free Models — Ranked by Use Case</h3>
<p>Strictly $0 models across OpenRouter, Nous Portal and OpenCode Zen. Auto-refreshed daily.</p><span class="c-type">Comparison</span></a>
<a class="card" href="comparisons-router-changelog.html"><div class="c-icon"></div><h3>Router — Model Chain Changes</h3>
<p>Which upstream each Hermes router alias actually uses, and how chains change over time.</p><span class="c-type">Router</span></a>"""
    body = f"""
<section class="hero"><h1>Free-tier model knowledge base</h1>
<p class="lead">Hermes Agent — inventory of the <strong>truly free</strong> models available across
configured providers. Strict rule: listed price must be exactly <strong>$0</strong>.</p>
<p class="src-note">Last updated: <strong>{fmt_ts(generated_at)}</strong></p></section>
<blockquote>Current roster: <strong>{n} free models</strong>. Sources this run: {esc(src_bits)}</blockquote>
{change_html}
<div class="card-grid">{cards}</div>
<h2 style="margin-top:32px">Recent changes</h2>
{table(["When", "Added", "Removed"], hist_rows) if hist_rows else "<p class='src-note'>No changes recorded yet.</p>"}"""
    return page("Home", "index.html", body, generated_at)


def main():
    merged, statuses = collect_all()
    # strict: drop anything not provably $0 or explicitly zen-curated,
    # plus routers/aggregators/UI helpers that aren't real callable models.
    # "zen-micro" = explicit micro-price exemption (free on Zen, badge-labeled).
    models = [m for m in merged if m["free_basis"] in ("price-0", "zen-free", "zen-micro")
              and not is_junk(m)]
    old = S.load_snapshot()
    d = S.diff(old["models"] if old else [], models)
    generated_at = S._now()
    snap = S.save_snapshot(models, statuses)
    S.append_history(d)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "comparisons-free-models-ranking.html"), "w", encoding="utf-8") as f:
        f.write(render_ranking(models, generated_at))
    with open(os.path.join(OUT_DIR, "comparisons-router-changelog.html"), "w", encoding="utf-8") as f:
        f.write(render_router_changelog(load_router_changelog(), generated_at))
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(models, d, S.load_history(), statuses, generated_at))
    print(f"generated {len(models)} free models at {generated_at}")
    print("statuses:", {k: v["count"] for k, v in statuses.items()})
    print("diff:", d)


if __name__ == "__main__":
    main()
