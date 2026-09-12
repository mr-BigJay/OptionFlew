from __future__ import annotations

import httpx

from app.storage import get_setting


def telegram_enabled() -> bool:
    return get_setting("telegram_enabled", "0") == "1"


def send_telegram_message(text: str) -> tuple[bool, str]:
    token = get_setting("telegram_bot_token", "").strip()
    chat_id = get_setting("telegram_chat_id", "").strip()
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


def maybe_send_report(paragraph: str) -> None:
    if not telegram_enabled():
        return
    if get_setting("telegram_on_schedule", "1") != "1":
        return
    send_telegram_message(paragraph)
