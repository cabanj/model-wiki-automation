"""Source fetchers. Each returns a list of normalized model records.
Each fetch_* never raises on network failure — it returns ([], error_string)."""

import json
import re
import urllib.request

from .common import make_model, is_zero_price, normalize_id

UA = {"User-Agent": "model-wiki-automation/1.0"}
TIMEOUT = 30


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _result(models, err=""):
    return models, err


# --- OpenRouter -------------------------------------------------------------

def fetch_openrouter():
    try:
        data = _get_json("https://openrouter.ai/api/v1/models")["data"]
    except Exception as e:
        return [], f"openrouter: {e}"
    models = []
    for m in data:
        if not is_zero_price(m.get("pricing")):
            continue
        arch = m.get("architecture") or {}
        models.append(make_model(
            m["id"], m.get("name", ""), m.get("description", ""),
            (m.get("top_provider") or {}).get("context_length") or m.get("context_length"),
            arch.get("modality", "text"),
            "tools" in (m.get("supported_parameters") or []),
            source="openrouter"))
    return models, ""


# --- Nous Portal (inference API, OpenRouter-compatible) ----------------------

def fetch_nous_portal():
    try:
        data = _get_json("https://inference-api.nousresearch.com/v1/models")["data"]
    except Exception as e:
        return [], f"nous: {e}"
    models = []
    for m in data:
        if not is_zero_price(m.get("pricing")):
            continue
        arch = m.get("architecture") or {}
        models.append(make_model(
            m["id"], m.get("name", ""), m.get("description", ""),
            (m.get("top_provider") or {}).get("context_length") or m.get("context_length"),
            arch.get("modality", "text"),
            "tools" in (m.get("supported_parameters") or []),
            source="nous"))
    return models, ""


# --- models.dev ---------------------------------------------------------------

# Providers whose catalog represents subscription plans ("$0 within your plan"),
# not truly free APIs. Flagged via free_basis so the UI can label them.
_PLAN_PROVIDER_RE = re.compile(r"(token-plan|coding-plan|subscription)", re.I)


def fetch_modelsdev():
    try:
        providers = _get_json("https://models.dev/api.json")
    except Exception as e:
        return [], f"models.dev: {e}"
    models = []
    for pid, prov in providers.items():
        plan = bool(_PLAN_PROVIDER_RE.search(pid))
        for mid, m in (prov.get("models") or {}).items():
            cost = m.get("cost") or {}
            if not is_zero_price({"prompt": cost.get("input"), "completion": cost.get("output")}):
                continue
            models.append(make_model(
                mid, m.get("name", ""), "", m.get("limit", {}).get("context"),
                ",".join(m.get("modalities") or ["text"]) if m.get("modalities") else "text",
                bool((m.get("capabilities") or {}).get("tool_call")),
                source="models.dev",
                free_basis="plan" if plan else "price-0"))
    return models, ""


# --- OpenCode Zen --------------------------------------------------------------

# Zen /v1/models has no pricing; free-ness comes from the curated Zen docs list
# (IDs ending in -free). Kept here; update when OpenCode changes the roster.
ZEN_FREE_IDS = [
    "x-preview-f-free", "mimo-v2.5-free", "hy3-free", "nemotron-3-ultra-free",
    "nemotron-3.5-lightning-free", "muse-spark-1.2-contributor-free",
]


def fetch_opencode_zen():
    try:
        data = _get_json("https://opencode.ai/zen/v1/models")["data"]
    except Exception as e:
        return [], f"zen: {e}"
    listed = {m["id"] for m in data}
    models = []
    for mid in ZEN_FREE_IDS:
        if mid in listed or normalize_id(mid) in {normalize_id(x) for x in listed}:
            models.append(make_model(mid, description="", source="opencode-zen",
                                     free_basis="zen-free"))
    missing = [m for m in ZEN_FREE_IDS if normalize_id(m) not in {normalize_id(m2["id"]) for m2 in data}]
    err = "" if not missing else f"zen: gone from live list: {missing}"
    return models, err


ALL_SOURCES = [
    ("openrouter", fetch_openrouter),
    ("nous", fetch_nous_portal),
    ("models.dev", fetch_modelsdev),
    ("opencode-zen", fetch_opencode_zen),
]


def collect_all():
    """Fetch all sources; returns (merged_models, statuses).
    A failing source never blocks the rest."""
    from .common import merge
    merged, statuses = [], {}
    for name, fn in ALL_SOURCES:
        models, err = fn()
        statuses[name] = {"ok": not err.startswith(name.split(":")[0]) and err == "",
                          "count": len(models), "error": err}
        merged.extend(models)
    return merge(merged), statuses
