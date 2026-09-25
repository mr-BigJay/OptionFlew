from __future__ import annotations

import re
import logging
from datetime import datetime, timezone
from typing import Any

from app.storage import connect

logger = logging.getLogger("optionflow.indicators")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_LANGS = frozenset({"pine", "python", "other"})


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def init_indicator_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS custom_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                slug TEXT NOT NULL,
                title_fa TEXT NOT NULL,
                description_fa TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'pine',
                source_code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, slug)
            );
            CREATE INDEX IF NOT EXISTS idx_custom_indicators_user
                ON custom_indicators(user_id, updated_at DESC);
            """
        )


def normalize_slug(raw: str) -> str:
    s = (raw or "").strip().lower().replace(" ", "-")
    s = re.sub(r"[^a-z0-9_-]", "", s)
    return s[:64]


def validate_slug(slug: str) -> bool:
    return bool(slug and _SLUG_RE.match(slug))


def list_indicators(*, user_id: int | None = None, is_admin: bool = False) -> list[dict[str, Any]]:
    init_indicator_db()
    q = "SELECT * FROM custom_indicators"
    params: list[Any] = []
    if not is_admin and user_id is not None:
        q += " WHERE user_id = ?"
        params.append(user_id)
    q += " ORDER BY updated_at DESC"
    with connect() as conn:
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def get_indicator(indicator_id: int) -> dict[str, Any] | None:
    init_indicator_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM custom_indicators WHERE id = ?", (indicator_id,)
        ).fetchone()
        return dict(row) if row else None


def user_can_edit(user: dict[str, Any] | None, row: dict[str, Any]) -> bool:
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return int(row.get("user_id") or 0) == int(user["id"])


def save_indicator(
    *,
    user_id: int,
    title_fa: str,
    source_code: str,
    slug: str = "",
    description_fa: str = "",
    language: str = "pine",
    indicator_id: int | None = None,
) -> tuple[int | None, str]:
    init_indicator_db()
    title = (title_fa or "").strip()
    code = source_code or ""
    if not title:
        return None, "عنوان الزامی است."
    if not code.strip():
        return None, "سورس کد الزامی است."
    lang = (language or "pine").strip().lower()
    if lang not in _LANGS:
        lang = "pine"
    slug_norm = normalize_slug(slug) or normalize_slug(title)
    if not validate_slug(slug_norm):
        return None, "شناسه (slug) نامعتبر است — فقط a-z، 0-9، - و _"
    now = utc_now_iso()
    desc = (description_fa or "").strip()
    try:
        with connect() as conn:
            if indicator_id:
                row = conn.execute(
                    "SELECT user_id FROM custom_indicators WHERE id = ?",
                    (indicator_id,),
                ).fetchone()
                if not row:
                    return None, "اندیکاتور پیدا نشد."
                conn.execute(
                    """
                    UPDATE custom_indicators SET
                        title_fa = ?, description_fa = ?, language = ?,
                        source_code = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (title, desc, lang, code, now, indicator_id),
                )
                return indicator_id, ""
            conn.execute(
                """
                INSERT INTO custom_indicators (
                    user_id, slug, title_fa, description_fa, language,
                    source_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, slug_norm, title, desc, lang, code, now, now),
            )
            new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            return int(new_id), ""
    except Exception as e:
        logger.exception("save_indicator failed")
        if "UNIQUE" in str(e):
            return None, "این شناسه قبلاً ثبت شده — slug دیگری انتخاب کنید."
        return None, "خطا در ذخیره."


def delete_indicator(indicator_id: int) -> bool:
    init_indicator_db()
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM custom_indicators WHERE id = ?", (indicator_id,)
        )
        return cur.rowcount > 0
