from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.exchange_fee_profiles import DEFAULT_FEE_PROFILE_ID, resolve_fee_rate
from app.storage import connect

logger = logging.getLogger("optionflow.position")

DEFAULT_FEE_RATE = resolve_fee_rate(DEFAULT_FEE_PROFILE_ID)

PATTERN_CATEGORIES = (
    "triangle",
    "flag",
    "divergence",
    "trendline",
    "channel",
    "ema50",
    "meaningful_behavior",
    "three_rp",
)

SCALP_SCENARIOS = (
    ("scalp_breakout", "شکست رنج 5m"),
    ("scalp_4h_rr", "۴HRR (رنج نیویork)"),
    ("scalp_trend_pullback", "پول‌بک ترند"),
)

REPORT_KINDS = (
    ("4h", "گزارش ۴ ساعته"),
    ("daily", "گزارش روزانه"),
)


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def init_position_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS paper_wallet (
                user_id INTEGER PRIMARY KEY,
                balance_usdt REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS paper_config (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                margin_usdt REAL NOT NULL DEFAULT 100,
                leverage REAL NOT NULL DEFAULT 5,
                stop_loss_pct REAL NOT NULL DEFAULT 1.0,
                take_profit_pct REAL NOT NULL DEFAULT 0.5,
                fee_rate REAL NOT NULL DEFAULT 0.0004,
                pattern_categories TEXT NOT NULL DEFAULT '[]',
                scalp_scenarios TEXT NOT NULL DEFAULT '[]',
                report_kinds TEXT NOT NULL DEFAULT '[]',
                source_overrides TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS paper_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_key TEXT NOT NULL,
                timeframe TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                margin_usdt REAL NOT NULL,
                leverage REAL NOT NULL,
                notional_usdt REAL NOT NULL,
                fee_open REAL NOT NULL,
                fee_close REAL,
                sl_price REAL NOT NULL,
                tp_price REAL NOT NULL,
                pnl_usdt REAL,
                signal_title TEXT NOT NULL DEFAULT '',
                opened_at TEXT NOT NULL,
                closed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_paper_pos_user_status
                ON paper_positions(user_id, status, opened_at DESC);
            CREATE TABLE IF NOT EXISTS paper_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                amount REAL NOT NULL,
                balance_after REAL NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                ref_id INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_paper_ledger_user
                ON paper_ledger(user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS paper_signal_seen (
                user_id INTEGER NOT NULL,
                signal_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, signal_key)
            );
            """
        )
        _migrate_paper_config(conn)


def _migrate_paper_config(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(paper_config)").fetchall()}
    if "fee_profile_id" not in cols:
        conn.execute(
            """
            ALTER TABLE paper_config
            ADD COLUMN fee_profile_id TEXT NOT NULL DEFAULT 'binance_usdt_vip0'
            """
        )


def _json_list(raw: str) -> list[str]:
    try:
        v = json.loads(raw or "[]")
        return [str(x) for x in v] if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _json_dict(raw: str) -> dict[str, Any]:
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}


def get_wallet(user_id: int) -> dict[str, Any]:
    init_position_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM paper_wallet WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            now = utc_now_iso()
            conn.execute(
                "INSERT INTO paper_wallet (user_id, balance_usdt, updated_at) VALUES (?, 0, ?)",
                (user_id, now),
            )
            return {"user_id": user_id, "balance_usdt": 0.0, "updated_at": now}
        return dict(row)


def get_config(user_id: int) -> dict[str, Any]:
    init_position_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM paper_config WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            now = utc_now_iso()
            conn.execute(
                """
                INSERT INTO paper_config (
                    user_id, enabled, margin_usdt, leverage, stop_loss_pct,
                    take_profit_pct, fee_rate, fee_profile_id, pattern_categories,
                    scalp_scenarios, report_kinds, source_overrides, updated_at
                ) VALUES (?, 0, 100, 5, 1.0, 0.5, ?, ?, '[]', '[]', '[]', '{}', ?)
                """,
                (user_id, DEFAULT_FEE_RATE, DEFAULT_FEE_PROFILE_ID, now),
            )
            row = conn.execute(
                "SELECT * FROM paper_config WHERE user_id = ?", (user_id,)
            ).fetchone()
        d = dict(row)
        d["pattern_categories"] = _json_list(d.get("pattern_categories") or "[]")
        d["scalp_scenarios"] = _json_list(d.get("scalp_scenarios") or "[]")
        d["report_kinds"] = _json_list(d.get("report_kinds") or "[]")
        d["source_overrides"] = _json_dict(d.get("source_overrides") or "{}")
        d["enabled"] = bool(d.get("enabled"))
        pid = str(d.get("fee_profile_id") or DEFAULT_FEE_PROFILE_ID)
        d["fee_profile_id"] = pid
        d["fee_rate"] = resolve_fee_rate(pid)
        return d


def save_config(user_id: int, **fields: Any) -> None:
    init_position_db()
    cfg = get_config(user_id)
    cfg.update(fields)
    pid = str(cfg.get("fee_profile_id") or DEFAULT_FEE_PROFILE_ID)
    cfg["fee_profile_id"] = pid
    cfg["fee_rate"] = resolve_fee_rate(pid)
    now = utc_now_iso()
    with connect() as conn:
        conn.execute(
            """
            UPDATE paper_config SET
                enabled = ?,
                margin_usdt = ?,
                leverage = ?,
                stop_loss_pct = ?,
                take_profit_pct = ?,
                fee_rate = ?,
                fee_profile_id = ?,
                pattern_categories = ?,
                scalp_scenarios = ?,
                report_kinds = ?,
                source_overrides = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                1 if cfg.get("enabled") else 0,
                float(cfg["margin_usdt"]),
                float(cfg["leverage"]),
                float(cfg["stop_loss_pct"]),
                float(cfg["take_profit_pct"]),
                float(cfg["fee_rate"]),
                pid,
                json.dumps(cfg.get("pattern_categories") or [], ensure_ascii=False),
                json.dumps(cfg.get("scalp_scenarios") or [], ensure_ascii=False),
                json.dumps(cfg.get("report_kinds") or [], ensure_ascii=False),
                json.dumps(cfg.get("source_overrides") or {}, ensure_ascii=False),
                now,
                user_id,
            ),
        )


def deposit(user_id: int, amount: float, note: str = "واریز تتر فرضی") -> float:
    if amount <= 0:
        raise ValueError("مبلغ باید مثبت باشد.")
    init_position_db()
    w = get_wallet(user_id)
    new_bal = float(w["balance_usdt"]) + amount
    now = utc_now_iso()
    with connect() as conn:
        conn.execute(
            "UPDATE paper_wallet SET balance_usdt = ?, updated_at = ? WHERE user_id = ?",
            (new_bal, now, user_id),
        )
        conn.execute(
            """
            INSERT INTO paper_ledger (user_id, kind, amount, balance_after, note, created_at)
            VALUES (?, 'deposit', ?, ?, ?, ?)
            """,
            (user_id, amount, new_bal, note, now),
        )
    return new_bal


def _append_ledger(
    conn,
    *,
    user_id: int,
    kind: str,
    amount: float,
    balance_after: float,
    note: str,
    ref_id: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO paper_ledger (user_id, kind, amount, balance_after, note, ref_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, kind, amount, balance_after, note, ref_id, utc_now_iso()),
    )


def locked_margin(user_id: int) -> float:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(margin_usdt), 0) AS s FROM paper_positions
            WHERE user_id = ? AND status = 'open'
            """,
            (user_id,),
        ).fetchone()
        return float(row["s"] or 0)


def list_positions(
    user_id: int,
    *,
    status: str | None = None,
    closed_only: bool = False,
    opened_from: str | None = None,
    opened_to: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    init_position_db()
    q = "SELECT * FROM paper_positions WHERE user_id = ?"
    params: list[Any] = [user_id]
    if status:
        q += " AND status = ?"
        params.append(status)
    if closed_only:
        q += " AND status != 'open'"
    if opened_from:
        q += " AND opened_at >= ?"
        params.append(opened_from)
    if opened_to:
        q += " AND opened_at < ?"
        params.append(opened_to)
    q += " ORDER BY opened_at DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def get_position(user_id: int, position_id: int) -> dict[str, Any] | None:
    init_position_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM paper_positions
            WHERE id = ? AND user_id = ?
            """,
            (position_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def list_ledger(user_id: int, limit: int = 80) -> list[dict[str, Any]]:
    init_position_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM paper_ledger WHERE user_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def signal_seen(user_id: int, signal_key: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM paper_signal_seen WHERE user_id = ? AND signal_key = ?",
            (user_id, signal_key),
        ).fetchone()
        return row is not None


def mark_signal_seen(user_id: int, signal_key: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_signal_seen (user_id, signal_key, created_at)
            VALUES (?, ?, ?)
            """,
            (user_id, signal_key, utc_now_iso()),
        )


def signal_consumed(user_id: int, signal_key: str) -> bool:
    """این سیگنال قبلاً ترید شده (باز یا بسته) — دوباره پوزیشن نگیر."""
    if signal_seen(user_id, signal_key):
        return True
    init_position_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM paper_positions
            WHERE user_id = ? AND source_key = ?
            LIMIT 1
            """,
            (user_id, signal_key),
        ).fetchone()
        return row is not None


def has_open_pattern_category(user_id: int, category: str) -> bool:
    """حداکثر یک پوزیشن باز به ازای هر دستهٔ الگو (مثلاً trendline)."""
    cat = (category or "").strip()
    if not cat:
        return False
    for p in list_positions(user_id, status="open", limit=80):
        if str(p.get("source_type") or "") != "pattern":
            continue
        sk = str(p.get("source_key") or "")
        if sk.startswith(f"{cat}:"):
            return True
        head = sk.split(":", 1)[0] if ":" in sk else ""
        if head == cat:
            return True
    return False


def has_open_report_kind(user_id: int, report_kind: str) -> bool:
    kind = (report_kind or "").strip()
    if not kind:
        return False
    init_position_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM paper_positions
            WHERE user_id = ? AND status = 'open' AND source_type = 'report'
              AND timeframe = ?
            LIMIT 1
            """,
            (user_id, kind),
        ).fetchone()
        return row is not None


def insert_open_position(
    user_id: int,
    *,
    source_type: str,
    source_key: str,
    timeframe: str,
    direction: str,
    entry_price: float,
    margin_usdt: float,
    leverage: float,
    fee_rate: float,
    sl_pct: float,
    tp_pct: float,
    signal_title: str,
) -> int | None:
    """باز کردن پوزیشن فرضی؛ None اگر موجودی کافی نباشد."""
    if direction not in ("long", "short"):
        return None
    entry = float(entry_price)
    if entry <= 0:
        return None
    margin = float(margin_usdt)
    lev = max(1.0, float(leverage))
    notional = margin * lev
    fee_open = notional * float(fee_rate)
    w = get_wallet(user_id)
    free = float(w["balance_usdt"])
    if free < margin + fee_open:
        return None
    if direction == "long":
        sl = entry * (1 - sl_pct / 100.0)
        tp = entry * (1 + tp_pct / 100.0)
    else:
        sl = entry * (1 + sl_pct / 100.0)
        tp = entry * (1 - tp_pct / 100.0)
    now = utc_now_iso()
    new_bal = free - margin - fee_open
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO paper_positions (
                user_id, status, source_type, source_key, timeframe, direction,
                entry_price, margin_usdt, leverage, notional_usdt, fee_open,
                sl_price, tp_price, signal_title, opened_at
            ) VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                source_type,
                source_key,
                timeframe,
                direction,
                entry,
                margin,
                lev,
                notional,
                fee_open,
                sl,
                tp,
                signal_title[:200],
                now,
            ),
        )
        pid = int(cur.lastrowid)
        conn.execute(
            "UPDATE paper_wallet SET balance_usdt = ?, updated_at = ? WHERE user_id = ?",
            (new_bal, now, user_id),
        )
        _append_ledger(
            conn,
            user_id=user_id,
            kind="fee_open",
            amount=-fee_open,
            balance_after=new_bal,
            note=f"کارمزد باز #{pid}",
            ref_id=pid,
        )
        _append_ledger(
            conn,
            user_id=user_id,
            kind="margin_lock",
            amount=-margin,
            balance_after=new_bal,
            note=f"مارجین پوز #{pid}",
            ref_id=pid,
        )
    mark_signal_seen(user_id, source_key)
    return pid


def close_position(
    user_id: int,
    position_id: int,
    *,
    exit_price: float,
    status: str,
    fee_rate: float,
) -> bool:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM paper_positions
            WHERE id = ? AND user_id = ? AND status = 'open'
            """,
            (position_id, user_id),
        ).fetchone()
        if row is None:
            return False
        pos = dict(row)
        entry = float(pos["entry_price"])
        exit_p = float(exit_price)
        notional = float(pos["notional_usdt"])
        margin = float(pos["margin_usdt"])
        direction = pos["direction"]
        if direction == "long":
            pnl = (exit_p - entry) / entry * notional
        else:
            pnl = (entry - exit_p) / entry * notional
        fee_close = notional * float(fee_rate)
        net = margin + pnl - fee_close
        w = conn.execute(
            "SELECT balance_usdt FROM paper_wallet WHERE user_id = ?", (user_id,)
        ).fetchone()
        free = float(w["balance_usdt"]) if w else 0.0
        new_bal = free + net
        now = utc_now_iso()
        conn.execute(
            """
            UPDATE paper_positions SET
                status = ?, exit_price = ?, fee_close = ?, pnl_usdt = ?, closed_at = ?
            WHERE id = ?
            """,
            (status, exit_p, fee_close, pnl, now, position_id),
        )
        conn.execute(
            "UPDATE paper_wallet SET balance_usdt = ?, updated_at = ? WHERE user_id = ?",
            (new_bal, now, user_id),
        )
        _append_ledger(
            conn,
            user_id=user_id,
            kind="pnl",
            amount=pnl,
            balance_after=new_bal,
            note=f"نتیجه #{position_id} ({status})",
            ref_id=position_id,
        )
        _append_ledger(
            conn,
            user_id=user_id,
            kind="fee_close",
            amount=-fee_close,
            balance_after=new_bal,
            note=f"کارمزد بست #{position_id}",
            ref_id=position_id,
        )
        _append_ledger(
            conn,
            user_id=user_id,
            kind="margin_release",
            amount=margin,
            balance_after=new_bal,
            note=f"آزاد مارجین #{position_id}",
            ref_id=position_id,
        )
    sk = str(pos.get("source_key") or "").strip()
    if sk:
        mark_signal_seen(user_id, sk)
    return True
