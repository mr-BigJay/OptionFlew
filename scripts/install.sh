#!/usr/bin/env bash
# OptionFlow VPS one-line installer:
#   curl -fsSL https://raw.githubusercontent.com/mr-BigJay/OptionFlew/cursor/optionflow-guide-9890/scripts/install.sh | bash
set -euo pipefail

INSTALL_DIR="${OPTIONFLOW_DIR:-$HOME/optionflow-dashboard}"
REPO="${OPTIONFLOW_REPO:-https://github.com/mr-BigJay/OptionFlew.git}"
BRANCH="${OPTIONFLOW_BRANCH:-cursor/optionflow-guide-9890}"
PORT="${OPTIONFLOW_PORT:-8080}"
INTERVAL_HOURS="${OPTIONFLOW_INTERVAL_HOURS:-2}"
WINDOW_HOURS="${OPTIONFLOW_WINDOW_HOURS:-2}"

echo "==> OptionFlow Dashboard installer"
echo "    Directory: $INSTALL_DIR"

if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "==> Updating existing install..."
  git -C "$INSTALL_DIR" fetch origin "$BRANCH" --depth 1
  git -C "$INSTALL_DIR" checkout "$BRANCH"
  git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
else
  echo "==> Cloning repository..."
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip -q
pip install -r requirements.txt -q

mkdir -p "$INSTALL_DIR/data"

ENV_FILE="$INSTALL_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<EOF
OPTIONFLOW_DATA=$INSTALL_DIR/data
OPTIONFLOW_PORT=$PORT
OPTIONFLOW_INTERVAL_HOURS=$INTERVAL_HOURS
OPTIONFLOW_WINDOW_HOURS=$WINDOW_HOURS
EOF
fi

SERVICE_NAME="optionflow-dashboard.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
if [[ "$(id -u)" -eq 0 ]]; then
  cat > "$SERVICE_PATH" <<EOF
[Unit]
Description=OptionFlow BTC Options Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$INSTALL_DIR/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  echo ""
  echo "✓ Service started: systemctl status $SERVICE_NAME"
else
  echo "==> Not root — starting in background with nohup (use sudo bash for systemd)"
  # shellcheck disable=SC1091
  set -a && source "$ENV_FILE" && set +a
  nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT" >> "$INSTALL_DIR/server.log" 2>&1 &
  echo $! > "$INSTALL_DIR/server.pid"
fi

IP="$(curl -fsS ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "============================================"
echo "  Dashboard: http://${IP:-YOUR_VPS_IP}:$PORT"
echo "  Reports every ${INTERVAL_HOURS}h · data window ${WINDOW_HOURS}h"
echo "  Data dir:  $INSTALL_DIR/data"
echo "============================================"
