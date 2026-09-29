"""Pricing observation for models that once were free.

The roster only ever contains price==0 models, so the moment a model turns paid
it disappears from the data and the transition becomes unrecoverable. This
recorder is the side channel that keeps that evidence: fetchers call `record`
for every catalog entry they see, including the non-free ones, but only for ids
the watcher is interested in.

Deliberately a plain collector object rather than module state: fetchers take
it as an optional argument, so a call without a recorder behaves exactly as
before and two recorders never mix.
"""

from .common import normalize_id


def bare(raw_id):
    """`meta/hy3` -> `hy3`. Providers prefix catalog ids; the roster does not."""
    normalized = normalize_id(raw_id)
    return normalized.split("/", 1)[1] if "/" in normalized else normalized


class WatchRecorder:
    """Watched id -> {source: {present, pricing}} per observed fetch.

    Filtering happens on both the full id and its bare form, so a watchlist of
    `hy3` sees the `meta/hy3` catalog entry without the fetcher needing to know
    anything about provider prefixes. Slots are keyed by the watched id, which
    keeps `lookup` a plain dict read.
    """

    def __init__(self, ids=None):
        self.ids = {normalize_id(i) for i in (ids or ())}
        self._watched_bare = {bare(i) for i in self.ids}
        self.records = {}

    def _watches(self, normalized):
        if not self.ids:
            return True
        return normalized in self.ids or bare(normalized) in self._watched_bare

    def lookup(self, model_id, source):
        """Observation for a watched id on one source, or None if unseen.

        None is ambiguous on purpose: it means "this source did not tell us",
        covering both a failed fetch and a vanished entry. Callers must consult
        source health before reading anything into it.
        """
        return (self.records.get(normalize_id(model_id)) or {}).get(source)

    def record(self, raw_id, pricing, source, present=True):
        """Note that `raw_id` was seen in `source`'s catalog.

        `pricing` may be None (Zen publishes no prices) — the slot still
        records presence, which is the signal that matters when a catalog
        entry disappears.
        """
        normalized = normalize_id(raw_id)
        if not self._watches(normalized):
            return
        # With no watchlist every id is its own watch key, so the full id must
        # survive; the bare form is only ever a fallback for a prefixed entry.
        watched = bare(normalized) if normalized not in self.ids and self.ids else normalized
        self.records.setdefault(watched, {})[source] = {
            "present": present, "pricing": pricing or {}}

    def seen(self):
        return dict(self.records)
