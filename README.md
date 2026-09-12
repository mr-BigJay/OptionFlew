# OptionFlow Guide

راهنمای **فارسی** بر اساس **option order flow واقعی** Deribit (BTC) — CLI + **داشبورد موبایل** + ذخیرهٔ گزارش + تلگرام.

## نصب یک‌خطی روی VPS

```bash
curl -fsSL https://raw.githubusercontent.com/mr-BigJay/OptionFlew/cursor/optionflow-guide-9890/scripts/install.sh | bash
```

با root اجرا کنید تا **systemd** ساخته شود؛ بدون root با `nohup` بالا می‌آید.

متغیرهای اختیاری قبل از نصب:

```bash
OPTIONFLOW_PORT=8080 OPTIONFLOW_INTERVAL_HOURS=2 OPTIONFLOW_DIR=$HOME/optionflow-dashboard bash -c 'curl -fsSL ... | bash'
```

## داشبورد

- **خانه:** آخرین گزارش (پاراگراف ساده + مسیر)
- **گزارش‌ها:** تب روز / هفته / ماه + بازهٔ تاریخ (لیست شبیه یادداشت)
- **تلگرام:** Bot Token، Chat ID، ارسال خودکار با هر گزارش

گزارش‌ها هر **۲ ساعت** (قابل تنظیم با `OPTIONFLOW_INTERVAL_HOURS`) در SQLite ذخیره می‌شوند.

## توسعهٔ محلی

```bash
pip install -r requirements.txt
export OPTIONFLOW_DATA=./data
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

## CLI (بدون داشبورد)

```bash
python3 -m optionflow --simple
python3 -m optionflow --hours 2 --pre-event-minutes 30 --event-at 2026-09-11T12:30:00Z
```

## محدودیت‌ها

- Deribit BTC options · سناریو نه سیگنال قطعی
- Expiry Compass / gamma اختصاصی dankbit نیست
