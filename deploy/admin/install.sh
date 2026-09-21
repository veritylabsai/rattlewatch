#!/usr/bin/env bash
# Install the Rattlewatch admin dashboard on the edge host.
#
# Idempotent. Does NOT set the admin password - use set-password.sh for that,
# so the secret never appears in shell history or a process list.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEBROOT=/var/www/rattlewatch-admin
BIN=/usr/local/bin/rattlewatch-dashboard
UNITDIR=/etc/systemd/system
HTPASSWD=/etc/nginx/rattlewatch.htpasswd

echo "[install] webroot ${WEBROOT}"
sudo install -d -o notmy -g notmy -m 0755 "${WEBROOT}"

echo "[install] generator -> ${BIN}"
sudo install -o root -g root -m 0755 "${HERE}/build_dashboard.py" "${BIN}"

echo "[install] systemd units"
sudo install -o root -g root -m 0644 "${HERE}/rattlewatch-dashboard.service" "${UNITDIR}/"
sudo install -o root -g root -m 0644 "${HERE}/rattlewatch-dashboard.timer"   "${UNITDIR}/"
sudo systemctl daemon-reload

if [ ! -f "${HTPASSWD}" ]; then
  echo "[install] WARNING: ${HTPASSWD} does not exist yet."
  echo "[install]          Run set-password.sh before exposing /admin/."
fi

echo "[install] building the dashboard once"
sudo systemctl start rattlewatch-dashboard.service

echo "[install] enabling the timer"
sudo systemctl enable --now rattlewatch-dashboard.timer
sudo systemctl list-timers rattlewatch-dashboard.timer --no-pager | head -3

echo
echo "[install] service result:"
sudo systemctl is-active rattlewatch-dashboard.service || true
ls -la "${WEBROOT}"
