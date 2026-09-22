from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.storage import connect
from optionflow.patterns.types import PatternHit
from optionflow.scalp.scenarios import BUILTIN, merge_scenario_params, parse_json_list

logger = logging.getLogger("optionflow.scalp_store")


def init_scalp_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scalp_scenarios (
                scenario_id TEXT PRIMARY KEY,
                title_fa TEXT NOT NULL DEFAULT '',
                description_fa TEXT NOT NULL DEFAULT '',
                detector_type TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                timeframes_json TEXT NOT NULL DEFAULT '[]',
                params_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS scalp_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id TEXT NOT NULL,
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
            CREATE INDEX IF NOT EXISTS idx_scalp_events_created
                ON scalp_events(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_scalp_events_scenario
                ON scalp_events(scenario_id, created_at DESC);
            """
        )
    seed_builtin_scenarios()


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def seed_builtin_scenarios() -> None:
    now = utc_now_iso()
    with connect() as conn:
        for b in BUILTIN:
            conn.execute(
                """
                INSERT OR IGNORE INTO scalp_scenarios (
                    scenario_id, title_fa, description_fa, detector_type,
                    enabled, timeframes_json, params_json, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    b["scenario_id"],
                    b["title_fa"],
                    b["description_fa"],
                    b["detector_type"],
                    json.dumps(b["timeframes"], ensure_ascii=False),
                    json.dumps(b["params"], ensure_ascii=False),
                    now,
                ),
            )


def list_scenarios(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    init_scalp_db()
    q = "SELECT * FROM scalp_scenarios"
    if enabled_only:
        q += " WHERE enabled = 1"
    q += " ORDER BY scenario_id"
    with connect() as conn:
        rows = conn.execute(q).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["timeframes"] = parse_json_list(d.get("timeframes_json"))
        try:
            custom = json.loads(d.get("params_json") or "{}")
        except json.JSONDecodeError:
            custom = {}
        d["params"] = merge_scenario_params(
            {"scenario_id": d["scenario_id"], "params": custom}
        )
        out.append(d)
    return out


def get_scenario(scenario_id: str) -> dict[str, Any] | None:
    init_scalp_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM scalp_scenarios WHERE scenario_id = ?",
            (scenario_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["timeframes"] = parse_json_list(d.get("timeframes_json"))
    try:
        custom = json.loads(d.get("params_json") or "{}")
    except json.JSONDecodeError:
        custom = {}
    d["params"] = merge_scenario_params(
        {"scenario_id": d["scenario_id"], "params": custom}
    )
    return d


def update_scenario_settings(
    scenario_id: str,
    *,
    enabled: bool | None = None,
    params: dict[str, Any] | None = None,
) -> bool:
    init_scalp_db()
    if get_scenario(scenario_id) is None:
        return False
    sets: list[str] = ["updated_at = ?"]
    vals: list[Any] = [utc_now_iso()]
    if enabled is not None:
        sets.append("enabled = ?")
        vals.append(1 if enabled else 0)
    if params is not None:
        sets.append("params_json = ?")
        vals.append(json.dumps(params, ensure_ascii=False))
    vals.append(scenario_id)
    with connect() as conn:
        conn.execute(
            f"UPDATE scalp_scenarios SET {', '.join(sets)} WHERE scenario_id = ?",
            vals,
        )
    return True


def scalp_content_signature(hit: PatternHit) -> str:
    meta = hit.meta or {}
    sk = meta.get("setup_key") or meta.get("scenario_id") or hit.pattern_id
    stage = meta.get("stage") or "active"
    return f"{hit.pattern_id}:{stage}:{sk}"


def event_key_for_scalp(hit: PatternHit) -> str:
    meta = hit.meta or {}
    sid = meta.get("scenario_id") or hit.pattern_id
    sig = scalp_content_signature(hit)
    return f"scalp:{hit.timeframe}:{sid}:{sig}"


def save_scalp_hit(hit: PatternHit, *, created_at: str | None = None) -> int | None:
    if hit.category != "scalp":
        return None
    meta = hit.meta or {}
    scenario_id = str(meta.get("scenario_id") or "")
    if not scenario_id:
        return None
    key = event_key_for_scalp(hit)
    ts = created_at or utc_now_iso()
    meta_json = json.dumps(meta, ensure_ascii=False, default=str)
    try:
        with connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO scalp_events (
                    scenario_id, timeframe, pattern_id, event_key,
                    title_fa, status_fa, summary_fa, forecast_fa,
                    chart_file, meta_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id,
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
        logger.exception("save_scalp_hit failed key=%s", key)
        return None


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for d in rows:
        meta = d.get("meta") or {}
        sid = d.get("scenario_id") or meta.get("scenario_id") or ""
        fake = PatternHit(
            category="scalp",
            timeframe=str(d.get("timeframe") or ""),
            pattern_id=str(d.get("pattern_id") or ""),
            title_fa="",
            status_fa="",
            summary_fa="",
            forecast_fa="",
            meta={**meta, "scenario_id": sid},
        )
        bucket = event_key_for_scalp(fake)
        if bucket in seen:
            continue
        seen.add(bucket)
        out.append(d)
    return out


def list_scalp_events(
    *,
    scenario_id: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    init_scalp_db()
    q = "SELECT * FROM scalp_events WHERE 1=1"
    params: list[Any] = []
    if scenario_id:
        q += " AND scenario_id = ?"
        params.append(scenario_id)
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
    return _dedupe_rows(out)


def get_scalp_event(event_id: int) -> dict[str, Any] | None:
    init_scalp_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM scalp_events WHERE id = ?", (event_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["meta"] = json.loads(d.pop("meta_json") or "{}")
    except json.JSONDecodeError:
        d["meta"] = {}
    return d
