#!/usr/bin/env python3
"""Generate the free-model directory and static wiki pages."""

from datetime import datetime, timezone
import hashlib
import json
import os
import sys
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources import collect_all
from sources.common import is_junk
import snapshot as S
import render
from render import esc, fmt_ts, model_row_attrs, model_rows, page, site_url, table

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
        headers = ["Use case", "Model", "Model name", "Eligibility", "Sources", "Context", "Modalities", "Description"]
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


def render_feed(history, generated_at):
    def rfc822(ts):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        except Exception:
            return ts
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    base = site_url()
    for tag, value in (("title", "llmroster.dev — Model Changes"),
                       ("link", base or "index.html"),
                       ("description", "Recent additions and removals from the free model roster."),
                       ("lastBuildDate", rfc822(generated_at))):
        ET.SubElement(channel, tag).text = value
    feed_url = site_url("feed.xml")
    if base and feed_url:
        ET.SubElement(channel, "{http://www.w3.org/2005/Atom}link", {
            "href": feed_url, "rel": "self", "type": "application/rss+xml"})
    for change in sorted(history or [], key=lambda h: h.get("at", ""), reverse=True)[:20]:
        added = change.get("added", [])
        removed = change.get("removed", [])
        description = "Added: " + (", ".join(added) or "none") + ". Removed: " + (", ".join(removed) or "none") + "."
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"Roster change: {len(added)} added, {len(removed)} removed"
        ET.SubElement(item, "description").text = description
        ET.SubElement(item, "pubDate").text = rfc822(change.get("at", ""))
        digest = hashlib.sha256(json.dumps(change, sort_keys=True).encode()).hexdigest()
        ET.SubElement(item, "guid").text = f"urn:model-wiki:change:{digest}"
    return ET.tostring(root, encoding="unicode")


def _quickstart_model(models):
    candidates = [m for m in models if "openrouter" in m.get("sources", [])]
    if not candidates:
        return "openrouter/YOUR_MODEL_ID:free"
    return sorted(candidates, key=lambda m: m.get("display_id", m.get("id", "")))[0].get("display_id", candidates[0]["id"])


def render_quick_start(models):
    model_id_value = _quickstart_model(models)
    base = "https://openrouter.ai/api/v1"
    snippets = {
        "cURL": f'''curl {base}/chat/completions \\\n  -H "Authorization: Bearer $OPENROUTER_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d \'{{"model":"{model_id_value}","messages":[{{"role":"user","content":"Hello"}}]}}\'''',
        "Python": f'''import os\nfrom openai import OpenAI\n\nclient = OpenAI(\n    base_url="{base}",\n    api_key=os.environ["OPENROUTER_API_KEY"],\n)\nresponse = client.chat.completions.create(\n    model="{model_id_value}",\n    messages=[{{"role": "user", "content": "Hello"}}],\n)\nprint(response.choices[0].message.content)''',
        "TypeScript / Node.js": f'''import OpenAI from "openai";\n\nconst client = new OpenAI({{ baseURL: "{base}", apiKey: process.env.OPENROUTER_API_KEY }});\nconst response = await client.chat.completions.create({{\n  model: "{model_id_value}",\n  messages: [{{ role: "user", content: "Hello" }}],\n}});\nconsole.log(response.choices[0].message.content);''',
    }
    panels = "".join(f'<input type="radio" name="quickstart-tab" id="quickstart-{i}" class="quickstart-radio" {"checked" if i == 0 else ""}><label for="quickstart-{i}">{label}</label><div class="quickstart-panel"><pre><code>{esc(snippet)}</code></pre><button type="button" class="copy-button" data-copy-value="{esc(snippet)}">Copy snippet</button></div>' for i, (label, snippet) in enumerate(snippets.items()))
    return f'''<details class="quickstart"><summary>Developer quick start</summary><p>Connect through OpenRouter, then replace this example with any copied model ID from the directory.</p><div class="quickstart-tabs">{panels}</div></details>'''


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
         ", ".join(render.model_id(i) for i in h["added"]) or "—",
         ", ".join(render.model_id(i) for i in h["removed"]) or "—"]
        for h in hist_sorted[:5]]
    cards = f'''
<a class="card" href="comparisons-free-models-ranking.html"><span class="card-kicker">Directory</span><h3>Find a free model</h3><p>Filter the current roster by use case, model ID, source, modality, or capability.</p><div class="card-meta"><span>{n} models</span><span class="card-arrow">→</span></div></a>
<a class="card" href="comparisons-benchmarks.html"><span class="card-kicker">Decision guide</span><h3>Compare benchmark leaders</h3><p>Start with the best free model for everyday work, research, coding, and vision.</p><div class="card-meta"><span>AA benchmarks</span><span class="card-arrow">→</span></div></a>'''
    history_html = table(["When", "Added", "Removed"], hist_rows,
                         caption="Recent model roster changes", row_header=0) if hist_rows else '<div class="empty-state">No roster changes recorded yet.</div>'
    body = f'''<div class="page-body">
<section class="hero">
  <span class="eyebrow">LLM Roster · live model intelligence</span>
  <h1>Choose the right free model with confidence.</h1>
  <p class="lead">A continuously refreshed inventory of genuinely free models across configured providers, with benchmark comparisons to guide your choice.</p>
  <p class="src-note">Last updated: <strong>{fmt_ts(generated_at)}</strong></p>
</section>
<div class="metric-strip" aria-label="Current model roster summary">
  <div class="metric"><span class="metric-label">Free roster</span><strong class="metric-value">{n}</strong><span class="metric-note">models currently confirmed</span></div>
  <div class="metric"><span class="metric-label">Sources</span><strong class="metric-value">{source_count}</strong><span class="metric-note">statuses checked this run</span></div>
  <div class="metric"><span class="metric-label">This run</span><strong class="metric-value">{change_count}</strong><span class="metric-note">roster changes</span></div>
</div>
<blockquote><strong>Eligibility policy:</strong> listed prompt and completion pricing must be exactly $0. Zen exceptions are explicitly labelled. Source status: {esc(src_bits)}.</blockquote>
{render_quick_start(models)}
{change_html}
<div class="card-grid">{cards}</div>
<h2>Recent roster changes</h2>
{history_html}
</div>'''
    return page("Home", "index.html", body, generated_at)


def main():
    from_snapshot = "--from-snapshot" in sys.argv[1:]
    if from_snapshot:
        # Rebuild pages from the last persisted roster: no source fetch, no snapshot
        # write, no history append. Used by deploy-only.sh so a merge to main
        # republishes with new render code but unchanged data.
        old = S.load_snapshot()
        if not old:
            raise SystemExit("--from-snapshot: no data/models.json snapshot to rebuild from")
        merged, statuses = old["models"], old.get("statuses", {})
        models = [m for m in merged if m["free_basis"] in ("price-0", "zen-free", "zen-micro")
                  and not is_junk(m)]
        d = {"added": [], "removed": [], "unchanged_count": len(models)}
    else:
        merged, statuses = collect_all()
        models = [m for m in merged if m["free_basis"] in ("price-0", "zen-free", "zen-micro")
                  and not is_junk(m)]
        old = S.load_snapshot()
        d = S.diff(old["models"] if old else [], models)
    generated_at = S._now()
    if not from_snapshot:
        S.save_snapshot(models, statuses)
        S.append_history(d)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "comparisons-free-models-ranking.html"), "w", encoding="utf-8") as f:
        f.write(render_ranking(models, generated_at))
    stale_router_page = os.path.join(OUT_DIR, "comparisons-router-changelog.html")
    if os.path.exists(stale_router_page):
        os.remove(stale_router_page)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(models, d, S.load_history(), statuses, generated_at))
    with open(os.path.join(OUT_DIR, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(render_feed(S.load_history(limit=20), generated_at))
    print(f"generated {len(models)} free models at {generated_at}")
    print("statuses:", {k: v["count"] for k, v in statuses.items()})
    print("diff:", d)

    if d["added"] or d["removed"]:
        import x_publisher
        print("ready-to-paste post:")
        print(x_publisher.format_message(d["added"], d["removed"]))


if __name__ == "__main__":
    main()
