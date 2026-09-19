from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("optionflow.telegram")


def public_base_url() -> str:
    return os.environ.get("OPTIONFLOW_PUBLIC_URL", "").strip().rstrip("/")


def webhook_url(secret: str) -> str:
    base = public_base_url()
    secret = (secret or "").strip()
    if not base or not secret:
        return ""
    return f"{base}/telegram/hook/{secret}"


def telegram_call(
    token: str,
    method: str,
    *,
    json: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[bool, Any]:
    token = (token or "").strip()
    if not token:
        return False, "توکن ربات تنظیم نشده است."
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        r = httpx.post(url, json=json or {}, timeout=timeout)
        data = r.json()
        if not data.get("ok"):
            return False, str(data.get("description", r.text))
        return True, data.get("result")
    except Exception as e:
        return False, str(e)


def telegram_get_me(token: str) -> tuple[bool, str]:
    ok, result = telegram_call(token, "getMe")
    if not ok:
        return False, str(result)
    username = str((result or {}).get("username") or "").strip().lstrip("@")
    if not username:
        return False, "ربات نام کاربری ندارد."
    return True, username


def telegram_set_webhook(token: str, url: str) -> tuple[bool, str]:
    url = (url or "").strip()
    if not url:
        return False, "OPTIONFLOW_PUBLIC_URL تنظیم نشده؛ وب‌هوک ثبت نشد."
    ok, result = telegram_call(
        token,
        "setWebhook",
        json={"url": url, "allowed_updates": ["message"], "drop_pending_updates": False},
    )
    if not ok:
        return False, str(result)
    return True, "وب‌هوک ثبت شد."


def send_telegram_message(
    text: str,
    *,
    token: str = "",
    chat_id: str = "",
) -> tuple[bool, str]:
    token = (token or "").strip()
    chat_id = str(chat_id or "").strip()
    if not token or not chat_id:
        return False, "ربات پلتفرم یا چت کاربر تنظیم نشده است."
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
    chat_id = str(chat_id or "").strip()
    if not token or not chat_id:
        return False, "ربات پلتفرم یا چت کاربر تنظیم نشده است."
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


def handle_bot_update(payload: dict[str, Any]) -> None:
    """Connect a user when they send /start CODE to the platform bot."""
    from app.auth_store import connect_telegram_chat, get_platform_bot

    message = payload.get("message") or payload.get("edited_message") or {}
    if not isinstance(message, dict):
        return
    text = str(message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None or not text:
        return
    bot = get_platform_bot()
    token = bot.get("bot_token") or ""
    if not token:
        return
    cmd, _, rest = text.partition(" ")
    if not cmd.startswith("/start"):
        return
    code = rest.strip()
    if not code:
        send_telegram_message(
            "برای اتصال حساب OptionFlow، از صفحهٔ تلگرام داشبورد دکمهٔ اتصال را بزنید.",
            token=token,
            chat_id=str(chat_id),
        )
        return
    user = connect_telegram_chat(code, str(chat_id))
    if user:
        send_telegram_message(
            f"سلام {user['username']} — حساب OptionFlow شما به این ربات وصل شد.\n"
            "گزارش‌های زمان‌بندی‌شده همین‌جا برایتان می‌آید.",
            token=token,
            chat_id=str(chat_id),
        )
        return
    send_telegram_message(
        "کد اتصال نامعتبر یا منقضی است. از صفحهٔ تلگرام داشبورد دوباره وصل شوید.",
        token=token,
        chat_id=str(chat_id),
    )


def maybe_send_report(paragraph: str, chart_png: bytes | None = None) -> None:
    from app.auth_store import get_platform_bot, list_telegram_subscribers

    token = get_platform_bot().get("bot_token") or ""
    if not token:
        logger.warning("Telegram skipped: platform bot is not configured")
        return
    subs = list_telegram_subscribers(scheduled_only=True)
    if not subs:
        return
    for sub in subs:
        chat_id = sub.get("telegram_chat_id") or ""
        if not chat_id:
            continue
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
