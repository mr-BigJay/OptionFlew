# OptionFlow

## Stable v1 (production) — `main`

Deribit flow، داشبورد، گزارش ساده، تلگرام، Tehran :31 — **بدون** enriched/Binance/gamma.

```bash
curl -fsSL https://raw.githubusercontent.com/mr-BigJay/OptionFlew/main/scripts/install.sh | sudo bash
```

به‌روزرسانی:

```bash
cd /opt/optionflow-dashboard
sudo git fetch origin main && sudo git checkout main && sudo git reset --hard origin/main
sudo .venv/bin/pip install -r requirements.txt -q
sudo systemctl restart optionflow-dashboard
```

### اکانتینگ (یک سرور، دو ربات)

- ادمین: `/bigjay_controller/login` · کاربر: `/login`
- در **هر دو** `.env` (stable و enrich):

```bash
OPTIONFLOW_ADMIN_USER=BigJay
OPTIONFLOW_ADMIN_PASSWORD='...'
OPTIONFLOW_AUTH_DB=/opt/optionflow-shared/users.db
```

با `OPTIONFLOW_AUTH_DB` مشترک، یک‌بار ساخت کاربر در پنل ادمین (روی هر دامنه) برای **هر دو** ربات کافی است. گزارش‌ها همچنان در `data/` جدا می‌مانند.

---

## Pre-release / dev — `pre-release`

+ Binance funding/OI/liquid، gamma، max pain، `--enriched`، `OPTIONFLOW_ENRICHED=1` در scheduler.

```bash
curl -fsSL https://raw.githubusercontent.com/mr-BigJay/OptionFlew/pre-release/scripts/install-prerelease.sh | sudo bash
```

پوشه پیش‌فرض: `/opt/optionflow-dashboard-pre` · پورت **8081** · سرویس `optionflow-dashboard-pre`

**مهم:** روی VPS از `python3` سیستمی استفاده نکن — سرویس و CLI باید از **`.venv`** باشند (مثل `install-prerelease.sh`).

به‌روزرسانی (شاخه enriched / narrative):

```bash
cd /opt/optionflow-dashboard-pre
sudo bash scripts/update-dashboard-pre.sh
```

یا دستی:

```bash
cd /opt/optionflow-dashboard-pre
git fetch origin cursor/enriched-data-report-9890
git ls-remote origin refs/heads/cursor/enriched-data-report-9890   # باید f6ec38e یا جدیدتر
git checkout -B cursor/enriched-data-report-9890 origin/cursor/enriched-data-report-9890
git reset --hard origin/cursor/enriched-data-report-9890
git log -1 --oneline
.venv/bin/pip install -r requirements.txt -q
sudo systemctl restart optionflow-dashboard-pre
set -a && source .env && set +a
.venv/bin/python -c "from app.jobs import run_scheduled_report; run_scheduled_report()"
.venv/bin/python -m optionflow --simple --enriched | head -20
```
