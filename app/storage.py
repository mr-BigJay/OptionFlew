from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from optionflow.report_service import ReportSnapshot

DEFAULT_DATA_DIR = Path(os.environ.get("OPTIONFLOW_DATA", "data"))


def data_dir() -> Path:
    d = DEFAULT_DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "optionflow.db"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                window_hours REAL NOT NULL,
                report_kind TEXT NOT NULL DEFAULT '4h',
                paragraph TEXT NOT NULL,
                headline TEXT,
                bias TEXT,
                score REAL,
                confidence_pct INTEGER,
                support_zone INTEGER,
                target_zone INTEGER,
                spot REAL,
                trade_count INTEGER,
                window_label TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(reports)")}
        if "window_label" not in cols:
            conn.execute("ALTER TABLE reports ADD COLUMN window_label TEXT DEFAULT ''")
        if "report_kind" not in cols:
            conn.execute(
                "ALTER TABLE reports ADD COLUMN report_kind TEXT DEFAULT '4h'"
            )


def insert_report(snapshot: ReportSnapshot) -> int:
    row = snapshot.to_row()
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO reports (
                created_at, window_hours, report_kind, paragraph, headline, bias, score,
                confidence_pct, support_zone, target_zone, spot, trade_count,
                window_label
            ) VALUES (
                :created_at, :window_hours, :report_kind, :paragraph, :headline, :bias, :score,
                :confidence_pct, :support_zone, :target_zone, :spot, :trade_count,
                :window_label
            )
            """,
            row,
        )
        return int(cur.lastrowid)


def get_report(report_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        return dict(row) if row else None


def get_latest_report(report_kind: str | None = None) -> dict[str, Any] | None:
    with connect() as conn:
        if report_kind:
            row = conn.execute(
                """
                SELECT * FROM reports
                WHERE report_kind = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (report_kind,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM reports ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None


def get_latest_reports_by_kind() -> dict[str, dict[str, Any] | None]:
    return {
        "4h": get_latest_report("4h"),
        "daily": get_latest_report("daily"),
    }


def list_reports(
    *,
    start_iso: str | None = None,
    end_iso: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM reports WHERE 1=1"
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
        return [dict(r) for r in rows]


def get_setting(key: str, default: str = "") -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
