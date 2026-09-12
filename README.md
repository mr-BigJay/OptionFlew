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

---

## Pre-release / dev — `pre-release`

+ Binance funding/OI/liquid، gamma، max pain، `--enriched`، `OPTIONFLOW_ENRICHED=1` در scheduler.

```bash
curl -fsSL https://raw.githubusercontent.com/mr-BigJay/OptionFlew/pre-release/scripts/install-prerelease.sh | sudo bash
```

پوشه پیش‌فرض: `/opt/optionflow-dashboard-pre` · پورت **8081** · سرویس `optionflow-dashboard-pre`

```bash
python3 -m optionflow --simple --enriched
```
