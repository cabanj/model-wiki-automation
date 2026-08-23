#!/usr/bin/env bash
# Cron wrapper: git pull then full pipeline. Logs to /var/log/model-wiki.log
set -euo pipefail
cd /opt/model-wiki-automation
git pull --ff-only --quiet
source /etc/model-wiki.env
./run.sh
