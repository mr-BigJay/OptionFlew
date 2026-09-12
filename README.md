# OptionFlow

**Stable (v1)** — Deribit option flow، داشبورد موبایل، گزارش پارagraph ساده، تلگرام، زمان‌بندی Tehran (:31).

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
sudo git fetch origin main
sudo git checkout main
sudo git reset --hard origin/main
sudo .venv/bin/pip install -r requirements.txt -q
sudo systemctl restart optionflow-dashboard
```

## CLI

```bash
python3 -m optionflow --simple
```
