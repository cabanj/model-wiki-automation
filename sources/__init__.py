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
        # subscription-plan providers ("$0 within your plan") are NOT truly
        # free APIs — excluded entirely per strict price==0 policy
        if _PLAN_PROVIDER_RE.search(pid):
            continue
        for mid, m in (prov.get("models") or {}).items():
            cost = m.get("cost") or {}
            if not is_zero_price({"prompt": cost.get("input"), "completion": cost.get("output")}):
                continue
            models.append(make_model(
                mid, m.get("name", ""), "", m.get("limit", {}).get("context"),
                ",".join(m.get("modalities") or ["text"]) if m.get("modalities") else "text",
                bool((m.get("capabilities") or {}).get("tool_call")),
                source="models.dev",
                free_basis="price-0"))
    return models, ""


# --- OpenCode Zen --------------------------------------------------------------

# Zen /v1/models has no pricing; free-ness comes from the curated Zen docs list
# (IDs ending in -free). Kept here; update when OpenCode changes the roster.
ZEN_FREE_IDS = [
    "x-preview-f-free", "mimo-v2.5-free", "hy3-free", "nemotron-3-ultra-free",
    "nemotron-3.5-lightning-free", "muse-spark-1.2-contributor-free",
    "muse-spark-1.3-contributor-free",
]

# Explicit micro-price exemptions (normalized ids): free on Zen, micro-priced
# on OpenRouter. Shown with a distinct badge, never silently as $0.
ZEN_MICRO_EXEMPT = frozenset({
    normalize_id("muse-spark-1.3-contributor-free"),
})


def _zen_basis(mid, price):
    """free_basis for a Zen-curated id, or None to reject from the roster."""
    if price is None or is_zero_price(price):
        return "zen-free"
    if normalize_id(mid) in ZEN_MICRO_EXEMPT:
        return "zen-micro"
    return None


def fetch_opencode_zen():
    try:
        data = _get_json("https://opencode.ai/zen/v1/models")["data"]
    except Exception as e:
        return [], f"zen: {e}"
    listed = {m["id"] for m in data}
    # Zen /v1/models has no descriptions or prices — enrich from models.dev
    # (description-only lookup, models.dev is NOT a roster source) AND
    # verify zero pricing via OpenRouter API (Zen models are also listed there).
    desc_by_id = _zen_descriptions_from_modelsdev()
    or_pricing = _openrouter_pricing()
    models = []
    for mid in ZEN_FREE_IDS:
        if mid not in listed and normalize_id(mid) not in {normalize_id(x) for x in listed}:
            continue
        # strict price==0 check (1.2-contributor rejected here: micro-priced);
        # try both bare id and with known prefixes (OpenRouter may prefix with provider)
        price = or_pricing.get(normalize_id(mid))
        if price is None:
            price = or_pricing.get("meta/" + normalize_id(mid))
        basis = _zen_basis(mid, price)
        if basis is None:
            continue
        models.append(make_model(mid,
                                 description=desc_by_id.get(normalize_id(mid), ""),
                                 context_length=desc_by_id.get("_ctx:" + normalize_id(mid)),
                                 source="opencode-zen",
                                 free_basis=basis))
    missing = [m for m in ZEN_FREE_IDS if normalize_id(m) not in {normalize_id(m2["id"]) for m2 in data}]
    err = "" if not missing else f"zen: gone from live list: {missing}"
    return models, err


def _openrouter_pricing():
    """Map normalized model id -> pricing dict, from OpenRouter catalog."""
    try:
        data = _get_json("https://openrouter.ai/api/v1/models")["data"]
    except Exception:
        return {}
    return {normalize_id(m["id"]): m.get("pricing") for m in data}


def _zen_descriptions_from_modelsdev():
    """Description enrichment only: id -> description (and _ctx:id -> context)."""
    try:
        providers = _get_json("https://models.dev/api.json")
    except Exception:
        return {}
    out = {}
    for prov in providers.values():
        for mid, m in (prov.get("models") or {}).items():
            key = normalize_id(mid)
            d = (m.get("description") or "").strip()
            ctx = (m.get("limit") or {}).get("context")
            if d and key not in out:
                out[key] = d
            if ctx and ("_ctx:" + key) not in out:
                out["_ctx:" + key] = ctx
    return out


ALL_SOURCES = [
    ("openrouter", fetch_openrouter),
    ("nous", fetch_nous_portal),
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
