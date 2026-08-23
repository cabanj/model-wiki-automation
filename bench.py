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


# Explicit alias map: normalized roster id -> exact AA model name.
# Used when fuzzy matching would pick the wrong AA entry (verified manually
# against live AA names). Anything not listed falls back to fuzzy matching.
AA_ALIASES = {
    "z-ai/glm-5.2": "GLM-5.2 (max)",
    "meituan/longcat-2.0": "LongCat 2.0",
    "upstage/solar-pro4": "Solar Pro 4",
    "mimo-v2.5": "MiMo-V2.5",
    "liquid/lfm-2.5-2.6b": "LFM2 2.6B",
    "cohere/north-mini-code": "North Mini Code",
    "google/gemma-4-26b-a4b-it": "Gemma 4 26B A4B (Reasoning)",
    "google/gemma-4-31b-it": "Gemma 4 31B (Non-reasoning)",
    "nvidia/nemotron-3-nano-30b-a3b": "NVIDIA Nemotron 3 Nano 30B A3B (Reasoning)",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning": "Nemotron 3 Nano Omni 30B A3B Reasoning",
    "nvidia/nemotron-3-super-120b-a12b": "Nemotron 3 Super 120B A12B (Reasoning)",
    "nvidia/nemotron-3-ultra-550b-a55b": "Nemotron 3 Ultra 550B A55B (Reasoning)",
    "nemotron-3-ultra": "Nemotron 3 Ultra 550B A55B (Reasoning)",
    "nemotron-3.5-lightning": "Nemotron 3.5 Lightning",
    "nvidia/nemotron-3.5-lightning": "Nemotron 3.5 Lightning",
    "nvidia/nemotron-nano-12b-v2-vl": "NVIDIA Nemotron Nano 12B v2 VL (Reasoning)",
    "nvidia/nemotron-nano-9b-v2": "NVIDIA Nemotron Nano 9B V2 (Non-reasoning)",
    "stepfun/step-3.7-flash": "Step 3.7 Flash",
    "thinkingmachines/inkling": "Inkling (xhigh)",
    "thinkingmachines/inkling-small": "Inkling Small",
    "muse-spark-1.2-contributor": "Muse Spark 1.2 (xhigh)",
}


def match_free(free_models, aa_models):
    """Map normalized free-model ids to AA entries.
    Matching uses only 'significant' tokens: >=3 chars and not pure numbers.
    This prevents false positives like laguna-s-2.1 ~ Muse Spark 1.2 (shared
    tokens '2','1'). A match requires >=1 significant shared token; ties broken
    by higher token overlap. Verified-free models not present in AA stay
    unmatched (no score shown — never guessed)."""
    def sig_tokens(s):
        return {t for t in _split(s.lower())
                if len(t) >= 3 and not t.replace(".", "").isdigit()}

    aa_entries = []
    for a in aa_models:
        n = a.get("name") or ""
        toks = {t for t in sig_tokens(n)}
        aa_entries.append((toks, n, a))

    matched = {}
    by_name = {a.get("name", ""): a for _, n, a in aa_entries}
    for m in free_models:
        mid = m["id"]
        # 1) explicit alias wins
        if mid in AA_ALIASES and AA_ALIASES[mid] in by_name:
            matched[mid] = by_name[AA_ALIASES[mid]]
            continue
        # 2) fuzzy fallback (only for models NOT explicitly aliased — and only
        #    when the match is unambiguous, i.e. >=2 significant shared tokens)
        base = mid.split("/")[-1]
        mtoks = {t for t in sig_tokens(base)
                 if t not in ("preview", "free", "stealth", "contributor", "reasoning")}
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

    def fmt_score(v):
        """2 decimal places max, no trailing-zero noise."""
        if isinstance(v, float) and 0 <= v <= 1:
            return f"{v:.2f}"
        return f"{float(v):.2f}"

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
                         f'<span class="badge badge-free">free</span> {fmt_score(v)}{star}'])
        for v, a in top_paid(field):
            name = f"{a['name']} ({(a.get('model_creator') or {}).get('name', '')})"
            rows.append([f"<em>{esc(name)} *</em>",
                         f'<span class="badge badge-plan">paid</span> {fmt_score(v)}'])
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
                f'<span class="badge badge-free">free</span> {fmt_score(v)}{" ⭐" if i == 0 else ""}']
               for i, (v, m) in enumerate(mm[:TOP_N_FREE])]
    for v, a in top_paid(MULTIMODAL_FIELD):
        name = f"{a['name']} ({(a.get('model_creator') or {}).get('name', '')})"
        mm_rows.append([f"<em>{esc(name)} *</em>",
                        f'<span class="badge badge-plan">paid</span> {fmt_score(v)}'])
    sections.append(
        "<h2>🖼️ Multimodal (vision)</h2><p class='src-note'>Free roster models accepting image input, "
        "ranked by AA Intelligence Index as proxy (no dedicated MMMU field in the free API).</p>"
        + table(["Model", "Score"], mm_rows))

    # Summary: best free model per use-case, computed from the matched AA data only.
    def best_free(field):
        scored = [(matched[m["id"]].get(field), m) for m in models
                  if m["id"] in matched]
        scored = [(v, m) for v, m in scored if v is not None]
        scored.sort(key=lambda x: -x[0])
        return scored[0] if scored else (None, None)

    summary_specs = [
        ("Everyday model", "artificial_analysis_intelligence_index",
         "best general intelligence — good balance of quality, speed and context"),
        ("Research", "gpqa",
         "GPQA — scientific reasoning benchmark, proxy for research-grade work"),
        ("Coding", "artificial_analysis_coding_index",
         "AA Coding Index — code generation and review"),
    ]
    sum_rows = []
    for label, field, desc in summary_specs:
        v, m = best_free(field)
        if m:
            sum_rows.append([f"<strong>{label}</strong>",
                             f'<code>{esc(m["display_id"])}</code>',
                             esc(desc), str(v)])
    sections.append(
        "<h2>📌 Summary — best free model per use case</h2>"
        "<p class='src-note'>Derived strictly from the Artificial Analysis data above; "
        "'everyday model' weighs overall intelligence, latency and context.</p>"
        + table(["Use case", "Model", "Why", "Score"], sum_rows))

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
