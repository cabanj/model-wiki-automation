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
    ("⚙️ Agentic / terminal", "agentic_index",
     "AA Agentic Index — terminal usage, tool use, multi-step workflows."),
]


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

    free_ids = {m["id"] for m in models}
    matched = match_free(models, aa_data)

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
        for v, m in scored[:10]:
            star = " ⭐" if m["free_basis"] == "price-0" and v == scored[0][0] else ""
            rows.append([f'<code>{esc(m["display_id"])}</code>', f"{v}{star}"])
        if REFERENCE.get(field.replace("artificial_analysis_", "").replace("_index", "")) is None:
            ref_val = REFERENCE.get({"artificial_analysis_intelligence_index": "intelligence",
                                     "artificial_analysis_coding_index": "coding",
                                     "agentic_index": "agentic"}.get(field), "")
        else:
            ref_val = REFERENCE.get(field.replace("artificial_analysis_", "").replace("_index", ""))
        if ref_val:
            rows.append([f"<em>{esc(REFERENCE['name'])} *</em>", str(ref_val)])
        # roster members without AA data
        no_data = [m for m in models if m["id"] not in matched]
        for m in no_data[:6]:
            rows.append([f'<code>{esc(m["display_id"])}</code>', "—"])
        note = f" <span class='src-note'>({len(no_data)} roster models without AA data shown as —)</span>" if no_data else ""
        sections.append(f"<h2>{title}</h2><p class='src-note'>{desc}{note}</p>"
                        + table(["Model", "Score"], rows))

    src_note = "Live from Artificial Analysis API"
    if err and from_cache:
        src_note = f"⚠ AA live fetch failed ({esc(err)[:80]}) — showing cached data"
    body = f"""
<section class="page-head"><h1>Benchmarks — Free Roster vs Paid Frontier</h1>
<p class="lead">How the current <strong>strictly-$0 roster</strong> scores on public benchmarks,
with the best commercial model in each category as reference (*).
Best verified-free model per category marked ⭐.</p></section>
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
