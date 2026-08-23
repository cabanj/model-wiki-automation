# model-wiki automation — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task (or implement directly — tasks are small).

**Goal:** Fully automated "Free-tier model knowledge base" served from the OVH VPS (`http://135.125.233.237:8080`), refreshed on schedule, always in sync with actually-available free models and current benchmarks.

**Architecture:** Static site generator run by cron (daily 20:00 UTC). **Multiple sources of truth**, merged and deduplicated: OpenRouter API + models.dev (which also powers OpenCode's catalog) + OpenCode Zen free list + Nous Portal cache. Generator renders HTML matching the existing wiki's design; deploy script scp's to `/var/www/model-wiki`; cron on VPS pulls + regenerates daily.

**Tech Stack:** Python 3 (stdlib only or `uv`-managed), Jinja2 templates (optional — can be f-strings), OpenRouter `/api/v1/models`, git, nginx (already configured), Docker-free.

---

## Current context / assumptions

- VPS already serves 4 hand-made static pages at `/var/www/model-wiki` (index, benchmarks, free-models-ranking, MoA). Page *claims* weekly refresh but **crontab is empty**.
- Repo exists: `github.com/cabanj/model-wiki-automation` (currently only PLAN.md locally; needs first push).
- OpenRouter API is public, no key needed for the catalog; pricing fields are in the response → filtering `price == 0` is reliable ("truly free", not ":free suffix which can still have limits/pricing quirks").
- Benchmarks: no stable single API. Plan uses OpenRouter per-model metadata + links to published leaderboards; automated benchmark scraping is a v2 concern (see Open questions).
- Skill `ovh-vps` rules apply: backup before editing config, ask before opening ports/stopping services. Port 8080 already open — no changes needed.

## Requirements recap (from Jacek)

1. Wiki based on what's already on the VPS (same design/structure).
2. Only **darmowe** models — price exactly 0 (prompt AND completion), not "cheap".
3. Dynamic selection — list refreshes periodically (cron), because availability changes.
4. Stale models removed, new ones added automatically, **with descriptions**.
5. Benchmarks section: comparison against newest benchmarks, cross-referenced with the free models; **best free-tier models highlighted, paid frontier as reference**.
6. Model on existing VPS wiki style.
7. **Strict price == 0** — micro-pricing models excluded entirely.
8. Old MoA/concepts pages: **removed** — final wiki = index + ranking + benchmarks.

---

## Proposed approach

```
repo: cabanj/model-wiki-automation
├── gen.py              # fetch catalog -> filter price==0 -> diff vs data/models.json -> render HTML
├── bench.py            # benchmark data fetch/normalize -> render benchmarks page
├── templates/          # base.html, index.html, ranking.html, benchmarks.html
├── data/
│   ├── models.json     # snapshot of last generation (enables diff/changelog)
│   └── history.json    # added/removed log per run
├── deploy.sh           # scp/rsync -> /var/www/model-wiki + curl smoke test
└── cron-model-wiki.sh  # git pull && python3 gen.py && ./deploy.sh
```

Generation happens **on the VPS** (recommended): repo cloned at `/opt/model-wiki-automation`, cron runs there, no local→VPS sync problem. Local machine only pushes code.

### Refresh cadence
Weekly (Monday 20:00 UTC) matches the claim already on the page. Cron entry:
```
0 20 * * 1 cd /opt/model-wiki-automation && git pull --ff-only && ./run.sh >> /var/log/model-wiki.log 2>&1
```
(CRON ma znaczenie tylko jako trigger — sam generator jest idempotentny.)

### Free-model definition
Per source, normalized to a common schema `{id, name, description, context_length, modalities,
tools, sources: [...], free_basis: "price-0" | "zen-free" | "curated"}`:

| Source | Endpoint | Free criterion | Notes |
|---|---|---|---|
| OpenRouter | `GET https://openrouter.ai/api/v1/models` | `pricing.prompt==0 && pricing.completion==0` | verified live: 22/422 |
| models.dev | `GET https://models.dev/api.json` | `cost.input==0 && cost.output==0` | 193 providers; also powers OpenCode catalog; flag "token-plan" providers (free within subscription) separately |
| OpenCode Zen | `https://opencode.ai/zen/v1/models` + docs page | model IDs ending `-free` on the Zen list | `/v1/models` has no prices — free-ness comes from the curated Zen list |
| Nous Portal | `GET https://inference-api.nousresearch.com/v1/models` (bez auth, format OpenRouter) | `pricing.prompt==0 && pricing.completion==0` | verified live: 7/373 free; `portal.nousresearch.com/v1/models` NIE działa (Vercel checkpoint) — właściwy host to `inference-api` |

Merge rule: dedupe by normalized id; a model appears on the wiki if **any** source marks it free;
the table shows which sources confirm it (`openrouter · models.dev`). Model is removed only when
**no** source lists it as free anymore.

### Diff & changelog
Each run compares new list vs `data/models.json`. Added/removed models go into `data/history.json` and are rendered as a "Changes" section on the index page — so usunięte modele znikają ze strony, ale historia dodaje/usuwa zostaje widoczna.

### Descriptions
OpenRouter response includes `description`, `context_length`, `architecture.modality`, `supported_parameters` — rendered directly. No extra enrichment in v1 (YAGNI).

### Benchmarks (v1 — automatyczne, wzorowane na starej stronie)
Stara strona już korzystała z **Artificial Analysis API** (wyniki z "†", płatne referencje live
z tych samych danych) — czyli dostęp do AA jest wykonalny i był robiony. Odtwarzamy to:
- `bench.py` pobiera dane z Artificial Analysis API (klucz w env na VPS; fallback: curowany JSON,
  gdy AA niedostępne — generator nie może paść przez jedno źródło).
- Struktura jak na starej stronie: sekcje per kategoria — Intelligence Index, Coding, Agentic,
  Speed (throughput/TTFT), Pricing ($0 dla wszystkich), Reasoning (GPQA/HLE), Multimodal (MMMU-Pro).
- **W każdej kategorii: najlepsze modele ze free tier na górze + najlepszy model płatny jako
  referencja** (np. Claude Opus 5) — tak było na starej stronie, zachowujemy format.
- Modele free bez danych AA (np. stealth) dostają wiersz z "—" + oznaczenie braku danych.
- Cross-reference z bieżącym rostrem: model znika z benchmarków gdy przestaje być price==0;
  nowy darmowy model pojawia się automatycznie.

### Design
Reuse the existing CSS/design tokens from current `index.html` **1:1** — full template extracted
from the deployed pages (sidebar + search, header with date, TOC, table styles, pager, print styles,
dark/light). Same filenames as current site so nginx/links don't change. Analysis of old pages:
`analysis/` in repo.

### Free-model definition (STRICT)
**Cena == 0. Żadnego micro-pricing.** A model qualifies only if every priced field is exactly 0.
Models with micro-pricing (e.g. $0.0000003/1M) are **excluded from the main roster**; optionally
rendered in a clearly-labeled separate section "Near-free (micro-pricing)" — never mixed in.
`free_basis` labels: `price-0` (OpenRouter/models.dev verified), `zen-free` (limited-time),
`curated` (Nous Portal JSON).

---

## Step-by-step plan

### Task 1: Bootstrap repo
- Init git in `C:/Users/caban/projects/model-wiki-automation`, move PLAN.md content here, `.gitignore`, push to `cabanj/model-wiki-automation`.
- Verify: `git push` succeeds.

### Task 2: Source fetchers + normalizer (`sources/`)
- `sources/openrouter.py`: GET catalog, filter `pricing==0`.
- `sources/modelsdev.py`: GET `models.dev/api.json`, filter `cost==0`; mark token-plan providers.
- `sources/opencode_zen.py`: GET Zen `/v1/models`, intersect with `-free` IDs from docs list.
- `sources/nous_portal.py`: GET `https://inference-api.nousresearch.com/v1/models` (OpenRouter-compatible format, same filter as OpenRouter).
- Common `normalize()` → shared schema; merge + dedupe by id, track `sources` list.
- Tests: offline fixtures per source (paid/free/missing-pricing), merge test (same model in 2 sources → 1 row, sources=[or, md]).

### Task 3: Snapshot + diff (`data/models.json`, history)
- On each run: load previous snapshot, compute `added` / `removed`, write new snapshot + append history.
- Test: two sequential fake runs → correct diff output.

### Task 4: Templates + renderer
- Extract design tokens/CSS from current VPS `index.html` into `templates/base.html`.
- Pages: `index.html` (overview + changelog), `comparisons-free-models-ranking.html` (table: name, id, context, modalities, description, params/tools support).
- Keep same filenames as current site so nginx/links don't change.

### Task 5: Benchmarks page (`bench.py`)
- Fetch from Artificial Analysis API — verified: `GET https://artificialanalysis.ai/api/v2/data/llms/models` with header `x-api-key: <AA_API_KEY>` (env on VPS, never in repo); returns intelligence/coding/agentic indexes + GPQA/HLE/MMLU-Pro etc.
- Cache last-good data to `data/benchmarks-cache.json` as fallback.
- Sections per category (Intelligence, Coding, Agentic, Speed, Pricing, Reasoning, Multimodal): top free-tier models + one paid reference model each.
- Renderer marks FREE rows; missing AA data → "—".

### Task 6: Deploy script (`deploy.sh`)
- `scp -r dist/* ovh-fra:/var/www/model-wiki/` (backup old dir first: `cp -r` to timestamped backup per skill rules).
- Smoke test: `curl -s http://135.125.233.237:8080/ | grep -c "<title>"`.

### Task 7: VPS setup
- Clone repo to `/opt/model-wiki-automation` on ovh-fra.
- Install cron entry (ask Jacek before adding crontab — skill rule about production box).
- Log rotation note: simple `>> /var/log/model-wiki.log` + logrotate entry or size guard.

### Task 8: First real run + verification
- Run generator manually on VPS, deploy, verify pages load, count of free models matches live API (~22 today).
- Compare visually with old site (open preview).

---

## Files likely to change

- Local repo: everything above (new project).
- VPS: `/opt/model-wiki-automation` (new clone), root crontab (currently empty — one line added after asking), nothing else. No nginx changes (filenames kept identical).

## Tests / validation

- Unit tests for filter/diff/badge logic (pytest, fixtures offline).
- Integration: end-to-end run produces HTML containing ≥1 model row and changelog section.
- Deploy smoke test via curl.
- Manual: Jacek opens http://135.125.233.237:8080 and confirms look/content.

## Risks / tradeoffs

- **Multi-source merge**: normalization by ID across sources isn't perfect (e.g. `nvidia/x:free` vs `nvidia/x`); plan includes a normalization step (strip `:free`/`-free` suffixes, lowercase) + manual alias map if needed. Residual risk: occasional duplicate rows — acceptable, fixable via aliases.
- **"Free" semantics differ per source**: OpenRouter = truly $0; models.dev has subscription-plan providers where cost 0 means "within your plan"; Zen free models are "limited time". Wiki will label the basis per model so nobody is misled.
- **OpenRouter as single source**: ~~removed~~ — now mitigated by 4 sources; if one source is down, generator continues with the rest (per-source try/except, page shows source status/timestamps).
- **Benchmarks**: AA key lives in VPS env only (verified working); fallback cache when AA down.
- **Opisy**: opis z API jako baza; gdy brak — placeholder, nie halucynacja (stara strona
  dopisywała własne opisy; my trzymamy się danych źródłowych + opcjonalna curacja).
- **Cron on VPS = another thing to maintain**: log file growth; mitigated with logrotate line.
- **Free ≠ unlimited**: OpenRouter free tier has rate limits (e.g. 200 req/day); page should state this so nobody assumes infinite capacity.

## Open questions (do refinementu)

1. Cadence: **daily** ✅ (20:00 UTC)
2. Generowanie na VPS: **tak** ✅
3. Benchmarki: **AA API w v1** ✅ — klucz dostarczony i **zweryfikowany** (`x-api-key` header,
   endpoint `/api/v2/data/llms/models` zwraca 200 z intelligence/coding/GPQA/HLE itd.);
   klucz NIE trafia do repo ani planu — tylko env na VPS
4. Nous Portal: curowany JSON w repo (otwarte: ewentualny endpoint)
5. Stare strony MoA / concepts: **usunąć** ✅ — wiki to index + ranking + benchmarki
6. Micro-pricing: **strict cena==0, całkiem wyciąć** ✅ — żadnej sekcji "near-free"
