# OptionFlow Guide

راهنمای **فارسی** بر اساس **option order flow واقعی** Deribit (BTC) — شبیه منطق داشبوردهایی مثل dankbit (Buyer Call/Put، سطح حمایت/هدف، جمع‌بندی قبل از خبر).

> این ابزار **سیگنال تضمینی نیست**؛ flow عمومی را به **متن actionable** تبدیل می‌کند تا مثل تحلیل دستی شما تصمیم بگیرید.

## نصب

```bash
pip install -r requirements.txt
```

## استفاده

**تحلیل ۲ ساعت اخیر (پیش‌فرض):**

```bash
python -m optionflow
```

**پنجرهٔ دلخواه + ۳۰ دقیقه قبل از خبر:**

```bash
python -m optionflow --hours 2 --pre-event-minutes 30 --event-at 2026-09-11T12:30:00Z
```

**خروجی JSON برای ربات تلگرام:**

```bash
python -m optionflow --json
```

## ربات «به‌موقع»

1. هر **۵–۱۵ دقیقه** cron یا scheduler همین CLI را اجرا کنید.
2. اگر `--json` → `bias` یا `score` از آستانه رد شد، به Telegram بفرستید.
3. برای اخبار مهم، `--event-at` را از تقویم اقتصادی پر کنید.

## محدودیت‌ها

- فقط **Deribit BTC options** (نه Binance spot labels دقیق dankbit).
- **Effective** = تقریب notional (contracts × index); dankbit ممکن است delta-weighted باشد.
- **Gamma / Expiry Compass** اختصاصی dankbit نیست — سطوح از **تمرکز strike در flow** استخراج می‌شوند.

## توسعهٔ بعدی

- WebSocket real-time + هشدار لحظه‌ای
- delta-weighted effective از `mark_iv` / greeks
- داشبورد وب
