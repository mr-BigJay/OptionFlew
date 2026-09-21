from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.storage import connect, data_dir, init_db


def ensure_backtest_schema() -> None:
    init_db()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                category TEXT NOT NULL,
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
            CREATE INDEX IF NOT EXISTS idx_backtest_created ON backtest_runs(created_at);
            """
        )


def create_backtest_run(
    *,
    category: str,
    timeframe: str,
    from_iso: str,
    to_iso: str,
    target_profit_pct: float | None = None,
) -> int:
    ensure_backtest_schema()
    _ensure_backtest_target_column()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO backtest_runs
            (created_at, category, timeframe, from_iso, to_iso, status, progress_pct, target_profit_pct)
            VALUES (?, ?, ?, ?, ?, 'running', 0, ?)
            """,
            (now, category, timeframe, from_iso, to_iso, target_profit_pct),
        )
        return int(cur.lastrowid)


def _ensure_backtest_target_column() -> None:
    with connect() as conn:
        try:
            conn.execute(
                "ALTER TABLE backtest_runs ADD COLUMN target_profit_pct REAL"
            )
        except sqlite3.OperationalError:
            pass


def update_backtest_progress(run_id: int, pct: int, bars_scanned: int = 0) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE backtest_runs
            SET progress_pct = ?, bars_scanned = ?
            WHERE id = ? AND status = 'running'
            """,
            (min(100, max(0, pct)), bars_scanned, run_id),
        )


def finish_backtest_run(run_id: int, result_dict: dict[str, Any]) -> None:
    findings = result_dict.get("findings", [])
    with connect() as conn:
        conn.execute(
            """
            UPDATE backtest_runs SET
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


def fail_backtest_run(run_id: int, message: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE backtest_runs SET status = 'error', progress_pct = 100,
            error_message = ? WHERE id = ?
            """,
            (message[:500], run_id),
        )


def get_backtest_run(run_id: int) -> dict[str, Any] | None:
    ensure_backtest_schema()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM backtest_runs WHERE id = ?", (run_id,)
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def list_backtest_runs(limit: int = 100) -> list[dict[str, Any]]:
    ensure_backtest_schema()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM backtest_runs
            ORDER BY id DESC
            LIMIT ?
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
