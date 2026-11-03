#!/usr/bin/env bash
# Install the ISMAS agent as a systemd service on a monitored server.
# Usage: sudo ./deploy/agent/install.sh <server-name> <ingest-url> <agent-token>
#   e.g. sudo ./deploy/agent/install.sh web-01 https://brain.tailXXXX.ts.net/webhook/ismas-ingest <token>
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
[ $# -eq 3 ] || { sed -n 2,4p "$0"; exit 1; }
NAME=$1; URL=$2; TOKEN=$3
SRC="$(cd "$(dirname "$0")/../../agent" && pwd)"
DEST=/opt/ismas/agent

mkdir -p /opt/ismas /var/lib/ismas-agent
rm -rf "$DEST"; cp -r "$SRC" "$DEST"
python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install -q -r "$DEST/requirements.txt"

[ -f "$DEST/configs/$NAME.yaml" ] || echo "WARN: no configs/$NAME.yaml, agent will use default.yaml (syslog/auth.log only)"

umask 077
cat > /etc/ismas-agent.env <<ENV
SERVER_NAME=$NAME
INGEST_URL=$URL
AGENT_TOKEN=$TOKEN
AGENT_DRY_RUN=${AGENT_DRY_RUN:-1}
ENV

cat > /etc/systemd/system/ismas-agent.service <<'UNIT'
[Unit]
Description=ISMAS agent
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=/etc/ismas-agent.env
ExecStart=/opt/ismas/agent/.venv/bin/python /opt/ismas/agent/agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now ismas-agent
echo "Started in DRY-RUN mode. Check: journalctl -u ismas-agent -f"
echo "When payloads look right: sed -i 's/AGENT_DRY_RUN=1/AGENT_DRY_RUN=0/' /etc/ismas-agent.env && systemctl restart ismas-agent"
