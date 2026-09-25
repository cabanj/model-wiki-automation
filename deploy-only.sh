#!/usr/bin/env bash
# Republish with current code, unchanged data. Triggered by GitHub Actions on
# merge to main. Does NOT fetch sources, does NOT touch data/models.json or
# data/history.json, and needs no AA_API_KEY — the daily cron owns data refresh.
# Shares run.sh's lock so a merge landing during the 18:00 UTC cron run waits.
set -euo pipefail
cd "$(dirname "$0")"

LOCK=/run/lock/model-wiki.lock
exec 9>"$LOCK"
flock 9

# Rebuild from the last snapshot so new render/base.css is actually published.
python3 gen.py --from-snapshot
python3 bench.py --use-cache

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
sudo cp -r /var/www/model-wiki "/var/www/model-wiki.bak-$STAMP"
sudo find /var/www/model-wiki -name '*.bak-*' -maxdepth 1 -mtime +14 -exec rm -rf {} + 2>/dev/null || true
sudo cp dist/index.html dist/comparisons-free-models-ranking.html dist/comparisons-benchmarks.html dist/feed.xml dist/privacy.html dist/contact.html /var/www/model-wiki/
sudo rm -f /var/www/model-wiki/comparisons-router-changelog.html

sleep 1
CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/index.html)
FEED_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/feed.xml)
BENCH_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/comparisons-benchmarks.html)
echo "smoke test index.html -> $CODE; feed.xml -> $FEED_CODE; benchmarks -> $BENCH_CODE"
[ "$CODE" = "200" ] && [ "$FEED_CODE" = "200" ] && [ "$BENCH_CODE" = "200" ] || { echo "DEPLOY FAILED"; exit 1; }
echo "republished OK at $STAMP"
