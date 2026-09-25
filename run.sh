#!/usr/bin/env bash
# Full pipeline: generate pages, deploy to VPS. Run on the VPS via cron or by hand.
set -euo pipefail
cd "$(dirname "$0")"

# Shared with deploy-only.sh so a merge-triggered republish never runs alongside
# the daily cron build; the second process blocks here until the first exits.
exec 9>/run/lock/model-wiki.lock
flock 9

export AA_API_KEY="${AA_API_KEY:?AA_API_KEY must be set (see /etc/model-wiki.env)}"

python3 gen.py
python3 bench.py

# backup current site, then deploy
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
sudo cp -r /var/www/model-wiki "/var/www/model-wiki.bak-$STAMP"
sudo find /var/www/model-wiki -name '*.bak-*' -maxdepth 1 -mtime +14 -exec rm -rf {} + 2>/dev/null || true
sudo cp dist/index.html dist/comparisons-free-models-ranking.html dist/comparisons-benchmarks.html dist/feed.xml /var/www/model-wiki/
sudo rm -f /var/www/model-wiki/comparisons-router-changelog.html

# smoke test
sleep 1
CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/index.html)
FEED_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/feed.xml)
echo "smoke test http://127.0.0.1:8080/index.html -> $CODE; feed.xml -> $FEED_CODE"
[ "$CODE" = "200" ] && [ "$FEED_CODE" = "200" ] || { echo "DEPLOY FAILED"; exit 1; }
echo "deployed OK at $STAMP"

# publish the public free-llm-roster README (no-op until its checkout exists);
# never fatal to site generation, so it runs after the smoke test
bash publish-readme.sh
