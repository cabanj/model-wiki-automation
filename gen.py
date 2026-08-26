#!/usr/bin/env python3
"""model-wiki generator: fetch all sources -> diff vs snapshot -> render HTML pages."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources import collect_all
from sources.common import normalize_id, is_junk
import snapshot as S
from render import page, table, model_rows, esc

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
    hist_rows = [
        [h["at"],
         ", ".join(f"<code>{esc(i)}</code>" for i in h["added"]) or "—",
         ", ".join(f"<code>{esc(i)}</code>" for i in h["removed"]) or "—"]
        for h in history[:5]]
    cards = f"""
<a class="card" href="comparisons-benchmarks.html"><div class="c-icon"></div><h3>Benchmarks — Free Roster vs Paid Frontier</h3>
<p>How the current free roster scores on Artificial Analysis benchmarks, with the best paid model as reference.</p><span class="c-type">Comparison</span></a>
<a class="card" href="comparisons-free-models-ranking.html"><div class="c-icon"></div><h3>Free Models — Ranked by Use Case</h3>
<p>Strictly $0 models across OpenRouter, Nous Portal and OpenCode Zen. Auto-refreshed daily.</p><span class="c-type">Comparison</span></a>"""
    body = f"""
<section class="hero"><h1>Free-tier model knowledge base</h1>
<p class="lead">Hermes Agent — inventory of the <strong>truly free</strong> models available across
configured providers. Strict rule: listed price must be exactly <strong>$0</strong>.</p></section>
<blockquote>Current roster: <strong>{n} free models</strong>. Sources this run: {esc(src_bits)}</blockquote>
{change_html}
<div class="card-grid">{cards}</div>
<h2 style="margin-top:32px">Recent changes</h2>
{table(["When", "Added", "Removed"], hist_rows) if hist_rows else "<p class='src-note'>No changes recorded yet.</p>"}"""
    return page("Home", "index.html", body, generated_at)


def main():
    merged, statuses = collect_all()
    # strict: drop anything not provably $0 or explicitly zen-curated,
    # plus routers/aggregators/UI helpers that aren't real callable models
    models = [m for m in merged if m["free_basis"] in ("price-0", "zen-free")
              and not is_junk(m)]
    old = S.load_snapshot()
    d = S.diff(old["models"] if old else [], models)
    generated_at = S._now()
    snap = S.save_snapshot(models, statuses)
    S.append_history(d)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "comparisons-free-models-ranking.html"), "w", encoding="utf-8") as f:
        f.write(render_ranking(models, generated_at))
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(models, d, S.load_history(), statuses, generated_at))

    print(f"generated {len(models)} free models at {generated_at}")
    print("statuses:", {k: v["count"] for k, v in statuses.items()})
    print("diff:", d)


if __name__ == "__main__":
    main()
