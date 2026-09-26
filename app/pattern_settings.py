"""تنظیم هر الگو: فعال بودن و تایم‌فریم‌هایی که سیگنال می‌سازند."""

from __future__ import annotations

import json
import sqlite3

from app.storage import connect

PATTERN_TIMEFRAMES: dict[str, tuple[str, ...]] = {
    "triangle": ("5m", "15m", "1h"),
    "flag": ("5m", "15m", "1h"),
    "divergence": ("5m", "15m", "1h"),
    "trendline": ("5m", "15m", "1h"),
    "channel": ("5m", "15m", "1h"),
    "ema50": ("5m", "15m", "1h"),
    "three_rp": ("1h",),
    "meaningful_behavior": ("1h",),
}


def pattern_timeframes(category: str) -> tuple[str, ...]:
    return PATTERN_TIMEFRAMES.get(category, ("5m", "15m", "1h"))


def ensure_pattern_settings() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pattern_settings (
                category TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                timeframes TEXT NOT NULL DEFAULT '[]'
            )
            """
        )


def _default(category: str) -> dict:
    return {
        "category": category,
        "enabled": True,
        "timeframes": list(pattern_timeframes(category)),
    }


def get_pattern_setting(category: str) -> dict:
    ensure_pattern_settings()
    allowed = pattern_timeframes(category)
    with connect() as conn:
        row = conn.execute(
            "SELECT enabled, timeframes FROM pattern_settings WHERE category = ?",
            (category,),
        ).fetchone()
    if row is None:
        return _default(category)
    try:
        raw = json.loads(row["timeframes"] or "[]")
    except json.JSONDecodeError:
        raw = []
    chosen = [tf for tf in raw if tf in allowed]
    return {
        "category": category,
        "enabled": bool(row["enabled"]),
        "timeframes": chosen,
    }


def save_pattern_setting(
    category: str,
    *,
    enabled: bool | None = None,
    timeframes: list[str] | None = None,
) -> dict:
    current = get_pattern_setting(category)
    allowed = pattern_timeframes(category)
    if enabled is None:
        enabled = bool(current["enabled"])
    if timeframes is None:
        chosen = list(current["timeframes"])
    else:
        chosen = [tf for tf in timeframes if tf in allowed]
    ensure_pattern_settings()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO pattern_settings (category, enabled, timeframes)
            VALUES (?, ?, ?)
            ON CONFLICT(category) DO UPDATE SET
                enabled = excluded.enabled,
                timeframes = excluded.timeframes
            """,
            (category, 1 if enabled else 0, json.dumps(chosen)),
        )
    return get_pattern_setting(category)


def signal_allowed(category: str, timeframe: str) -> bool:
    """سیگنال جدید فقط اگر الگو روشن باشد و تایم‌فریم تیک داشته باشد."""
    cfg = get_pattern_setting(category)
    if not cfg["enabled"]:
        return False
    return str(timeframe or "") in cfg["timeframes"]


def all_pattern_settings(categories: tuple[str, ...] | list[str]) -> dict[str, dict]:
    return {cat: get_pattern_setting(cat) for cat in categories}
