#!/usr/bin/env bash
# Full pipeline: generate pages, deploy to VPS. Run on the VPS via cron or by hand.
set -euo pipefail
cd "$(dirname "$0")"

export AA_API_KEY="${AA_API_KEY:?AA_API_KEY must be set (see /etc/model-wiki.env)}"

python3 gen.py
python3 bench.py

# backup current site, then deploy
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
sudo cp -r /var/www/model-wiki "/var/www/model-wiki.bak-$STAMP"
sudo find /var/www/model-wiki -name '*.bak-*' -maxdepth 1 -mtime +14 -exec rm -rf {} + 2>/dev/null || true
sudo cp dist/index.html dist/comparisons-free-models-ranking.html dist/comparisons-benchmarks.html /var/www/model-wiki/

# smoke test
sleep 1
CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/index.html)
echo "smoke test http://127.0.0.1:8080 -> $CODE"
[ "$CODE" = "200" ] || { echo "DEPLOY FAILED"; exit 1; }
echo "deployed OK at $STAMP"
