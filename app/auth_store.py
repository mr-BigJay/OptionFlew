from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.storage import connect_users, db_path, init_db, users_db_path

logger = logging.getLogger("optionflow.auth")

DEFAULT_USER_PASSWORD = "12345678"
MIN_PASSWORD_LEN = 8

_USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    mobile TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    allow_enrich INTEGER NOT NULL DEFAULT 0,
    allow_stable INTEGER NOT NULL DEFAULT 0,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    telegram_bot_token TEXT NOT NULL DEFAULT '',
    telegram_chat_id TEXT NOT NULL DEFAULT '',
    telegram_enabled INTEGER NOT NULL DEFAULT 0,
    telegram_on_schedule INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return "pbkdf2_sha256$260000$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        check = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iters)
        ).hex()
        return secrets.compare_digest(check, hash_hex)
    except Exception:
        return False


def _legacy_users_table_exists() -> bool:
    legacy = db_path()
    if not legacy.is_file():
        return False
    if legacy.resolve() == users_db_path().resolve():
        return False
    try:
        conn = sqlite3.connect(legacy)
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def _migrate_users_from_legacy_db() -> None:
    if os.environ.get("OPTIONFLOW_AUTH_DB", "").strip() == "":
        return
    legacy = db_path()
    if not _legacy_users_table_exists():
        return
    with connect_users() as auth_conn:
        n = auth_conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if n:
            return
        leg = sqlite3.connect(legacy)
        leg.row_factory = sqlite3.Row
        rows = leg.execute("SELECT * FROM users").fetchall()
        leg.close()
        if not rows:
            return
        for r in rows:
            auth_conn.execute(
                """
                INSERT INTO users
                (id, username, mobile, password_hash, is_admin, allow_enrich,
                 allow_stable, must_change_password, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["id"],
                    r["username"],
                    r["mobile"],
                    r["password_hash"],
                    r["is_admin"],
                    r["allow_enrich"],
                    r["allow_stable"],
                    r["must_change_password"],
                    r["created_at"],
                ),
            )
        logger.info(
            "Migrated %s user(s) from %s to shared auth DB %s",
            len(rows),
            legacy,
            users_db_path(),
        )


def ensure_users_schema() -> None:
    init_db()
    with connect_users() as conn:
        conn.executescript(_USERS_SCHEMA)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        alters = {
            "telegram_bot_token": "TEXT NOT NULL DEFAULT ''",
            "telegram_chat_id": "TEXT NOT NULL DEFAULT ''",
            "telegram_enabled": "INTEGER NOT NULL DEFAULT 0",
            "telegram_on_schedule": "INTEGER NOT NULL DEFAULT 1",
            "telegram_link_code": "TEXT NOT NULL DEFAULT ''",
        }
        for name, ddl in alters.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS telegram_bot (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                bot_token TEXT NOT NULL DEFAULT '',
                bot_username TEXT NOT NULL DEFAULT '',
                webhook_secret TEXT NOT NULL DEFAULT ''
            );
            INSERT OR IGNORE INTO telegram_bot (id, bot_token, bot_username, webhook_secret)
            VALUES (1, '', '', '');
            """
        )
    _migrate_users_from_legacy_db()


def bootstrap_admin() -> None:
    ensure_users_schema()
    logger.info("Auth users database: %s", users_db_path())
    admin_user = os.environ.get("OPTIONFLOW_ADMIN_USER", "BigJay").strip()
    admin_pass = os.environ.get("OPTIONFLOW_ADMIN_PASSWORD", "").strip()
    if not admin_pass:
        logger.warning(
            "OPTIONFLOW_ADMIN_PASSWORD not set — admin user not auto-created"
        )
        return
    pw_hash = _hash_password(admin_pass)
    with connect_users() as conn:
        row = conn.execute(
            """
            SELECT id, is_admin FROM users
            WHERE username = ? COLLATE NOCASE
            """,
            (admin_user,),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE users SET
                    password_hash = ?,
                    is_admin = 1,
                    allow_enrich = 1,
                    allow_stable = 1,
                    must_change_password = 0
                WHERE id = ?
                """,
                (pw_hash, row["id"]),
            )
            logger.info(
                "Bootstrap admin %s: password synced from OPTIONFLOW_ADMIN_PASSWORD",
                admin_user,
            )
            return
        conn.execute(
            """
            INSERT INTO users
            (username, mobile, password_hash, is_admin, allow_enrich, allow_stable,
             must_change_password, created_at)
            VALUES (?, ?, ?, 1, 1, 1, 0, ?)
            """,
            (admin_user, "", pw_hash, _utc_now()),
        )
        logger.info("Bootstrap admin user %s created", admin_user)


def get_user(user_id: int | None) -> dict[str, Any] | None:
    if not user_id:
        return None
    ensure_users_schema()
    with connect_users() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def get_user_by_username(username: str) -> dict[str, Any] | None:
    ensure_users_schema()
    with connect_users() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
    return _row_to_dict(row) if row else None


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    user = get_user_by_username(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def list_users() -> list[dict[str, Any]]:
    ensure_users_schema()
    with connect_users() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE is_admin = 0 ORDER BY id DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_user(
    *,
    username: str,
    mobile: str,
    allow_enrich: bool,
    allow_stable: bool,
) -> tuple[int | None, str]:
    username = username.strip()
    mobile = mobile.strip()
    if len(username) < 2:
        return None, "نام کاربری کوتاه است."
    if get_user_by_username(username):
        return None, "این نام کاربری وجود دارد."
    ensure_users_schema()
    with connect_users() as conn:
        cur = conn.execute(
            """
            INSERT INTO users
            (username, mobile, password_hash, is_admin, allow_enrich, allow_stable,
             must_change_password, created_at)
            VALUES (?, ?, ?, 0, ?, ?, 1, ?)
            """,
            (
                username,
                mobile,
                _hash_password(DEFAULT_USER_PASSWORD),
                1 if allow_enrich else 0,
                1 if allow_stable else 0,
                _utc_now(),
            ),
        )
        return int(cur.lastrowid), ""


def set_user_password(user_id: int, new_password: str, *, force_change: bool) -> str:
    if len(new_password) < MIN_PASSWORD_LEN:
        return f"حداقل {MIN_PASSWORD_LEN} کاراکتر."
    ensure_users_schema()
    with connect_users() as conn:
        conn.execute(
            """
            UPDATE users SET password_hash = ?, must_change_password = ?
            WHERE id = ?
            """,
            (_hash_password(new_password), 1 if force_change else 0, user_id),
        )
    return ""


def admin_reset_user_password(user_id: int) -> None:
    set_user_password(user_id, DEFAULT_USER_PASSWORD, force_change=True)


def clear_must_change(user_id: int) -> None:
    with connect_users() as conn:
        conn.execute(
            "UPDATE users SET must_change_password = 0 WHERE id = ?",
            (user_id,),
        )


def set_user_telegram_prefs(user_id: int, *, on_schedule: bool) -> None:
    ensure_users_schema()
    with connect_users() as conn:
        conn.execute(
            "UPDATE users SET telegram_on_schedule = ? WHERE id = ?",
            (1 if on_schedule else 0, user_id),
        )


def issue_telegram_link_code(user_id: int) -> str:
    ensure_users_schema()
    code = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:10]
    with connect_users() as conn:
        conn.execute(
            "UPDATE users SET telegram_link_code = ? WHERE id = ?",
            (code, user_id),
        )
    return code


def get_or_issue_telegram_link_code(user_id: int) -> str:
    user = get_user(user_id)
    if not user:
        return ""
    existing = str(user.get("telegram_link_code") or "").strip()
    if existing:
        return existing
    return issue_telegram_link_code(user_id)


def connect_telegram_chat(code: str, chat_id: str) -> dict[str, Any] | None:
    code = (code or "").strip()
    chat_id = str(chat_id or "").strip()
    if not code or not chat_id:
        return None
    ensure_users_schema()
    with connect_users() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_link_code = ?",
            (code,),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            """
            UPDATE users SET telegram_chat_id = '', telegram_enabled = 0
            WHERE telegram_chat_id = ? AND id != ?
            """,
            (chat_id, row["id"]),
        )
        conn.execute(
            """
            UPDATE users SET
                telegram_chat_id = ?,
                telegram_enabled = 1,
                telegram_link_code = ''
            WHERE id = ?
            """,
            (chat_id, row["id"]),
        )
    return get_user(int(row["id"]))


def disconnect_telegram(user_id: int) -> None:
    ensure_users_schema()
    with connect_users() as conn:
        conn.execute(
            """
            UPDATE users SET
                telegram_chat_id = '',
                telegram_enabled = 0,
                telegram_link_code = ''
            WHERE id = ?
            """,
            (user_id,),
        )


def get_platform_bot() -> dict[str, str]:
    ensure_users_schema()
    with connect_users() as conn:
        row = conn.execute("SELECT * FROM telegram_bot WHERE id = 1").fetchone()
    if not row:
        return {"bot_token": "", "bot_username": "", "webhook_secret": ""}
    return {
        "bot_token": row["bot_token"] or "",
        "bot_username": row["bot_username"] or "",
        "webhook_secret": row["webhook_secret"] or "",
    }


def save_platform_bot(
    *,
    bot_token: str,
    bot_username: str = "",
    webhook_secret: str = "",
) -> None:
    ensure_users_schema()
    current = get_platform_bot()
    token = bot_token.strip()
    username = (bot_username or current["bot_username"]).strip().lstrip("@")
    secret = (webhook_secret or current["webhook_secret"] or secrets.token_urlsafe(24)).strip()
    with connect_users() as conn:
        conn.execute(
            """
            INSERT INTO telegram_bot (id, bot_token, bot_username, webhook_secret)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                bot_token = excluded.bot_token,
                bot_username = excluded.bot_username,
                webhook_secret = excluded.webhook_secret
            """,
            (token, username, secret),
        )


def list_telegram_subscribers(*, scheduled_only: bool = True) -> list[dict[str, Any]]:
    """کاربرانی که به ربات ادمین وصل شده‌اند."""
    ensure_users_schema()
    extra = " AND telegram_on_schedule = 1" if scheduled_only else ""
    with connect_users() as conn:
        rows = conn.execute(
            f"""
            SELECT id, username, telegram_chat_id, telegram_on_schedule
            FROM users
            WHERE telegram_enabled = 1
              AND telegram_chat_id != ''
              {extra}
            """
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["is_admin"] = bool(d.get("is_admin"))
    d["allow_enrich"] = bool(d.get("allow_enrich"))
    d["allow_stable"] = bool(d.get("allow_stable"))
    d["must_change_password"] = bool(d.get("must_change_password"))
    d["telegram_enabled"] = bool(d.get("telegram_enabled"))
    if "telegram_on_schedule" in d:
        d["telegram_on_schedule"] = bool(d.get("telegram_on_schedule"))
    return d
