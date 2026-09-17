#!/usr/bin/env bash
# به‌روزرسانی stable — /opt/optionflow-dashboard + تأیید قالب prose
set -euo pipefail

INSTALL_DIR="${OPTIONFLOW_DIR:-/opt/optionflow-dashboard}"
BRANCH="${OPTIONFLOW_BRANCH:-main}"
SERVICE="${OPTIONFLOW_SERVICE:-optionflow-dashboard.service}"
REMOTE="${OPTIONFLOW_REMOTE:-origin}"

say() { echo "[OptionFlow-stable] $*"; }
die() { say "ERROR: $*"; exit 1; }

[[ -d "$INSTALL_DIR/.git" ]] || die "Repo peida nashod: $INSTALL_DIR"
cd "$INSTALL_DIR"

say "Remote main:"
git ls-remote "$REMOTE" "refs/heads/$BRANCH" | head -1 || true

git fetch "$REMOTE" "$BRANCH"
# بعضی cloneها ref محلی origin/main ندارند؛ بعد از fetch از FETCH_HEAD استفاده کن
if git rev-parse "$REMOTE/$BRANCH" >/dev/null 2>&1; then
  TARGET_REF="$REMOTE/$BRANCH"
else
  say "WARN: $REMOTE/$BRANCH peida nashod; estefade az FETCH_HEAD"
  TARGET_REF="FETCH_HEAD"
fi
git checkout -B "$BRANCH" "$TARGET_REF"
git reset --hard "$TARGET_REF"
say "HEAD: $(git log -1 --oneline) (branch: $(git branch --show-current))"

[[ -f optionflow/scenario_narrative.py ]] || die "optionflow/scenario_narrative.py nist — branch/main eshtebahe."
grep -q "format_narrative_scenario" optionflow/guide.py || die "guide.py ghadimi ast (scenario_narrative nist)."

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -U pip -q
.venv/bin/pip install -r requirements.txt -q

if command -v systemctl >/dev/null 2>&1; then
  systemctl restart "$SERVICE" 2>/dev/null || true
fi

say "Version check:"
.venv/bin/python3 -m optionflow --version

say "Report sample:"
OUT=$(.venv/bin/python3 -m optionflow --simple 2>&1) || true
echo "$OUT" | head -8
echo "$OUT" | grep -qE "جمع‌بندی|نتیجه‌گیری" || die "Khrooji hanuz format ghadimi (A-B/scalp). Payin kamel:\n$OUT"
echo "$OUT" | grep -q "حرکت اول" || die "Format prose-v3 (bakhsh-band) faal nist."
echo "$OUT" | grep -qE "A–B|اسکالپ|بازار متعادل" && die "Matn ghadimi (A-B) hanuz hast."

say "OK — format jadid faal ast."
