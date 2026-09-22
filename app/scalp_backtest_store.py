from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.storage import connect, init_db


def ensure_scalp_backtest_schema() -> None:
    init_db()
    from app.scalp_store import init_scalp_db

    init_scalp_db()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scalp_backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                scenario_id TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                from_iso TEXT NOT NULL,
                to_iso TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                progress_pct INTEGER NOT NULL DEFAULT 0,
                bars_scanned INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                fail_count INTEGER NOT NULL DEFAULT 0,
                findings_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT NOT NULL DEFAULT '',
                findings_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_scalp_bt_created
                ON scalp_backtest_runs(created_at DESC);
            """
        )


def create_scalp_backtest_run(
    *,
    scenario_id: str,
    timeframe: str,
    from_iso: str,
    to_iso: str,
) -> int:
    ensure_scalp_backtest_schema()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO scalp_backtest_runs
            (created_at, scenario_id, timeframe, from_iso, to_iso, status, progress_pct)
            VALUES (?, ?, ?, ?, ?, 'running', 0)
            """,
            (now, scenario_id, timeframe, from_iso, to_iso),
        )
        return int(cur.lastrowid)


def update_scalp_backtest_progress(
    run_id: int, pct: int, bars_scanned: int = 0
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE scalp_backtest_runs
            SET progress_pct = ?, bars_scanned = ?
            WHERE id = ? AND status = 'running'
            """,
            (min(100, max(0, pct)), bars_scanned, run_id),
        )


def finish_scalp_backtest_run(run_id: int, result_dict: dict[str, Any]) -> None:
    findings = result_dict.get("findings", [])
    with connect() as conn:
        conn.execute(
            """
            UPDATE scalp_backtest_runs SET
              status = ?,
              progress_pct = 100,
              bars_scanned = ?,
              success_count = ?,
              fail_count = ?,
              findings_count = ?,
              error_message = ?,
              findings_json = ?
            WHERE id = ?
            """,
            (
                "done" if not result_dict.get("error") else "error",
                int(result_dict.get("bars_scanned", 0)),
                int(result_dict.get("success_count", 0)),
                int(result_dict.get("fail_count", 0)),
                len(findings),
                result_dict.get("error") or "",
                json.dumps(findings, ensure_ascii=False),
                run_id,
            ),
        )


def fail_scalp_backtest_run(run_id: int, message: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE scalp_backtest_runs SET status = 'error', progress_pct = 100,
            error_message = ? WHERE id = ?
            """,
            (message[:500], run_id),
        )


def cancel_scalp_backtest_run(
    run_id: int, *, message: str = "متوقف توسط کاربر"
) -> bool:
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE scalp_backtest_runs
            SET status = 'cancelled', error_message = ?
            WHERE id = ? AND status = 'running'
            """,
            (message[:500], run_id),
        )
        return cur.rowcount > 0


def get_scalp_backtest_run(run_id: int) -> dict[str, Any] | None:
    ensure_scalp_backtest_schema()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM scalp_backtest_runs WHERE id = ?", (run_id,)
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def list_scalp_backtest_runs(limit: int = 80) -> list[dict[str, Any]]:
    ensure_scalp_backtest_schema()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM scalp_backtest_runs
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["findings"] = json.loads(d.get("findings_json") or "[]")
    except json.JSONDecodeError:
        d["findings"] = []
    return d
