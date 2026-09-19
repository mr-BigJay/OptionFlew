from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("optionflow.telegram")


def send_telegram_message(
    text: str,
    *,
    token: str = "",
    chat_id: str = "",
) -> tuple[bool, str]:
    token = (token or "").strip()
    chat_id = (chat_id or "").strip()
    if not token or not chat_id:
        return False, "توکن ربات یا Chat ID تنظیم نشده است."
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=30.0,
        )
        data = r.json()
        if not data.get("ok"):
            return False, str(data.get("description", r.text))
        return True, "پیام ارسال شد."
    except Exception as e:
        return False, str(e)


def send_telegram_photo(
    png: bytes,
    *,
    caption: str = "",
    token: str = "",
    chat_id: str = "",
) -> tuple[bool, str]:
    token = (token or "").strip()
    chat_id = (chat_id or "").strip()
    if not token or not chat_id:
        return False, "توکن ربات یا Chat ID تنظیم نشده است."
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        r = httpx.post(
            url,
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"photo": ("btcusdt-scenario.png", png, "image/png")},
            timeout=60.0,
        )
        data = r.json()
        if not data.get("ok"):
            return False, str(data.get("description", r.text))
        return True, "عکس ارسال شد."
    except Exception as e:
        return False, str(e)


def maybe_send_report(paragraph: str, chart_png: bytes | None = None) -> None:
    from app.auth_store import list_telegram_subscribers

    subs = list_telegram_subscribers(scheduled_only=True)
    if not subs:
        return
    for sub in subs:
        token = sub.get("telegram_bot_token") or ""
        chat_id = sub.get("telegram_chat_id") or ""
        if chart_png:
            ok, msg = send_telegram_photo(
                chart_png,
                caption="BTCUSDT — مسیر سناریو (Spot → B → C)",
                token=token,
                chat_id=chat_id,
            )
            if not ok:
                logger.warning(
                    "Telegram photo failed user=%s: %s",
                    sub.get("username"),
                    msg,
                )
        ok, msg = send_telegram_message(paragraph, token=token, chat_id=chat_id)
        if not ok:
            logger.warning(
                "Telegram text failed user=%s: %s",
                sub.get("username"),
                msg,
            )
