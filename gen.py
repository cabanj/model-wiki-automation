#!/usr/bin/env python3
"""Generate the free-model directory and static wiki pages."""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources import collect_all
from sources.common import is_junk
import snapshot as S
from render import esc, fmt_ts, model_row_attrs, model_rows, page, table

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")

USE_CASES = [
    ("Deep reasoning / research", ["reasoning", "ultra", "thinking", "r1", "nemotron-3-ultra"]),
    ("Agentic coding", ["cod", "laguna", "devstral"]),
    ("Long-context work", ["longcat"]),
    ("Vision / multimodal", ["vision", "omni", "vl-", "-vl", "gemma"]),
    ("Fast / lightweight", ["lightning", "flash", "nano", "mini", "lfm"]),
    ("General purpose fallback", []),
]
ROLE_IDS = {role: f"role-{index + 1}" for index, (role, _) in enumerate(USE_CASES)}


def assign_role(m):
    hay = m["id"].lower() + " " + m.get("description", "").lower()[:200]
    for role, keywords in USE_CASES:
        if any(keyword in hay for keyword in keywords):
            return role
    return USE_CASES[-1][0]


def sort_models(models):
    order = {role: index for index, (role, _) in enumerate(USE_CASES)}
    source_order = {"nous": 0, "opencode-zen": 1, "openrouter": 2}

    def primary_source(m):
        return min(source_order.get(source, 9) for source in m["sources"])

    return sorted(models, key=lambda m: (order.get(m.get("role"), 99), primary_source(m),
                                          (m.get("name") or m["id"]).lower()))


def render_ranking(models, generated_at):
    enriched = [dict(m, role=assign_role(m)) for m in models]
    enriched = sort_models(enriched)
    groups = []
    for role, _ in USE_CASES:
        group_models = [m for m in enriched if m["role"] == role]
        if group_models:
            groups.append((role, group_models))
    role_options = "".join(
        f'<option value="{esc(role)}">{esc(role)}</option>' for role, _ in groups)
    sections = []
    for role, group_models in groups:
        headers = ["Use case", "Model", "Eligibility", "Sources", "Context", "Modalities", "Description"]
        sections.append(
            f'<section class="model-group" data-model-group><div class="model-group-head">'
            f'<h2 id="{ROLE_IDS[role]}">{esc(role)}</h2><span>{len(group_models)} models</span></div>'
            f'{table(headers, model_rows(group_models), cls="model-table", caption=f"Free models for {role}", row_header=1, row_attrs=[model_row_attrs(m) for m in group_models])}'
            '</section>')
    source_count = len({source for m in models for source in m.get("sources", [])})
    body = f'''<div class="page-body">
<section class="page-head">
  <span class="eyebrow">Model directory · {len(models)} currently available</span>
  <h1>Free models by use case</h1>
  <p class="lead">A practical directory of models confirmed as truly free by at least one configured source. Use the filters to narrow the roster by use case or search by model ID, capability, modality, or source.</p>
</section>
<div class="metric-strip" aria-label="Directory summary">
  <div class="metric"><span class="metric-label">Models</span><strong class="metric-value">{len(models)}</strong><span class="metric-note">confirmed free</span></div>
  <div class="metric"><span class="metric-label">Use cases</span><strong class="metric-value">{len(groups)}</strong><span class="metric-note">directory groups</span></div>
  <div class="metric"><span class="metric-label">Sources</span><strong class="metric-value">{source_count}</strong><span class="metric-note">OpenRouter, Nous, Zen</span></div>
</div>
<div data-model-filter>
  <div class="filter-bar">
    <div class="filter-field"><label for="model-search">Search models</label><input class="filter-input" id="model-search" type="search" data-model-filter-input placeholder="Try GLM, coding, image…" autocomplete="off"></div>
    <div class="filter-field filter-field--role"><label for="use-case-filter">Use case</label><select class="filter-select" id="use-case-filter" data-model-filter-role><option value="">All use cases</option>{role_options}</select></div>
    <span class="filter-count" data-model-filter-count><strong>{len(models)}</strong> models</span>
  </div>
  <div data-model-list>
    {''.join(sections)}
    <div class="empty-state" data-model-filter-empty hidden>No models match the current filters. Try a broader search or another use case.</div>
  </div>
</div>
</div>'''
    return page("Free models by use case", "comparisons-free-models-ranking.html", body, generated_at)


ROUTER_CHANGELOG_PATH = "/opt/hermes-router/data/changelog.json"

ALIAS_LABELS = {
    "free-general": "General",
    "free-fast": "Fast",
    "free-coding": "Coding",
    "free-fallback": "Fallback",
}


def load_router_changelog():
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
        body = '<div class="page-body"><section class="page-head"><span class="eyebrow">Router audit</span><h1>Router model-chain changes</h1><p class="lead">No router changes have been recorded yet. The audit run writes here after every config apply.</p></section></div>'
        return page("Router model-chain changes", "comparisons-router-changelog.html", body, generated_at)

    latest = history[-1]
    cur_by_alias = {}
    for change in latest.get("changes", []):
        cur_by_alias[change["alias"]] = change["new"]

    chain_rows = []
    for alias in ["free-general", "free-fast", "free-coding", "free-fallback"]:
        ids = cur_by_alias.get(alias, [])
        chain_rows.append([
            f"<strong>{esc(ALIAS_LABELS.get(alias, alias))}</strong>",
            _fmt_models(ids),
            str(len(ids)),
        ])
    chains_html = table(["Alias", "Chain priority order", "Models"], chain_rows,
                        caption="Current router chains", row_header=0)

    history_rows = []
    for entry in reversed(history):
        ts = entry.get("at", "")
        try:
            when = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            when = ts[:16]
        for change in entry.get("changes", []):
            history_rows.append([
                f"<code>{esc(when)}</code>",
                f"<strong>{esc(ALIAS_LABELS.get(change['alias'], change['alias']))}</strong>",
                _fmt_models(change.get("old", [])),
                _fmt_models(change.get("new", [])),
            ])
    history_html = table(["When", "Alias", "Was", "Now"], history_rows,
                         cls="history-table", caption="Router chain history", row_header=1)

    body = f'''<div class="page-body">
<section class="page-head">
  <span class="eyebrow">Router audit · last recorded state</span>
  <h1>Router model-chain changes</h1>
  <p class="lead">The daily Hermes audit compares OpenRouter, Nous Portal, and OpenCode Zen, re-ranks each alias chain, applies the new configuration, and records the result only after a successful smoke test.</p>
</section>
<h2 id="current-chains">Current chains</h2>
{chains_html}
<h2 id="change-history">Change history</h2>
{history_html}
</div>'''
    return page("Router model-chain changes", "comparisons-router-changelog.html", body, generated_at)


def render_index(models, d, history, statuses, generated_at):
    n = len(models)
    source_count = len(statuses)
    change_count = len(d["added"]) + len(d["removed"])
    src_bits = " · ".join(
        f"{name}: {'healthy' if status['ok'] else 'unavailable'} ({status['count']})"
        for name, status in statuses.items())
    change_html = ""
    if d["added"] or d["removed"]:
        parts = []
        if d["added"]:
            parts.append(f"<strong>{len(d['added'])} added</strong>")
        if d["removed"]:
            parts.append(f"<strong>{len(d['removed'])} removed</strong>")
        change_html = f'<blockquote>This run changed the roster: {" · ".join(parts)}. <a href="comparisons-free-models-ranking.html">Review the directory →</a></blockquote>'
    hist_sorted = sorted(history or [], key=lambda h: h.get("at", ""), reverse=True)
    hist_rows = [
        [fmt_ts(h["at"]),
         ", ".join(f"<code>{esc(i)}</code>" for i in h["added"]) or "—",
         ", ".join(f"<code>{esc(i)}</code>" for i in h["removed"]) or "—"]
        for h in hist_sorted[:5]]
    cards = f'''
<a class="card" href="comparisons-free-models-ranking.html"><span class="card-kicker">Directory</span><h3>Find a free model</h3><p>Filter the current roster by use case, model ID, source, modality, or capability.</p><div class="card-meta"><span>{n} models</span><span class="card-arrow">→</span></div></a>
<a class="card" href="comparisons-benchmarks.html"><span class="card-kicker">Decision guide</span><h3>Compare benchmark leaders</h3><p>Start with the best free model for everyday work, research, coding, and vision.</p><div class="card-meta"><span>AA benchmarks</span><span class="card-arrow">→</span></div></a>
<a class="card" href="comparisons-router-changelog.html"><span class="card-kicker">Operations</span><h3>See router changes</h3><p>Track the model chain applied to each Hermes routing alias over time.</p><div class="card-meta"><span>Audit history</span><span class="card-arrow">→</span></div></a>'''
    history_html = table(["When", "Added", "Removed"], hist_rows,
                         caption="Recent model roster changes", row_header=0) if hist_rows else '<div class="empty-state">No roster changes recorded yet.</div>'
    body = f'''<div class="page-body">
<section class="hero">
  <span class="eyebrow">Hermes Agent · live model intelligence</span>
  <h1>Choose the right free model with confidence.</h1>
  <p class="lead">A continuously refreshed inventory of genuinely free models across configured providers, with benchmark comparisons and the router changes that shape production behavior.</p>
  <p class="src-note">Last updated: <strong>{fmt_ts(generated_at)}</strong></p>
</section>
<div class="metric-strip" aria-label="Current model wiki summary">
  <div class="metric"><span class="metric-label">Free roster</span><strong class="metric-value">{n}</strong><span class="metric-note">models currently confirmed</span></div>
  <div class="metric"><span class="metric-label">Sources</span><strong class="metric-value">{source_count}</strong><span class="metric-note">statuses checked this run</span></div>
  <div class="metric"><span class="metric-label">This run</span><strong class="metric-value">{change_count}</strong><span class="metric-note">roster changes</span></div>
</div>
<blockquote><strong>Eligibility policy:</strong> listed prompt and completion pricing must be exactly $0. Zen exceptions are explicitly labelled. Source status: {esc(src_bits)}.</blockquote>
{change_html}
<div class="card-grid">{cards}</div>
<h2>Recent roster changes</h2>
{history_html}
</div>'''
    return page("Home", "index.html", body, generated_at)


def main():
    merged, statuses = collect_all()
    models = [m for m in merged if m["free_basis"] in ("price-0", "zen-free", "zen-micro")
              and not is_junk(m)]
    old = S.load_snapshot()
    d = S.diff(old["models"] if old else [], models)
    generated_at = S._now()
    S.save_snapshot(models, statuses)
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
