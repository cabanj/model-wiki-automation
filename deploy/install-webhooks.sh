#!/usr/bin/env bash
# Install the webhook service on the VPS. Idempotent.
#
# Two units, not one: the API must stay responsive while deliveries happen, and
# a single ten-second POST to a slow subscriber would otherwise block a
# subscription registration. They share only the SQLite file.
set -euo pipefail

# Where the unit files are read from. Override with WH_SOURCE to install from a
# worktree or another checkout; it must contain deploy/*.service.
REPO=/opt/model-wiki-automation
SOURCE=${WH_SOURCE:-$REPO}
STATE=/etc/roster-webhooks.env
DATA=/var/lib/roster-webhooks

for unit in roster-webhooks-api.service roster-webhooks-dispatch.service; do
  [ -f "$SOURCE/deploy/$unit" ] || {
    echo "ERROR: $SOURCE/deploy/$unit not found." >&2
    echo "Pass WH_SOURCE=<checkout> if the units live elsewhere." >&2
    exit 1
  }
done

echo "== state directory =="
mkdir -p "$DATA"
chmod 750 "$DATA"

if [ ! -f "$STATE" ]; then
  ADMIN_TOKEN=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  umask 077
  cat > "$STATE" <<EOF
# Secrets for the roster webhook service. Never in the repository.
# Read by both roster-webhooks-api.service and roster-webhooks-dispatch.service.
ROSTER_WEBHOOK_ADMIN_TOKEN=$ADMIN_TOKEN
EOF
  chmod 600 "$STATE"
  echo "created $STATE"
else
  echo "$STATE exists, keeping it"
fi

install -m 0644 "$SOURCE/deploy/roster-webhooks-api.service" /etc/systemd/system/roster-webhooks-api.service
install -m 0644 "$SOURCE/deploy/roster-webhooks-dispatch.service" /etc/systemd/system/roster-webhooks-dispatch.service

systemctl daemon-reload
systemctl enable --now roster-webhooks-api.service
systemctl enable --now roster-webhooks-dispatch.service

sleep 2
echo "== status =="
systemctl --no-pager --lines=0 status roster-webhooks-api.service || true
systemctl --no-pager --lines=0 status roster-webhooks-dispatch.service || true

echo
echo "== smoke =="
curl -s http://127.0.0.1:8090/api/v1/health || echo "API not answering"
echo
echo "Admin token: sudo grep ROSTER_WEBHOOK_ADMIN_TOKEN $STATE"
