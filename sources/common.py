"""Common model schema, ID normalization and merge logic for all sources."""

import re

# Normalized model record schema:
# {
#   "id": str,              # normalized (lowercase, no :free/-free suffix)
#   "display_id": str,      # id as reported by the first source that listed it
#   "name": str,
#   "description": str,
#   "context_length": int|None,
#   "modalities": str,      # e.g. "text", "text+image->text"
#   "tools": bool,
#   "sources": [str],       # which sources confirm it free
#   "free_basis": str,      # "price-0" | "zen-free"
# }

_SUFFIX_RE = re.compile(r"(:free|-free)$")


def normalize_id(raw_id: str) -> str:
    """Lowercase and strip :free / -free suffixes so the same model from
    different providers merges into one row."""
    return _SUFFIX_RE.sub("", raw_id.strip().lower())


def make_model(raw_id, name="", description="", context_length=None,
               modalities="text", tools=False, source="", free_basis="price-0"):
    return {
        "id": normalize_id(raw_id),
        "display_id": raw_id,
        "name": name or raw_id,
        "description": (description or "").strip(),
        "context_length": context_length,
        "modalities": modalities,
        "tools": bool(tools),
        "sources": [source] if source else [],
        "free_basis": free_basis,
    }


def is_zero_price(pricing: dict) -> bool:
    """True only when every priced field exists and is exactly 0.
    Missing pricing fields => not provably free => False."""
    if not pricing:
        return False
    try:
        return float(pricing.get("prompt")) == 0.0 and float(pricing.get("completion")) == 0.0
    except (TypeError, ValueError):
        return False


def merge(models):
    """Merge model records by normalized id; union of sources."""
    out = {}
    for m in models:
        key = m["id"]
        if key not in out:
            out[key] = dict(m)
            continue
        cur = out[key]
        for s in m["sources"]:
            if s not in cur["sources"]:
                cur["sources"].append(s)
        # prefer richer metadata
        if len(m.get("description", "")) > len(cur.get("description", "")):
            cur["description"] = m["description"]
        if m.get("context_length") and not cur.get("context_length"):
            cur["context_length"] = m["context_length"]
        if m.get("free_basis") == "price-0":
            cur["free_basis"] = "price-0"
        if not cur.get("tools") and m.get("tools"):
            cur["tools"] = True
        # keep a display_id from the most authoritative source order handled by callers
    return list(out.values())
