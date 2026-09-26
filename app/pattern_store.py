from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.storage import connect
from optionflow.patterns.dedupe import backtest_dedupe_key
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


def _meta_pivot_price(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return int(round(float(value[1])))
        except (TypeError, ValueError):
            return None
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    return None


def _trendline_line_signature(
    category: str,
    pattern_id: str,
    meta: dict[str, Any],
    timeframe: str,
) -> str:
    """همان خط، با وجود جابه‌جایی قیمت لحظه‌ای، یک سیگنال است."""
    hit = PatternHit(
        category=category,
        timeframe=timeframe or "15m",
        pattern_id=pattern_id,
        title_fa="",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta=meta,
    )
    key = backtest_dedupe_key(hit)
    prefix = f"{category}:"
    return key[len(prefix) :] if key.startswith(prefix) else key


def pattern_content_signature(
    *,
    category: str,
    pattern_id: str,
    meta: dict[str, Any],
    timeframe: str = "",
) -> str:
    """هویت پایدار الگو — بدون وابستگی به اندیس کندل که با اسکن جابه‌جا می‌شود."""
    alert = meta.get("alert_key")
    if alert:
        return str(alert)
    stage = str(meta.get("stage") or "")
    if category == "divergence":
        pa = _meta_pivot_price(meta.get("pivot_a"))
        pb = _meta_pivot_price(meta.get("pivot_b"))
        ra, rb = meta.get("rsi_a"), meta.get("rsi_b")
        rsi = ""
        if isinstance(ra, (int, float)) and isinstance(rb, (int, float)):
            rsi = f":r{round(float(ra), 1)}:{round(float(rb), 1)}"
        return f"{pattern_id}:{stage}:p{pa}:p{pb}{rsi}"
    if category == "ema50":
        ep = meta.get("entry_px")
        px = int(round(float(ep))) if isinstance(ep, (int, float)) else 0
        return f"{pattern_id}:e{px}"
    if category in ("trendline", "channel"):
        return _trendline_line_signature(category, pattern_id, meta, timeframe)
    if category == "triangle":
        kind = meta.get("kind") or ""
        u = meta.get("upper_now")
        lo = meta.get("lower_now")
        uk = int(round(float(u))) if isinstance(u, (int, float)) else 0
        lk = int(round(float(lo))) if isinstance(lo, (int, float)) else 0
        return f"{pattern_id}:{stage}:{kind}:u{uk}:l{lk}"
    if category == "flag":
        fh = meta.get("flag_high")
        fl = meta.get("flag_low")
        d = meta.get("direction") or ""
        fhk = int(round(float(fh))) if isinstance(fh, (int, float)) else 0
        flk = int(round(float(fl))) if isinstance(fl, (int, float)) else 0
        return f"{pattern_id}:{d}:h{fhk}:l{flk}"
    if category == "three_rp":
        sts = meta.get("signal_ts")
        if sts:
            d = meta.get("direction") or ""
            return f"{pattern_id}:enh:{sts}:{d}"
        px = meta.get("pattern_low") if "bear" in pattern_id else meta.get("pattern_high")
        pk = int(round(float(px))) if isinstance(px, (int, float)) else 0
        return f"{pattern_id}:enh:p{pk}"
    return f"{pattern_id}:{stage}"


def trade_signature_for_hit(hit: PatternHit) -> str:
    """امضای setup برای paper — بدون stage تا بعد از بستن دوباره باز نشود."""
    meta = hit.meta or {}
    category = hit.category
    pattern_id = hit.pattern_id
    alert = meta.get("alert_key")
    if alert:
        return str(alert)
    if category == "divergence":
        pa = _meta_pivot_price(meta.get("pivot_a"))
        pb = _meta_pivot_price(meta.get("pivot_b"))
        ra, rb = meta.get("rsi_a"), meta.get("rsi_b")
        rsi = ""
        if isinstance(ra, (int, float)) and isinstance(rb, (int, float)):
            rsi = f":r{round(float(ra), 1)}:{round(float(rb), 1)}"
        return f"{pattern_id}:p{pa}:p{pb}{rsi}"
    if category == "ema50":
        ep = meta.get("entry_px")
        px = int(round(float(ep))) if isinstance(ep, (int, float)) else 0
        return f"{pattern_id}:e{px}"
    if category in ("trendline", "channel"):
        return _trendline_line_signature(
            category, pattern_id, meta, str(hit.timeframe or "")
        )
    if category == "triangle":
        kind = meta.get("kind") or ""
        u = meta.get("upper_now")
        lo = meta.get("lower_now")
        uk = int(round(float(u))) if isinstance(u, (int, float)) else 0
        lk = int(round(float(lo))) if isinstance(lo, (int, float)) else 0
        return f"{pattern_id}:{kind}:u{uk}:l{lk}"
    if category == "flag":
        fh = meta.get("flag_high")
        fl = meta.get("flag_low")
        d = meta.get("direction") or ""
        fhk = int(round(float(fh))) if isinstance(fh, (int, float)) else 0
        flk = int(round(float(fl))) if isinstance(fl, (int, float)) else 0
        return f"{pattern_id}:{d}:h{fhk}:l{flk}"
    if category == "three_rp":
        sts = meta.get("signal_ts")
        if sts:
            d = meta.get("direction") or ""
            return f"{pattern_id}:enh:{sts}:{d}"
        px = meta.get("pattern_low") if "bear" in pattern_id else meta.get("pattern_high")
        pk = int(round(float(px))) if isinstance(px, (int, float)) else 0
        return f"{pattern_id}:enh:p{pk}"
    if category == "meaningful_behavior":
        return str(meta.get("alert_key") or pattern_id)
    stage = str(meta.get("stage") or "")
    return f"{pattern_id}:{stage}"


def trade_key_for_hit(hit: PatternHit) -> str:
    sig = trade_signature_for_hit(hit)
    return f"{hit.category}:{hit.timeframe}:{sig}"


def event_key_for_hit(hit: PatternHit) -> str:
    meta = hit.meta or {}
    sig = pattern_content_signature(
        category=hit.category,
        pattern_id=hit.pattern_id,
        meta=meta,
        timeframe=str(hit.timeframe or ""),
    )
    return f"{hit.category}:{hit.timeframe}:{sig}"


def _dedupe_event_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """یک ردیف به ازای هر الگوی واقعی (جدیدترین created_at)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for d in rows:
        meta = d.get("meta") or {}
        sig = pattern_content_signature(
            category=str(d.get("category") or ""),
            pattern_id=str(d.get("pattern_id") or ""),
            meta=meta,
            timeframe=str(d.get("timeframe") or ""),
        )
        bucket = f"{d.get('category')}:{d.get('timeframe')}:{sig}"
        if bucket in seen:
            continue
        seen.add(bucket)
        out.append(d)
    return out


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
    from app.pattern_settings import signal_allowed

    if isinstance(sample, dict):
        for tf_map in hits.values():
            if not isinstance(tf_map, dict):
                continue
            for hit in tf_map.values():
                if hit and signal_allowed(hit.category, hit.timeframe):
                    save_pattern_hit(hit)
        return
    for hit in hits.values():
        if hit and signal_allowed(hit.category, hit.timeframe):
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
        return _dedupe_event_rows(out)


def list_all_pattern_events(
    *,
    start_iso: str | None = None,
    end_iso: str | None = None,
    limit: int = 400,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM pattern_events WHERE 1=1"
    params: list[Any] = []
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
        return _dedupe_event_rows(out)


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


def _event_from_row(row: Any) -> dict[str, Any]:
    d = dict(row)
    try:
        d["meta"] = json.loads(d.pop("meta_json") or "{}")
    except json.JSONDecodeError:
        d["meta"] = {}
    return d


def get_pattern_event_by_key(event_key: str) -> dict[str, Any] | None:
    key = (event_key or "").strip()
    if not key:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM pattern_events WHERE event_key = ?",
            (key,),
        ).fetchone()
    return _event_from_row(row) if row else None


def _legacy_y_key(ev: dict[str, Any]) -> str:
    """کلید قدیمی پوزیشن: قیمت لحظه‌ای خط، قبل از هویت پایدار برخوردها."""
    meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
    y = meta.get("y_now")
    if not isinstance(y, (int, float)):
        return ""
    side = str(meta.get("side") or meta.get("early_side") or "")
    pid = str(ev.get("pattern_id") or "")
    return (
        f"{ev.get('category')}:{ev.get('timeframe')}:"
        f"{pid}:{side}:y{int(round(float(y)))}"
    )


def get_pattern_event_by_trade_key(trade_key: str) -> dict[str, Any] | None:
    """پوزیشن با trade_key ذخیره می‌شود؛ رویداد با event_key."""
    key = (trade_key or "").strip()
    parts = key.split(":", 2)
    if len(parts) < 3:
        return None
    category, timeframe, _sig = parts
    direct = get_pattern_event_by_key(key)
    if direct:
        return direct
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM pattern_events
            WHERE category = ? AND timeframe = ?
            ORDER BY created_at DESC
            LIMIT 300
            """,
            (category, timeframe),
        ).fetchall()
    legacy_hit: dict[str, Any] | None = None
    for row in rows:
        ev = _event_from_row(row)
        meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
        hit = PatternHit(
            category=str(ev.get("category") or ""),
            timeframe=str(ev.get("timeframe") or ""),
            pattern_id=str(ev.get("pattern_id") or ""),
            title_fa=str(ev.get("title_fa") or ""),
            status_fa="",
            summary_fa="",
            forecast_fa="",
            meta=meta,
        )
        if trade_key_for_hit(hit) == key or _legacy_y_key(ev) == key:
            return ev
        if (
            legacy_hit is None
            and ":y" in key
            and _legacy_y_key(ev)
            and _legacy_side_matches(key, ev)
        ):
            legacy_hit = ev
    return legacy_hit


def _legacy_side_matches(trade_key: str, ev: dict[str, Any]) -> bool:
    meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
    side = str(meta.get("side") or meta.get("early_side") or "")
    if not side:
        return True
    return f":{side}:y" in trade_key or trade_key.endswith(f":{side}")
