#!/usr/bin/env bash
# OptionFlow VPS installer (Finglish UI, nginx + SSL)
# Behtarin ravesh:
#   curl -fsSL https://raw.githubusercontent.com/mr-BigJay/OptionFlew/cursor/optionflow-guide-9890/scripts/install.sh -o install.sh
#   sudo bash install.sh
#
# Ya non-interactive:
#   sudo OPTIONFLOW_DOMAIN=flow.example.com OPTIONFLOW_EMAIL=you@mail.com bash install.sh
set -euo pipefail

INSTALL_DIR="${OPTIONFLOW_DIR:-/opt/optionflow-dashboard}"
REPO="${OPTIONFLOW_REPO:-https://github.com/mr-BigJay/OptionFlew.git}"
BRANCH="${OPTIONFLOW_BRANCH:-cursor/optionflow-guide-9890}"
PORT="${OPTIONFLOW_PORT:-8080}"
INTERVAL_HOURS="${OPTIONFLOW_INTERVAL_HOURS:-2}"
WINDOW_HOURS="${OPTIONFLOW_WINDOW_HOURS:-2}"
SERVICE_NAME="optionflow-dashboard.service"
NGINX_SITE="optionflow"

say() { echo "[OptionFlow] $*"; }
die() { say "ERROR: $*"; exit 1; }

if [[ "$(id -u)" -ne 0 ]]; then
  die "Lotfan ba root ejra kon: sudo bash install.sh (baraye nginx va SSL lazeme)"
fi

if [[ ! -t 0 ]] && [[ -z "${OPTIONFLOW_DOMAIN:-}" ]]; then
  die "Terminal interactive nist. Domain ro bede: sudo OPTIONFLOW_DOMAIN=flow.example.com bash install.sh"
fi

# --- Domain & email ---
if [[ -z "${OPTIONFLOW_DOMAIN:-}" ]]; then
  read -rp "[OptionFlow] Domain ro vared kon (mesal: chart.example.com): " OPTIONFLOW_DOMAIN
fi
DOMAIN="${OPTIONFLOW_DOMAIN// /}"
[[ -n "$DOMAIN" ]] || die "Domain khali bud."

if [[ ! "$DOMAIN" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ ]]; then
  die "Format domain eshtebahe: $DOMAIN"
fi

if [[ -z "${OPTIONFLOW_EMAIL:-}" ]]; then
  read -rp "[OptionFlow] Email baraye SSL/Let's Encrypt (Enter = bedune email): " OPTIONFLOW_EMAIL
fi

say "=========================================="
say "  OptionFlow Dashboard — shoro nasb"
say "  Domain: $DOMAIN"
say "  Install dir: $INSTALL_DIR"
say "=========================================="

# --- OS & prerequisites ---
if command -v apt-get >/dev/null 2>&1; then
  say "Package haye lazem ro nasb mikonam (git, python3, nginx, certbot)..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq \
    ca-certificates \
    curl \
    git \
    python3 \
    python3-venv \
    python3-pip \
    nginx \
    certbot \
    python3-certbot-nginx
elif command -v dnf >/dev/null 2>&1; then
  say "Package haye lazem ro nasb mikonam (dnf)..."
  dnf install -y git curl python3 nginx certbot python3-certbot-nginx
else
  die "Faghat Debian/Ubuntu ya RHEL/CentOS support mishe. Package ha ro dasti nasb kon."
fi

# --- App clone / update ---
if [[ -d "$INSTALL_DIR/.git" ]]; then
  say "Update repo..."
  git -C "$INSTALL_DIR" fetch origin "$BRANCH" --depth 1
  git -C "$INSTALL_DIR" checkout "$BRANCH"
  git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
else
  say "Clone repo..."
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

if [[ ! -d .venv ]]; then
  say "Python virtualenv..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip -q
pip install -r requirements.txt -q

mkdir -p "$INSTALL_DIR/data"

ENV_FILE="$INSTALL_DIR/.env"
cat > "$ENV_FILE" <<EOF
OPTIONFLOW_DATA=$INSTALL_DIR/data
OPTIONFLOW_PORT=$PORT
OPTIONFLOW_INTERVAL_HOURS=$INTERVAL_HOURS
OPTIONFLOW_WINDOW_HOURS=$WINDOW_HOURS
OPTIONFLOW_PUBLIC_URL=https://$DOMAIN
OPTIONFLOW_ADMIN_USER=BigJay
OPTIONFLOW_SESSION_SECRET=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
# OPTIONFLOW_ADMIN_PASSWORD=your-strong-password-here
EOF
say "Set OPTIONFLOW_ADMIN_PASSWORD in $ENV_FILE then restart service (creates admin BigJay)."

# --- systemd (local only — nginx miyad jolo) ---
say "Systemd service..."
cat > "/etc/systemd/system/$SERVICE_NAME" <<EOF
[Unit]
Description=OptionFlow BTC Options Dashboard
After=network-online.target nginx.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$INSTALL_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
say "Service bala omad (127.0.0.1:$PORT)."

# --- nginx ---
say "Nginx config baraye $DOMAIN ..."
NGINX_CONF="/etc/nginx/sites-available/$NGINX_SITE"
if [[ -d /etc/nginx/sites-available ]]; then
  cat > "$NGINX_CONF" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/$NGINX_SITE"
  rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
else
  cat > /etc/nginx/conf.d/optionflow.conf <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
fi

nginx -t
systemctl enable nginx
systemctl reload nginx
say "Nginx amade (HTTP)."

# --- DNS hint ---
PUBLIC_IP="$(curl -fsS --max-time 5 ifconfig.me 2>/dev/null || curl -fsS --max-time 5 icanhazip.com 2>/dev/null || true)"
if [[ -n "$PUBLIC_IP" ]]; then
  say "IP in server: $PUBLIC_IP — DNS record A baraye $DOMAIN bayad be in IP eshare kone."
  say "Age SSL fail shod, 5 daqiqe sab kon ta DNS propagate she, bad dobare: certbot --nginx -d $DOMAIN"
fi

# --- SSL ---
say "SSL certificate (Let's Encrypt)..."
CERTBOT_ARGS=(certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --redirect)
if [[ -n "${OPTIONFLOW_EMAIL:-}" ]]; then
  CERTBOT_ARGS+=(--email "$OPTIONFLOW_EMAIL" --no-eff-email)
else
  CERTBOT_ARGS+=(--register-unsafely-without-email)
fi

if "${CERTBOT_ARGS[@]}"; then
  say "SSL ba movafaghiat faal shod."
else
  say "WARN: SSL alan fail shod — nginx ro ba HTTP balast gozashtim."
  say "      Bad az fix DNS: certbot --nginx -d $DOMAIN"
fi

say ""
say "=========================================="
say "  Tamom shod!"
say "  Dashboard: https://$DOMAIN"
say "  Gozaresh har ${INTERVAL_HOURS}h · data window ${WINDOW_HOURS}h"
say "  Data: $INSTALL_DIR/data"
say "  Service: systemctl status $SERVICE_NAME"
say "=========================================="
