#!/usr/bin/env bash
# به‌روزرسانی /opt/optionflow-dashboard-pre (enriched) — همیشه با .venv، نه pip سیستمی
set -euo pipefail

INSTALL_DIR="${OPTIONFLOW_DIR:-/opt/optionflow-dashboard-pre}"
BRANCH="${OPTIONFLOW_BRANCH:-cursor/enriched-data-report-9890}"
SERVICE="${OPTIONFLOW_SERVICE:-optionflow-dashboard-pre.service}"
REMOTE="${OPTIONFLOW_REMOTE:-origin}"

say() { echo "[OptionFlow-pre] $*"; }
die() { say "ERROR: $*"; exit 1; }

[[ -d "$INSTALL_DIR/.git" ]] || die "Repo peida nashod: $INSTALL_DIR"

cd "$INSTALL_DIR"

say "Remote ref ro check kon (bayad ba GitHub yeki bashe):"
git ls-remote "$REMOTE" "refs/heads/$BRANCH" | head -1 || true

say "Fetch $REMOTE $BRANCH ..."
git fetch "$REMOTE" "$BRANCH"

LOCAL_REF="refs/remotes/$REMOTE/$BRANCH"
git rev-parse "$LOCAL_REF" >/dev/null 2>&1 || die "Branch $BRANCH roye $REMOTE nist."

git checkout -B "$BRANCH" "$LOCAL_REF"
git reset --hard "$LOCAL_REF"
say "HEAD: $(git log -1 --oneline)"

if [[ ! -d .venv ]]; then
  say "Sakhtan .venv ..."
  python3 -m venv .venv
fi

.venv/bin/pip install -U pip -q
.venv/bin/pip install -r requirements.txt -q

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload 2>/dev/null || true
  systemctl restart "$SERVICE"
  say "Service $SERVICE restart shod."
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

say "Tolid gozaresh jadid ..."
.venv/bin/python -c "from app.jobs import run_scheduled_report; run_scheduled_report()"

say "Preview (--simple --enriched):"
OUT=$(.venv/bin/python -m optionflow --simple --enriched)
echo "$OUT" | head -25
echo "$OUT" | grep -q "نتیجه‌گیری" || die "Gozaresh format jadid nist — git log -1 ro check kon."
echo "$OUT" | grep -q "زمینهٔ بازار" && die "Block zamane bazar (code ghadimi)."
echo "$OUT" | grep -q "مرحله اول" && die "Format titr-dar — bayad prose monasem bashe."
