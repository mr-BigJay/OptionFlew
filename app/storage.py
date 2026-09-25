from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from optionflow.report_codes import manual_report_code, scheduled_report_code, tehran_date_key_compact
from optionflow.report_service import ReportKind, ReportSnapshot

DEFAULT_DATA_DIR = Path(os.environ.get("OPTIONFLOW_DATA", "data"))


def data_dir() -> Path:
    d = DEFAULT_DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "optionflow.db"


def users_db_path() -> Path:
    """Shared user accounts (stable + enrich on one VPS). Default: same as reports DB."""
    override = os.environ.get("OPTIONFLOW_AUTH_DB", "").strip()
    if override:
        return Path(override)
    return db_path()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def connect_users() -> Iterator[sqlite3.Connection]:
    path = users_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
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
                window_label TEXT DEFAULT '',
                pdh INTEGER,
                pdl INTEGER,
                pwh INTEGER,
                pwl INTEGER
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
        for col in ("pdh", "pdl", "pwh", "pwl"):
            if col not in cols:
                conn.execute(f"ALTER TABLE reports ADD COLUMN {col} INTEGER")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(reports)")}
        if "report_code" not in cols:
            conn.execute("ALTER TABLE reports ADD COLUMN report_code TEXT")
        if "is_manual" not in cols:
            conn.execute(
                "ALTER TABLE reports ADD COLUMN is_manual INTEGER NOT NULL DEFAULT 0"
            )
        if "expires_at" not in cols:
            conn.execute("ALTER TABLE reports ADD COLUMN expires_at TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_code "
            "ON reports(report_code) WHERE report_code IS NOT NULL AND report_code != ''"
        )
    from app.pattern_store import init_pattern_events_db
    from app.scalp_store import init_scalp_db

    init_pattern_events_db()
    from app.position_store import init_position_db

    init_position_db()
    init_scalp_db()
    from app.indicator_store import init_indicator_db

    init_indicator_db()


def _upsert_scheduled(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    code = row["report_code"]
    existing = conn.execute(
        "SELECT id FROM reports WHERE report_code = ?", (code,)
    ).fetchone()
    cols = _report_columns()
    if existing:
        conn.execute(
            f"""
            UPDATE reports SET
                created_at = :created_at,
                window_hours = :window_hours,
                report_kind = :report_kind,
                paragraph = :paragraph,
                headline = :headline,
                bias = :bias,
                score = :score,
                confidence_pct = :confidence_pct,
                support_zone = :support_zone,
                target_zone = :target_zone,
                spot = :spot,
                trade_count = :trade_count,
                window_label = :window_label,
                pdh = :pdh,
                pdl = :pdl,
                pwh = :pwh,
                pwl = :pwl,
                is_manual = 0,
                expires_at = NULL
            WHERE report_code = :report_code
            """,
            row,
        )
        return int(existing["id"])
    cur = conn.execute(
        f"""
        INSERT INTO reports ({cols}) VALUES (
            :created_at, :window_hours, :report_kind, :paragraph, :headline, :bias, :score,
            :confidence_pct, :support_zone, :target_zone, :spot, :trade_count,
            :window_label, :pdh, :pdl, :pwh, :pwl, :report_code, :is_manual, :expires_at
        )
        """,
        row,
    )
    return int(cur.lastrowid)


def _report_columns() -> str:
    return """
                created_at, window_hours, report_kind, paragraph, headline, bias, score,
                confidence_pct, support_zone, target_zone, spot, trade_count,
                window_label, pdh, pdl, pwh, pwl, report_code, is_manual, expires_at
            """


def _scheduled_only_sql(extra: str = "") -> str:
    return (
        f"(is_manual IS NULL OR is_manual = 0) {extra}"
    )


def purge_expired_manual_reports() -> int:
    now = utc_now_iso()
    with connect() as conn:
        cur = conn.execute(
            """
            DELETE FROM reports
            WHERE is_manual = 1 AND expires_at IS NOT NULL AND expires_at <= ?
            """,
            (now,),
        )
        return cur.rowcount


def _next_manual_index(conn: sqlite3.Connection, date_key: str) -> int:
    prefix = f"{date_key}-j"
    rows = conn.execute(
        "SELECT report_code FROM reports WHERE report_code LIKE ? ESCAPE '\\'",
        (f"{prefix}%",),
    ).fetchall()
    max_n = 0
    for row in rows:
        code = row["report_code"] or ""
        if not code.startswith(prefix):
            continue
        suffix = code[len(prefix) :]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    return max_n + 1


def save_scheduled_report(snapshot: ReportSnapshot) -> int:
    """Insert or replace scheduled report keyed by report_code (4h slot / daily)."""
    from optionflow.report_chart import chart_png_for_snapshot

    purge_expired_manual_reports()
    kind: ReportKind = snapshot.report_kind  # type: ignore[assignment]
    code = snapshot.report_code or scheduled_report_code(kind)
    snapshot.report_code = code
    row = snapshot.to_row()
    row["report_code"] = code
    row["is_manual"] = 0
    row["expires_at"] = None
    with connect() as conn:
        rid = _upsert_scheduled(conn, row)
    png = chart_png_for_snapshot(snapshot)
    if png:
        save_report_chart(code, png)
    return rid


def save_manual_report(snapshot: ReportSnapshot) -> int:
    """Manual run (تولید الان): YYYYMMDD-jn, expires 24h after creation."""
    from optionflow.report_chart import chart_png_for_snapshot

    purge_expired_manual_reports()
    created = parse_iso(snapshot.created_at)
    expires = (created + timedelta(hours=24)).replace(microsecond=0)
    expires_iso = expires.isoformat().replace("+00:00", "Z")
    date_key = tehran_date_key_compact(created)
    row = snapshot.to_row()
    with connect() as conn:
        idx = _next_manual_index(conn, date_key)
        code = manual_report_code(date_key, idx)
        row["report_code"] = code
        row["is_manual"] = 1
        row["expires_at"] = expires_iso
        cols = _report_columns()
        cur = conn.execute(
            f"""
            INSERT INTO reports ({cols}) VALUES (
                :created_at, :window_hours, :report_kind, :paragraph, :headline, :bias, :score,
                :confidence_pct, :support_zone, :target_zone, :spot, :trade_count,
                :window_label, :pdh, :pdl, :pwh, :pwl, :report_code, :is_manual, :expires_at
            )
            """,
            row,
        )
        rid = int(cur.lastrowid)
    snapshot.report_code = code
    png = chart_png_for_snapshot(snapshot)
    if png:
        save_report_chart(code, png)
    return rid


def insert_report(snapshot: ReportSnapshot) -> int:
    """Backward-compatible alias for scheduled save."""
    return save_scheduled_report(snapshot)


def get_report(report_id: int) -> dict[str, Any] | None:
    purge_expired_manual_reports()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not row:
            return None
        r = dict(row)
        if r.get("is_manual") and r.get("expires_at"):
            if r["expires_at"] <= utc_now_iso():
                conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
                return None
        return r


def get_latest_report(
    report_kind: str | None = None, *, scheduled_only: bool = False
) -> dict[str, Any] | None:
    """آخرین گزارش هر kind (زمان‌بندی‌شده یا دستی معتبر)."""
    purge_expired_manual_reports()
    now = utc_now_iso()
    visible = """
        (is_manual IS NULL OR is_manual = 0
         OR (expires_at IS NOT NULL AND expires_at > ?))
    """
    manual_clause = " AND (is_manual IS NULL OR is_manual = 0)" if scheduled_only else ""
    with connect() as conn:
        if report_kind:
            row = conn.execute(
                f"""
                SELECT * FROM reports
                WHERE report_kind = ? AND {visible}{manual_clause}
                ORDER BY created_at DESC LIMIT 1
                """,
                (report_kind, now),
            ).fetchone()
        else:
            row = conn.execute(
                f"""
                SELECT * FROM reports
                WHERE {visible}{manual_clause}
                ORDER BY created_at DESC LIMIT 1
                """,
                (now,),
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
    scheduled_only: bool = False,
) -> list[dict[str, Any]]:
    purge_expired_manual_reports()
    now = utc_now_iso()
    manual_clause = " AND (is_manual IS NULL OR is_manual = 0)" if scheduled_only else ""
    q = f"""
        SELECT * FROM reports WHERE 1=1
        AND (is_manual IS NULL OR is_manual = 0
             OR (expires_at IS NOT NULL AND expires_at > ?))
        {manual_clause}
    """
    params: list[Any] = [now]
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


def chart_path_for_code(report_code: str) -> Path:
    return data_dir() / "charts" / f"{report_code}.png"


def save_report_chart(report_code: str, png: bytes) -> Path | None:
    if not report_code or not png:
        return None
    path = chart_path_for_code(report_code)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def report_has_chart(report_code: str | None) -> bool:
    if not report_code:
        return False
    return chart_path_for_code(report_code).is_file()


def ensure_report_chart(report: dict[str, Any] | None) -> None:
    """اگر PNG نیست، چارت را از متن یا سطوح گزارش می‌سازد."""
    if not report:
        return
    code = report.get("report_code")
    if not code or report_has_chart(code):
        return
    from optionflow.report_chart import chart_png_for_report_row

    png = chart_png_for_report_row(report)
    if png:
        save_report_chart(code, png)
        return
    logging.getLogger("optionflow.storage").warning(
        "Chart not built for %s kind=%s (check prose-v3 or matplotlib/Binance)",
        code,
        report.get("report_kind"),
    )


def parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
