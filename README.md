# OptionFlow Guide

راهنمای **فارسی** بر اساس **option order flow واقعی** Deribit (BTC) — CLI + **داشبورد موبایل** + ذخیرهٔ گزارش + تلگرام.

## نصب یک‌خطی روی VPS (Finglish + SSL)

**پیشنهاد:** اسکریپت را دانلود کنید و با root اجرا کنید تا دامنه بپرسد و SSL بگیرد:

```bash
curl -fsSL https://raw.githubusercontent.com/mr-BigJay/OptionFlew/cursor/optionflow-guide-9890/scripts/install.sh -o install.sh
sudo bash install.sh
```

در حین نصب: **domain** (مثلاً `flow.example.com`) و اختیاری **email** برای Let's Encrypt.  
پیام‌های نصب **Finglish** هستند. پیش‌نیازها (`git`, `python3`, `nginx`, `certbot`) خودکار نصب می‌شوند.

**بدون سوال (non-interactive):**

```bash
sudo OPTIONFLOW_DOMAIN=flow.example.com OPTIONFLOW_EMAIL=you@mail.com bash install.sh
```

قبل از SSL، رکورد **A** دامنه باید به IP همان VPS اشاره کند.

متغیرهای اختیاری: `OPTIONFLOW_DIR=/opt/optionflow-dashboard` · `OPTIONFLOW_INTERVAL_HOURS=2`

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
