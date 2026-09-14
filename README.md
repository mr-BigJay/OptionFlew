# OptionFlow

**Stable (v1)** — Deribit option flow، داشبورد موبایل، گزارش **۴ ساعته + روزانه**، تلگرام، زمان‌بندی Tehran.

## نصب stable — یک خط

```bash
curl -fsSL https://raw.githubusercontent.com/mr-BigJay/OptionFlew/main/scripts/install.sh | sudo bash
```

## Pre-release / dev (gamma، Binance، enriched)

[شاخه `pre-release`](https://github.com/mr-BigJay/OptionFlew/tree/pre-release):

```bash
curl -fsSL https://raw.githubusercontent.com/mr-BigJay/OptionFlew/pre-release/scripts/install-prerelease.sh | sudo bash
```

## به‌روزرسانی stable (روی VPS)

```bash
cd /opt/optionflow-dashboard
sudo bash scripts/update-dashboard-stable.sh
```

یا دستی: `git fetch origin main && git reset --hard origin/main` سپس `.venv/bin/pip install -r requirements.txt` و `systemctl restart optionflow-dashboard`.

**تأیید:** `.venv/bin/python3 -m optionflow --version` باید `report_format=prose-v2` و فایل `scenario_narrative.py` را نشان دهد.  
`.venv/bin/python3 -m optionflow --simple | grep نتیجه‌گیری` باید خطی برگرداند — اگر `A–B` یا `اسکالپ` دیدید، هنوز کد قدیمی است.

## CLI

```bash
cd /opt/optionflow-dashboard
sudo .venv/bin/python3 -m optionflow --simple          # آخرین کندل ۴h
sudo .venv/bin/python3 -m optionflow --simple --daily   # آخرین روز تهران
```
