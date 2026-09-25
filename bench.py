#!/usr/bin/env python3
"""Generate the Artificial Analysis comparison page."""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render
from render import esc, fmt_ts, model_id, page, table
from snapshot import load_snapshot

AA_URL = ("https://artificialanalysis.ai/api/v2/data/llms/models"
          "?fields=model_name,creator_name,intelligence_index,coding_index,agentic_index,"
          "evaluations,gpqa,terminalbench_hard,median_output_tokens_per_second,"
          "median_time_to_first_token_seconds")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "benchmarks-cache.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", "comparisons-benchmarks.html")

CATEGORIES = [
    ("Overall intelligence", "artificial_analysis_intelligence_index",
     "AA Intelligence Index — general knowledge, reasoning, agents, and scientific performance."),
    ("Coding", "artificial_analysis_coding_index",
     "AA Coding Index — code generation, completion, and review."),
    ("Agentic coding / terminal", "terminalbench_hard",
     "Terminal-Bench Hard — agentic terminal usage, tool use, and multi-step workflows."),
    ("Scientific reasoning", "gpqa",
     "GPQA Diamond — graduate-level scientific reasoning benchmark."),
]
CATEGORY_IDS = {
    "Overall intelligence": "overall-intelligence",
    "Coding": "coding",
    "Agentic coding / terminal": "agentic-terminal",
    "Scientific reasoning": "scientific-reasoning",
}
PERCENT_FIELDS = {"gpqa", "terminalbench_hard"}
MULTIMODAL_FIELD = "artificial_analysis_intelligence_index"
TOP_N = 3


def is_multimodal(m):
    return "image" in (m.get("modalities") or "")


def fetch_aa():
    key = os.environ.get("AA_API_KEY")
    if not key:
        return None, "AA_API_KEY not set"
    req = urllib.request.Request(
        AA_URL, headers={"x-api-key": key, "User-Agent": "model-wiki-automation/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode())
        for entry in data.get("data", []):
            entry.update(entry.pop("evaluations", None) or {})
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return data["data"], ""
    except Exception as error:
        return None, str(error)


def load_cached():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)["data"]
    return []


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
    "nvidia/nemotron-nano-9b-v2": "Nemotron Nano 9B v2 (Non-reasoning)",
    "stepfun/step-3.7-flash": "Step 3.7 Flash",
    "thinkingmachines/inkling": "Inkling (xhigh)",
    "thinkingmachines/inkling-small": "Inkling Small",
    "tencent/hy3": "Hy3",
    "muse-spark-1.2-contributor": "Muse Spark 1.2 (xhigh)",
}

BENCH_EXCLUDE = frozenset({
    "z-ai/glm-5.2",
})


def is_paid_proxy(aa_entry):
    if not aa_entry:
        return False
    return float((aa_entry.get("pricing") or {}).get("price_1m_blended_3_to_1", 0) or 0) > 0


def proxy_mark(aa_entry):
    return "‡" if is_paid_proxy(aa_entry) else ""


def match_free(free_models, aa_models):
    def sig_tokens(value):
        return {token for token in _split(value.lower())
                if len(token) >= 3 and not token.replace(".", "").isdigit()}

    aa_entries = []
    for entry in aa_models:
        name = entry.get("name") or ""
        aa_entries.append((sig_tokens(name), name, entry))

    matched = {}
    by_name = {entry.get("name", ""): entry for _, _, entry in aa_entries}
    for model in free_models:
        model_key = model["id"]
        if model_key in AA_ALIASES and AA_ALIASES[model_key] in by_name:
            matched[model_key] = by_name[AA_ALIASES[model_key]]
            continue
        base = model_key.split("/")[-1]
        model_tokens = {token for token in sig_tokens(base)
                        if token not in ("preview", "free", "stealth", "contributor", "reasoning")}
        best, best_score = None, 0
        for tokens, _, entry in aa_entries:
            score = len(model_tokens & tokens)
            if score > best_score:
                best, best_score = entry, score
        if best and best_score >= 2:
            matched[model_key] = best
    return matched


def _split(value):
    for character in "-_/().,: ":
        value = value.replace(character, " ")
    return [token for token in value.split() if token and token not in ("the", "by")]


def rank_free_for_field(free_models, aa_models, field, top_n=3, predicate=None):
    candidates = free_models if predicate is None else [m for m in free_models if predicate(m)]
    matched = match_free(candidates, aa_models)
    scored = [(matched[m["id"]].get(field), m) for m in candidates
              if m["id"] not in BENCH_EXCLUDE and m["id"] in matched]
    scored = [(value, model) for value, model in scored if value is not None]
    scored.sort(key=lambda item: -float(item[0]))
    return scored[:top_n]


def top_paid(aa_models, field, n=1):
    scored = [(entry.get(field), entry) for entry in aa_models
              if entry.get(field) is not None
              and float((entry.get("pricing") or {}).get("price_1m_blended_3_to_1", 0) or 0) > 0]
    scored.sort(key=lambda item: -float(item[0]))
    return scored[:n]


def fmt_score(value, field=None):
    numeric = float(value)
    if 0 <= numeric <= 1 and field in PERCENT_FIELDS:
        return f"{numeric * 100:.1f}%"
    if 0 <= numeric <= 1:
        return f"{numeric:.2f}"
    return f"{numeric:.2f}"


def score_cell(value, field, model=None, entry=None, best=False):
    mark = ""
    if model is not None:
        mark = proxy_mark(entry)
    star = '<span class="star" aria-label="Best free model">★</span>' if best else ""
    label = f'<span class="proxy-label">paid proxy</span>' if mark else ""
    return f'<span class="score-cell">{fmt_score(value, field)}{mark}{star}</span>{label}'


def render(models, generated_at, use_cache=False):
    if use_cache:
        # Explicit cache reuse (deploy-only.sh): the merge changed code, not data.
        aa_data, error = load_cached(), ""
        from_cache = bool(aa_data)
    else:
        aa_data, error = fetch_aa()
        from_cache = False
    if aa_data is None:
        aa_data = load_cached()
        from_cache = bool(aa_data)
    matched = match_free(models, aa_data)

    if use_cache and from_cache:
        source_note = "Cached Artificial Analysis data (republished without a live fetch)"
    elif error and from_cache:
        source_note = "Cached benchmark data; live fetch unavailable"
    elif error:
        source_note = "Benchmark data unavailable; no cached result was found"
    else:
        source_note = "Live Artificial Analysis data"
    source_note = f"{source_note} ({esc(error[:80])})" if error else source_note

    summary_specs = [
        ("Everyday model", "artificial_analysis_intelligence_index", None,
         "Highest general intelligence score in the current free roster."),
        ("Research", "gpqa", None, "Highest GPQA score in the current free roster."),
        ("Coding", "artificial_analysis_coding_index", None,
         "Highest coding score in the current free roster."),
        ("Vision", MULTIMODAL_FIELD, is_multimodal,
         "Highest intelligence score among free models accepting image input."),
    ]
    summary_cards = []
    for label, field, predicate, rationale in summary_specs:
        ranked = rank_free_for_field(models, aa_data, field, top_n=1, predicate=predicate)
        if not ranked:
            continue
        value, model = ranked[0]
        summary_cards.append(
                f'<article class="summary-card"><h3>{esc(label)}</h3>'
            f'<span class="summary-model">{model_id(model.get("display_id", model["id"]))}</span>'
            f'<span class="summary-score">{score_cell(value, field, model, matched.get(model["id"]))}</span>'
            f'<p>{esc(rationale)}</p></article>')
    summary_html = "".join(summary_cards)

    sections = []
    for title, field, description in CATEGORIES:
        rows = []
        for index, (value, model) in enumerate(rank_free_for_field(models, aa_data, field, TOP_N)):
            rows.append([
                model_id(model.get("display_id", model["id"])),
                f'<span class="badge badge-free">Free</span> {score_cell(value, field, model, matched.get(model["id"]), best=index == 0)}',
            ])
        for value, entry in top_paid(aa_data, field):
            name = entry["name"]
            creator = (entry.get("model_creator") or {}).get("name", "")
            rows.append([
                f'<span class="paid-model">{esc(name)}<span class="model-creator">{esc(creator)}</span></span>',
                f'<span class="badge badge-paid">Paid reference</span> <span class="score-cell">{fmt_score(value, field)}</span>',
            ])
        no_data_count = sum(1 for model in models
                            if model["id"] not in BENCH_EXCLUDE
                            and (matched.get(model["id"]) or {}).get(field) is None)
        omitted = f' {no_data_count} roster models without this metric are omitted.' if no_data_count else ""
        sections.append(
            f'<section class="benchmark-section" aria-labelledby="{CATEGORY_IDS[title]}">'
            f'<h2 id="{CATEGORY_IDS[title]}">{esc(title)}</h2>'
            f'<p>{esc(description)}{esc(omitted)}</p>'
            f'{table(["Model", "Score"], rows, caption=f"{title} free models and paid reference", row_header=0)}'
            '</section>')

    multimodal = []
    for index, (value, model) in enumerate(
            rank_free_for_field(models, aa_data, MULTIMODAL_FIELD, TOP_N, predicate=is_multimodal)):
        multimodal.append([
            f'<code class="model-id">{esc(model.get("display_id", model["id"]))}</code>',
            f'<span class="badge badge-free">Free</span> {score_cell(value, MULTIMODAL_FIELD, model, matched.get(model["id"]), best=index == 0)}',
        ])
    for value, entry in top_paid(aa_data, MULTIMODAL_FIELD):
        name = entry["name"]
        creator = (entry.get("model_creator") or {}).get("name", "")
        multimodal.append([
            f'<span class="paid-model">{esc(name)}<span class="model-creator">{esc(creator)}</span></span>',
            f'<span class="badge badge-paid">Paid reference</span> <span class="score-cell">{fmt_score(value, MULTIMODAL_FIELD)}</span>',
        ])
    sections.append(
        f'<section class="benchmark-section" aria-labelledby="vision-benchmark">'
        f'<h2 id="vision-benchmark">Vision / multimodal</h2>'
        f'<p>Free models accepting image input, ranked by the AA Intelligence Index because the public AA dataset has no dedicated MMMU field.</p>'
        f'{table(["Model", "Score"], multimodal, caption="Vision-capable free models and paid reference", row_header=0)}'
        '</section>')

    body = f'''<div class="page-body">
<section class="page-head">
  <span class="eyebrow">Decision guide · free roster vs paid frontier</span>
  <h1>Benchmarks</h1>
  <p class="lead">Start with the best free model for a common task, then inspect category detail against one paid reference model. Scores use the public Artificial Analysis dataset.</p>
</section>
<div class="provenance"><span><strong>Data source:</strong> {source_note}</span><span>Last generated: <strong>{fmt_ts(generated_at)}</strong></span></div>
<p class="src-note"><strong>Reading the scores:</strong> ‡ and “paid proxy” mean the free roster model has no free-variant AA record, so the paid variant is shown as a clearly labelled proxy. It is not a free-tier measurement.</p>
<div class="summary-grid">{summary_html}</div>
{''.join(sections)}
</div>'''
    return page("Benchmarks", "comparisons-benchmarks.html", body, generated_at)


def main():
    use_cache = "--use-cache" in sys.argv[1:]
    snap = load_snapshot()
    models = snap["models"] if snap else []
    generated_at = snap["generated_at"] if snap else ""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(models, generated_at, use_cache=use_cache))
    print(f"benchmarks written ({len(models)} roster models)")


if __name__ == "__main__":
    main()
