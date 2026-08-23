# model-wiki automation

Cel: w pełni zautomatyzowana strona "Free-tier model knowledge base" na VPS OVH
(`http://135.125.233.237:8080`, web root `/var/www/model-wiki`).

## Stan wyjściowy (audyt 2026-08-22)
- 4 statyczne strony HTML (index, benchmarks, free-models-ranking, MoA) — ~104 KB, ręcznie robione
- Na stronie deklarowany "weekly refresh Monday 20:00 UTC" — **ale cron nie istnieje** (crontab pusty)
- Źródła danych wg opisu na stronie: OpenRouter catalog, Hermes `model_catalog.json`,
  `provider_models_cache.json`, Nous Portal cache — **żadnych skryptów na VPS, brak repo**
- Stara strona ma linki `href="#"` (martwe wikilinki)

## Założenia (KISS/YAGNI)
1. **Statyczny generator**, nie serwis — cron raz w tygodniu > daemon 24/7
2. **Repo na GitHubie** (`cabanj/model-wiki-automation`), VPS tylko hostuje i odpala cron
3. Źródło prawdy o darmowych modelach: **OpenRouter API** (`/api/v1/models`, publiczne,
   pricing w odpowiedzi) — jedno źródło zamiast czterech; rozszerzenia później (YAGNI)
4. Output: ranking HTML + index; benchmarki/MoA zostają jako statyczne strony

## Architektura (plan)
```
gen.py          # pobiera OpenRouter catalog -> filtruje price==0 -> renderuje HTML
templates/      # szablony stron
deploy.sh       # rsync/scp -> /var/www/model-wiki + curl smoke test
cron na VPS     # poniedziałek 20:00 UTC: git pull && gen.py && deploy
```

## Otwarte decyzje (do sesji z skillem ovh-vps)
- [ ] Generowanie NA VPS (rekomendowane) czy lokalnie + push
- [ ] Zakres v1: sam ranking free models z OpenRouter
- [ ] Styl strony: odświeżyć obecny design czy zostawić

## Infrastruktura projektu
- Repo: https://github.com/cabanj/model-wiki-automation
- Git identity skonfigurowany: Jacek (cabanj) / 14554726+cabanj@users.noreply.github.com
- Auth: HTTPS + Windows Credential Manager (PAT, scopes: repo workflow copilot project)
