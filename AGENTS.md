# Repository guide

## Purpose and flow

This is a standard-library Python static-site generator for a free-model wiki, not a service. The production flow is `cron-model-wiki.sh` -> `run.sh` -> `python3 gen.py` -> `python3 bench.py`, followed by deployment to `/var/www/model-wiki`.

- `sources/` fetches and merges OpenRouter, Nous Portal, and OpenCode Zen models.
- `snapshot.py` persists `data/models.json` and `data/history.json` and computes additions/removals.
- `gen.py` writes `dist/index.html`, `dist/comparisons-free-models-ranking.html`, and `dist/feed.xml`.
- `bench.py` writes `dist/comparisons-benchmarks.html`, using Artificial Analysis live data when `AA_API_KEY` is set and `data/benchmarks-cache.json` otherwise.
- `render.py` and `render/base.css` own the shared HTML shell and styling.
- `analysis/` is historical reference material, not current generated output.

## Commands

Run from the repository root. The runtime is Python standard library; the test runner is `pytest`.

```bash
python3 gen.py
python3 bench.py
python -m pytest test_sources.py test_snapshot.py test_bench.py -v
```

Focused benchmark tests:

```bash
python -m pytest test_bench.py::test_hy3_maps_to_paid_proxy -v
python -m pytest test_bench.py::test_excluded_model_absent_from_ranking -v
```

Production-only:

```bash
bash run.sh
bash cron-model-wiki.sh
```

`run.sh` requires Linux, `AA_API_KEY`, `sudo`, `/var/www/model-wiki`, and an HTTP server on `127.0.0.1:8080`. It deploys only the three active HTML files and `feed.xml`, and removes the obsolete router changelog page. `cron-model-wiki.sh` performs `git pull --ff-only`, sources `/etc/model-wiki.env`, and expects an external cron schedule; it does not install a schedule or redirect logs despite its comment.

There is no dependency manifest, lockfile, CI configuration, or configured lint, formatter, typecheck, or source-codegen command.

## Invariants and gotchas

- Normalize IDs by lowercasing and stripping a single trailing `:free` or `-free`; merge by normalized ID and union sources.
- For OpenRouter and Nous, require both prompt and completion pricing to be exactly zero; missing or micro-pricing is rejected.
- Zen free status is curated separately; `muse-spark-1.3-contributor-free` is the explicit `zen-micro` exception. `models.dev` is metadata enrichment for Zen, not a roster source.
- Keep `AA_API_KEY` outside the repository. Benchmark API calls use the `x-api-key` header.
- `data/` and `dist/` are generated/ignored; do not hand-edit them as source. A failed source fetch can still allow generation to complete with a reduced roster and removal diff.
- `test_sources.py` contains live-network tests (`test_modelsdev_live_filter` and `test_collect_all_never_raises_and_merges`); a full-suite result is network-dependent.
- `BENCH_EXCLUDE` in `bench.py` is manually synchronized with the external router's known-broken-model list; excluded models must stay out of benchmark rankings and summaries.
