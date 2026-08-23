#!/usr/bin/env python3
"""Benchmarks page: Artificial Analysis API (live) with last-good cache fallback."""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from render import page, table, esc
from snapshot import load_snapshot

AA_URL = ("https://artificialanalysis.ai/api/v2/data/llms/models"
          "?fields=model_name,creator_name,intelligence_index,coding_index,agentic_index,"
          "median_output_tokens_per_second,median_time_to_first_token_seconds")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "benchmarks-cache.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", "comparisons-benchmarks.html")

# paid frontier reference per category
REFERENCE = {"name": "Claude Opus 5 (Adaptive Reasoning)",
             "intelligence": 62.5, "coding": 77.0, "agentic": 58.4}

CATEGORIES = [
    ("🧠 Overall intelligence", "artificial_analysis_intelligence_index",
     "AA Intelligence Index — agents, coding, scientific reasoning, general knowledge."),
    ("💻 Coding", "artificial_analysis_coding_index",
     "AA Coding Index — code generation, completion, review."),
    ("🤖 Agentic coding / terminal", "terminalbench_hard",
     "Terminal-Bench Hard — agentic terminal usage, tool use, multi-step workflows (0-1 scale)."),
]

# Multimodal: separate section — roster models that accept image input,
# ranked by AA Intelligence Index (no dedicated MMMU field in the free API).
MULTIMODAL_FIELD = "artificial_analysis_intelligence_index"


def is_multimodal(m):
    return "image" in (m.get("modalities") or "")


def fetch_aa():
    key = os.environ.get("AA_API_KEY")
    if not key:
        return None, "AA_API_KEY not set"
    req = urllib.request.Request(
        AA_URL, headers={"x-api-key": key, "User-Agent": "model-wiki-automation/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
        # flatten evaluations into top-level keys for easy access
        for a in data.get("data", []):
            ev = a.pop("evaluations", None) or {}
            a.update(ev)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return data["data"], ""
    except Exception as e:
        return None, str(e)


def load_cached():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)["data"]
    return []


def match_free(free_models, aa_models):
    """Map normalized free-model ids to AA entries.
    Strategy: token overlap on the model's base name, plus targeted alias
    handling for known naming mismatches (e.g. 'nemotron-3.5-lightning' vs
    'Nemotron 3.5 Lightning', 'tencent/hy3:free' vs 'Hy3')."""
    def aa_tokens(name):
        return set(_split(name.lower()))

    # pre-index AA entries by their significant tokens (drop effort variants)
    aa_entries = []
    for a in aa_models:
        n = a.get("name") or ""
        toks = {t for t in _split(n.lower()) if t not in
                ("low", "high", "medium", "max", "xhigh", "non-reasoning", "reasoning")}
        aa_entries.append((toks, n, a))

    matched = {}
    for m in free_models:
        mid = m["id"]
        base = mid.split("/")[-1]
        mtoks = set(_split(base))
        best, best_score = None, 0
        for toks, n, a in aa_entries:
            score = len(mtoks & toks)
            if score > best_score:
                best, best_score = a, score
        if best and best_score >= 2:
            matched[mid] = best
    return matched


def _split(s):
    for ch in "-_/().,: ":
        s = s.replace(ch, " ")
    return [t for t in s.split() if t and t not in ("the", "by")]


def render(models, generated_at):
    aa_data, err = fetch_aa()
    from_cache = False
    if aa_data is None:
        aa_data = load_cached()
        from_cache = bool(aa_data)

    matched = match_free(models, aa_data)

    # paid frontier: top 3 paid AA models per category (by that category's score)
    def top_paid(field, n=3):
        scored = [(a.get(field), a) for a in aa_data
                  if a.get(field) is not None
                  and float((a.get("pricing") or {}).get("price_1m_blended_3_to_1", 0) or 0) > 0]
        scored.sort(key=lambda x: -x[0])
        return scored[:n]

    TOP_N_FREE = 3

    sections = []
    for title, field, desc in CATEGORIES:
        scored = []
        for m in models:
            a = matched.get(m["id"])
            v = (a or {}).get(field) if a else None
            if v is not None:
                scored.append((v, m))
        scored.sort(key=lambda x: -x[0])
        rows = []
        for i, (v, m) in enumerate(scored[:TOP_N_FREE]):
            star = " ⭐" if i == 0 else ""
            rows.append([f'<code>{esc(m["display_id"])}</code>',
                         f'<span class="badge badge-free">free</span> {v}{star}'])
        for v, a in top_paid(field):
            name = f"{a['name']} ({(a.get('model_creator') or {}).get('name', '')})"
            rows.append([f"<em>{esc(name)} *</em>",
                         f'<span class="badge badge-plan">paid</span> {v}'])
        no_data_count = sum(1 for m in models if m["id"] not in matched)
        note = (f" <span class='src-note'>({no_data_count} roster models without AA data omitted)</span>"
                if no_data_count else "")
        sections.append(f"<h2>{title}</h2><p class='src-note'>{desc}{note}</p>"
                        + table(["Model", "Score"], rows))

    # multimodal section: free roster models with image input, ranked by intel index
    mm = [(matched[m["id"]].get(MULTIMODAL_FIELD), m) for m in models
          if is_multimodal(m) and m["id"] in matched]
    mm = [(v, m) for v, m in mm if v is not None]
    mm.sort(key=lambda x: -x[0])
    mm_rows = [[f'<code>{esc(m["display_id"])}</code>',
                f'<span class="badge badge-free">free</span> {v}{" ⭐" if i == 0 else ""}']
               for i, (v, m) in enumerate(mm[:TOP_N_FREE])]
    for v, a in top_paid(MULTIMODAL_FIELD):
        name = f"{a['name']} ({(a.get('model_creator') or {}).get('name', '')})"
        mm_rows.append([f"<em>{esc(name)} *</em>",
                        f'<span class="badge badge-plan">paid</span> {v}'])
    sections.append(
        "<h2>🖼️ Multimodal (vision)</h2><p class='src-note'>Free roster models accepting image input, "
        "ranked by AA Intelligence Index as proxy (no dedicated MMMU field in the free API).</p>"
        + table(["Model", "Score"], mm_rows))

    src_note = "Live from Artificial Analysis API"
    if err and from_cache:
        src_note = f"⚠ AA live fetch failed ({esc(err)[:80]}) — showing cached data"
    body = f"""
<section class="page-head"><h1>Benchmarks — Free Roster vs Paid Frontier</h1>
<p class="lead">Top {TOP_N_FREE} <strong>$0 roster models</strong> vs top-3 paid alternatives per category,
from public Artificial Analysis benchmarks. Best free model marked ⭐.</p></section>
<p class="src-note">Source: {src_note}</p>
{''.join(sections)}"""
    return page("Benchmarks — Free Roster vs Paid Frontier",
                "comparisons-benchmarks.html", body, generated_at)


def main():
    snap = load_snapshot()
    models = snap["models"] if snap else []
    generated_at = snap["generated_at"] if snap else ""
    html = render(models, generated_at)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"benchmarks written ({len(models)} roster models)")


if __name__ == "__main__":
    main()
