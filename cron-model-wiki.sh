#!/usr/bin/env bash
# Cron wrapper: git pull then full pipeline. Logs to /var/log/model-wiki.log
# Self-heal: ensure run.sh is executable after `git pull` (git doesn't track +x).
set -euo pipefail
cd "$(dirname "$0")"
chmod +x run.sh cron-model-wiki.sh 2>/dev/null || true
git pull --ff-only --quiet
set -a
. /etc/model-wiki.env
set +a
exec ./run.sh
