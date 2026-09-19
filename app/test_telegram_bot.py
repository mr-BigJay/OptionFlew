from __future__ import annotations

from pathlib import Path

from app.auth_store import (
    connect_telegram_chat,
    create_user,
    disconnect_telegram,
    get_or_issue_telegram_link_code,
    get_platform_bot,
    get_user,
    issue_telegram_link_code,
    list_telegram_subscribers,
    save_platform_bot,
    set_user_telegram_prefs,
)
from app.telegram_notify import handle_bot_update, webhook_url


def _tmp_auth(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.storage.DEFAULT_DATA_DIR", tmp_path)
    monkeypatch.setenv("OPTIONFLOW_AUTH_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("OPTIONFLOW_DATA", str(tmp_path))
    monkeypatch.delenv("OPTIONFLOW_ADMIN_PASSWORD", raising=False)


def test_platform_bot_and_user_link(tmp_path, monkeypatch):
    _tmp_auth(tmp_path, monkeypatch)
    save_platform_bot(bot_token="123:abc", bot_username="OptionFlowBot")
    bot = get_platform_bot()
    assert bot["bot_token"] == "123:abc"
    assert bot["bot_username"] == "OptionFlowBot"
    assert bot["webhook_secret"]

    uid, err = create_user(
        username="ali",
        mobile="0912",
        allow_enrich=True,
        allow_stable=True,
    )
    assert err == ""
    code = issue_telegram_link_code(uid)
    assert code
    assert get_or_issue_telegram_link_code(uid) == code

    linked = connect_telegram_chat(code, "555001")
    assert linked is not None
    assert linked["username"] == "ali"
    assert linked["telegram_chat_id"] == "555001"
    assert linked["telegram_enabled"] is True
    assert linked["telegram_link_code"] == ""

    subs = list_telegram_subscribers(scheduled_only=True)
    assert len(subs) == 1
    assert subs[0]["telegram_chat_id"] == "555001"

    set_user_telegram_prefs(uid, on_schedule=False)
    assert list_telegram_subscribers(scheduled_only=True) == []
    assert len(list_telegram_subscribers(scheduled_only=False)) == 1

    disconnect_telegram(uid)
    user = get_user(uid)
    assert user["telegram_enabled"] is False
    assert user["telegram_chat_id"] == ""


def test_chat_id_moves_to_latest_user(tmp_path, monkeypatch):
    _tmp_auth(tmp_path, monkeypatch)
    a, _ = create_user(username="user_a", mobile="", allow_enrich=True, allow_stable=True)
    b, _ = create_user(username="user_b", mobile="", allow_enrich=True, allow_stable=True)
    connect_telegram_chat(issue_telegram_link_code(a), "42")
    connect_telegram_chat(issue_telegram_link_code(b), "42")
    assert get_user(a)["telegram_enabled"] is False
    assert get_user(b)["telegram_chat_id"] == "42"


def test_handle_start_connects_user(tmp_path, monkeypatch):
    _tmp_auth(tmp_path, monkeypatch)
    save_platform_bot(bot_token="tok", bot_username="Bot")
    uid, _ = create_user(
        username="sara",
        mobile="",
        allow_enrich=True,
        allow_stable=True,
    )
    code = issue_telegram_link_code(uid)
    sent: list[tuple[str, str]] = []

    def fake_send(text, *, token="", chat_id=""):
        sent.append((text, chat_id))
        return True, "ok"

    monkeypatch.setattr("app.telegram_notify.send_telegram_message", fake_send)
    handle_bot_update(
        {"message": {"text": f"/start {code}", "chat": {"id": 999}}}
    )
    user = get_user(uid)
    assert user["telegram_chat_id"] == "999"
    assert user["telegram_enabled"] is True
    assert sent and "sara" in sent[0][0]


def test_webhook_url_uses_public_env(monkeypatch):
    monkeypatch.setenv("OPTIONFLOW_PUBLIC_URL", "https://flow.example.com/")
    assert webhook_url("sec") == "https://flow.example.com/telegram/hook/sec"
    monkeypatch.setenv("OPTIONFLOW_PUBLIC_URL", "")
    assert webhook_url("sec") == ""
