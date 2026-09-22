from __future__ import annotations

import json
import logging
from typing import Any

from app.position_store import (
    close_position,
    get_config,
    has_open_pattern_category,
    has_open_report_kind,
    insert_open_position,
    list_positions,
    signal_seen,
)
from app.storage import list_reports
from optionflow.patterns.ohlc import load_btcusdt

logger = logging.getLogger("optionflow.paper")


def latest_btc_price() -> float | None:
    for tf in ("5m", "15m", "1h"):
        bars = load_btcusdt(tf, limit=3)
        if bars:
            return float(bars[-1].close)
    return None


def _direction_from_pattern(meta: dict[str, Any]) -> str | None:
    d = meta.get("direction")
    if d == "up":
        return "long"
    if d == "down":
        return "short"
    return None


def _direction_from_report(bias: str) -> str | None:
    b = (bias or "").lower()
    if any(x in b for x in ("bull", "long", "صعود", "خرید")):
        return "long"
    if any(x in b for x in ("bear", "short", "نزول", "فروش")):
        return "short"
    return None


def _source_risk(cfg: dict[str, Any], source_type: str, source_id: str) -> dict[str, float]:
    overrides = cfg.get("source_overrides") or {}
    block = overrides.get(f"{source_type}:{source_id}") or overrides.get(source_id) or {}
    return {
        "margin_usdt": float(block.get("margin_usdt") or cfg["margin_usdt"]),
        "leverage": float(block.get("leverage") or cfg["leverage"]),
        "stop_loss_pct": float(block.get("stop_loss_pct") or cfg["stop_loss_pct"]),
        "take_profit_pct": float(block.get("take_profit_pct") or cfg["take_profit_pct"]),
    }


def update_open_positions(user_id: int, mark_price: float) -> int:
    """SL/TP/لیکوئید ساده؛ تعداد بسته‌شده."""
    cfg = get_config(user_id)
    closed = 0
    for pos in list_positions(user_id, status="open", limit=50):
        entry = float(pos["entry_price"])
        direction = pos["direction"]
        sl = float(pos["sl_price"])
        tp = float(pos["tp_price"])
        margin = float(pos["margin_usdt"])
        notional = float(pos["notional_usdt"])
        if direction == "long":
            unreal = (mark_price - entry) / entry * notional
            hit_tp = mark_price >= tp
            hit_sl = mark_price <= sl
        else:
            unreal = (entry - mark_price) / entry * notional
            hit_tp = mark_price <= tp
            hit_sl = mark_price >= sl
        if unreal <= -margin * 0.95:
            if close_position(
                user_id,
                int(pos["id"]),
                exit_price=mark_price,
                status="closed_liquidated",
                fee_rate=float(cfg["fee_rate"]),
            ):
                closed += 1
            continue
        if hit_tp:
            if close_position(
                user_id,
                int(pos["id"]),
                exit_price=tp,
                status="closed_tp",
                fee_rate=float(cfg["fee_rate"]),
            ):
                closed += 1
        elif hit_sl:
            if close_position(
                user_id,
                int(pos["id"]),
                exit_price=sl,
                status="closed_sl",
                fee_rate=float(cfg["fee_rate"]),
            ):
                closed += 1
    return closed


def try_open_from_pattern_event(user_id: int, event: dict[str, Any]) -> int | None:
    cfg = get_config(user_id)
    if not cfg.get("enabled"):
        return None
    cat = str(event.get("category") or "")
    if cat not in (cfg.get("pattern_categories") or []):
        return None
    if has_open_pattern_category(user_id, cat):
        return None
    key = str(event.get("event_key") or f"pattern:{event.get('id')}")
    if signal_seen(user_id, key):
        return None
    meta = event.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    direction = _direction_from_pattern(meta)
    if not direction:
        return None
    price = latest_btc_price()
    if price is None:
        return None
    risk = _source_risk(cfg, "pattern", cat)
    return insert_open_position(
        user_id,
        source_type="pattern",
        source_key=key,
        timeframe=str(event.get("timeframe") or ""),
        direction=direction,
        entry_price=price,
        margin_usdt=risk["margin_usdt"],
        leverage=risk["leverage"],
        fee_rate=float(cfg["fee_rate"]),
        sl_pct=risk["stop_loss_pct"],
        tp_pct=risk["take_profit_pct"],
        signal_title=str(event.get("title_fa") or cat),
    )


def try_open_from_report(user_id: int, report: dict[str, Any]) -> int | None:
    cfg = get_config(user_id)
    if not cfg.get("enabled"):
        return None
    kind = str(report.get("report_kind") or "4h")
    if kind not in (cfg.get("report_kinds") or []):
        return None
    if has_open_report_kind(user_id, kind):
        return None
    rid = int(report["id"])
    key = f"report:{rid}"
    if signal_seen(user_id, key):
        return None
    direction = _direction_from_report(str(report.get("bias") or ""))
    if not direction:
        return None
    spot = report.get("spot")
    price = float(spot) if isinstance(spot, (int, float)) and spot > 0 else latest_btc_price()
    if price is None:
        return None
    risk = _source_risk(cfg, "report", kind)
    title = str(report.get("headline") or report.get("report_kind") or "گزارش")
    return insert_open_position(
        user_id,
        source_type="report",
        source_key=key,
        timeframe=kind,
        direction=direction,
        entry_price=price,
        margin_usdt=risk["margin_usdt"],
        leverage=risk["leverage"],
        fee_rate=float(cfg["fee_rate"]),
        sl_pct=risk["stop_loss_pct"],
        tp_pct=risk["take_profit_pct"],
        signal_title=title[:200],
    )


def process_signals_for_user(user_id: int, *, recent_events: list[dict] | None = None) -> dict[str, int]:
    """اسکن سیگنال‌های تازه + به‌روز SL/TP."""
    from datetime import datetime, timedelta, timezone

    from app.pattern_store import list_all_pattern_events

    stats = {"opened": 0, "closed": 0}
    mark = latest_btc_price()
    if mark is not None:
        stats["closed"] = update_open_positions(user_id, mark)
    cfg = get_config(user_id)
    if not cfg.get("enabled"):
        return stats
    events = recent_events
    if events is None:
        since = (
            datetime.now(timezone.utc) - timedelta(hours=6)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        events = list_all_pattern_events(start_iso=since, limit=40)
    for ev in events:
        pid = try_open_from_pattern_event(user_id, ev)
        if pid:
            stats["opened"] += 1
    reports = list_reports(limit=5)
    for rep in reports:
        pid = try_open_from_report(user_id, rep)
        if pid:
            stats["opened"] += 1
    return stats


def unrealized_pnl(pos: dict[str, Any], mark: float) -> float:
    entry = float(pos["entry_price"])
    notional = float(pos["notional_usdt"])
    if pos["direction"] == "long":
        return (mark - entry) / entry * notional
    return (entry - mark) / entry * notional


def live_open_state(user_id: int) -> dict[str, Any]:
    """قیمت مارک، PnL لحظه‌ای، و بستن خودکار SL/TP."""
    mark = latest_btc_price()
    closed = 0
    if mark is not None:
        closed = update_open_positions(user_id, mark)
    rows = list_positions(user_id, status="open", limit=50)
    items: list[dict[str, Any]] = []
    for p in rows:
        pnl = unrealized_pnl(p, mark) if mark is not None else None
        items.append(
            {
                "id": int(p["id"]),
                "direction": p["direction"],
                "leverage": float(p["leverage"]),
                "source_type": p["source_type"],
                "signal_title": p.get("signal_title") or "",
                "entry_price": float(p["entry_price"]),
                "sl_price": float(p["sl_price"]),
                "tp_price": float(p["tp_price"]),
                "pnl_usdt": round(pnl, 2) if pnl is not None else None,
            }
        )
    return {
        "mark": round(mark, 2) if mark is not None else None,
        "closed": closed,
        "open_count": len(items),
        "positions": items,
    }
