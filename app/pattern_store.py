from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.storage import connect
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.pattern_store")


def init_pattern_events_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pattern_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                pattern_id TEXT NOT NULL,
                event_key TEXT NOT NULL UNIQUE,
                title_fa TEXT NOT NULL DEFAULT '',
                status_fa TEXT NOT NULL DEFAULT '',
                summary_fa TEXT NOT NULL DEFAULT '',
                forecast_fa TEXT NOT NULL DEFAULT '',
                chart_file TEXT NOT NULL DEFAULT '',
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pattern_events_cat_time
                ON pattern_events(category, created_at DESC);
            """
        )


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def event_key_for_hit(hit: PatternHit) -> str:
    meta = hit.meta or {}
    stable = meta.get("alert_key")
    if not stable:
        parts = [
            hit.pattern_id,
            meta.get("confirm_index"),
            meta.get("entry_index"),
            meta.get("stage"),
        ]
        stable = ":".join(str(p) for p in parts if p is not None)
    return f"{hit.category}:{hit.timeframe}:{stable}"


def save_pattern_hit(hit: PatternHit, *, created_at: str | None = None) -> int | None:
    if not hit or not hit.category:
        return None
    key = event_key_for_hit(hit)
    ts = created_at or utc_now_iso()
    meta_json = json.dumps(hit.meta or {}, ensure_ascii=False, default=str)
    try:
        with connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO pattern_events (
                    category, timeframe, pattern_id, event_key,
                    title_fa, status_fa, summary_fa, forecast_fa,
                    chart_file, meta_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hit.category,
                    hit.timeframe,
                    hit.pattern_id,
                    key,
                    hit.title_fa,
                    hit.status_fa,
                    hit.summary_fa,
                    hit.forecast_fa,
                    hit.chart_file or "",
                    meta_json,
                    ts,
                ),
            )
            if cur.rowcount == 0:
                return None
            return int(cur.lastrowid)
    except Exception:
        logger.exception("save_pattern_hit failed key=%s", key)
        return None


def persist_scan_hits(
    hits: dict[str, PatternHit | None] | dict[str, dict[str, PatternHit | None]],
) -> None:
    """ذخیرهٔ رویدادهای جدید از اسکن (بدون تکرار event_key)."""
    if not hits:
        return
    sample = next(iter(hits.values()), None)
    if isinstance(sample, dict):
        for tf_map in hits.values():
            if not isinstance(tf_map, dict):
                continue
            for hit in tf_map.values():
                if hit:
                    save_pattern_hit(hit)
        return
    for hit in hits.values():
        if hit:
            save_pattern_hit(hit)


def list_pattern_events(
    category: str,
    *,
    start_iso: str | None = None,
    end_iso: str | None = None,
    limit: int = 300,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM pattern_events WHERE category = ?"
    params: list[Any] = [category]
    if start_iso:
        q += " AND created_at >= ?"
        params.append(start_iso)
    if end_iso:
        q += " AND created_at <= ?"
        params.append(end_iso)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(q, params).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["meta"] = json.loads(d.pop("meta_json") or "{}")
            except json.JSONDecodeError:
                d["meta"] = {}
            out.append(d)
        return out


def get_pattern_event(event_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM pattern_events WHERE id = ?", (event_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["meta"] = json.loads(d.pop("meta_json") or "{}")
        except json.JSONDecodeError:
            d["meta"] = {}
        return d
