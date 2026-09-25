from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.pattern_store import trade_key_for_hit
from app.position_store import (
    close_position,
    get_config,
    has_open_pattern_category,
    selected_timeframes,
    has_open_report_kind,
    insert_open_position,
    list_positions,
    signal_consumed,
)
from app.storage import list_reports
from optionflow.patterns.behavior_service import (
    get_cached_behavior_scan,
    invalidate_behavior_cache,
)
from optionflow.patterns.ohlc import load_btcusdt
from optionflow.patterns.service import (
    get_cached_scan,
    invalidate_pattern_cache,
    patterns_data_dir,
)
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.paper")

# گزارش فقط اگر تازه منتشر شده باشد (هم‌زمان با «لایو»)
REPORT_FRESH_MINUTES = 90


def latest_btc_price() -> float | None:
    for tf in ("5m", "15m", "1h"):
        bars = load_btcusdt(tf, limit=3)
        if bars:
            return float(bars[-1].close)
    return None


def pattern_hit_allows_entry(hit: PatternHit, cfg: dict[str, Any] | None = None) -> bool:
    """ترندلاین فقط با لمس خط. الگوهای دارای تأیید اولیه طبق تیک تنظیمات."""
    cat = str(hit.category or "")
    meta = hit.meta or {}
    if cat == "trendline" and not meta.get("testing"):
        return False
    from app.position_store import PATTERN_EARLY_CATEGORIES

    if cat not in PATTERN_EARLY_CATEGORIES:
        return True
    want_early = cat in ((cfg or {}).get("pattern_early") or [])
    stage = str(meta.get("stage") or "")
    if want_early:
        return stage == "early"
    return stage != "early"


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


def collect_live_pattern_hits(
    chart_dir: Path,
    data_root: Path,
    *,
    refresh: bool = True,
) -> list[PatternHit]:
    """همان hitهای اسکن زندهٔ بخش الگوها (نه آرشیو ۶ ساعته DB)."""
    if refresh:
        invalidate_pattern_cache()
        invalidate_behavior_cache()
    hits: list[PatternHit] = []
    scan = get_cached_scan(chart_dir)
    for tf_map in scan.values():
        if not isinstance(tf_map, dict):
            continue
        for hit in tf_map.values():
            if hit is not None:
                hits.append(hit)
    behavior = get_cached_behavior_scan(
        chart_dir, data_root=data_root, notify=False
    )
    for hit in behavior.values():
        if hit is not None:
            hits.append(hit)
    return hits


def try_open_from_pattern_hit(user_id: int, hit: PatternHit) -> int | None:
    cfg = get_config(user_id)
    if not cfg.get("enabled"):
        return None
    cat = str(hit.category or "")
    if cat not in (cfg.get("pattern_categories") or []):
        return None
    if not pattern_hit_allows_entry(hit, cfg):
        return None
    tf = str(hit.timeframe or "")
    if tf not in selected_timeframes(cfg, cat):
        return None
    if has_open_pattern_category(user_id, cat):
        return None
    key = trade_key_for_hit(hit)
    if signal_consumed(user_id, key):
        return None
    meta = hit.meta or {}
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
        timeframe=str(hit.timeframe or ""),
        direction=direction,
        entry_price=price,
        margin_usdt=risk["margin_usdt"],
        leverage=risk["leverage"],
        fee_rate=float(cfg["fee_rate"]),
        sl_pct=risk["stop_loss_pct"],
        tp_pct=risk["take_profit_pct"],
        signal_title=str(hit.title_fa or cat),
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
    if signal_consumed(user_id, key):
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


def _fresh_reports() -> list[dict[str, Any]]:
    since = (
        datetime.now(timezone.utc) - timedelta(minutes=REPORT_FRESH_MINUTES)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return list_reports(start_iso=since, limit=10)


def process_signals_for_user(
    user_id: int,
    *,
    data_root: Path | None = None,
    chart_dir: Path | None = None,
    refresh_scan: bool = True,
) -> dict[str, int]:
    """اسکن زندهٔ الگو + گزارش تازه؛ بدون باز کردن از رویدادهای قدیمی DB."""
    from app.storage import data_dir

    stats = {"opened": 0, "closed": 0}
    mark = latest_btc_price()
    if mark is not None:
        stats["closed"] = update_open_positions(user_id, mark)
    cfg = get_config(user_id)
    if not cfg.get("enabled"):
        return stats

    root = data_root or data_dir()
    charts = chart_dir or patterns_data_dir(root)

    for hit in collect_live_pattern_hits(
        charts, root, refresh=refresh_scan
    ):
        pid = try_open_from_pattern_hit(user_id, hit)
        if pid:
            stats["opened"] += 1

    for rep in _fresh_reports():
        pid = try_open_from_report(user_id, rep)
        if pid:
            stats["opened"] += 1

    if "nabzbours" in (cfg.get("scalp_scenarios") or []):
        opened = _open_nabzbours(user_id, charts)
        stats["opened"] += opened
    return stats


def _open_nabzbours(user_id: int, chart_dir: Path) -> int:
    """ورود مستقل نبض‌بورس — فقط اگر در تنظیم پوزیشن تیک خورده باشد."""
    from app.scalp_store import list_scenarios
    from optionflow.scalp.service import get_cached_scalp_scan

    cfg = get_config(user_id)
    if not cfg.get("enabled"):
        return 0
    scenarios = [
        s for s in list_scenarios(enabled_only=True) if s.get("scenario_id") == "nabzbours"
    ]
    if not scenarios:
        return 0
    opened = 0
    for hit in get_cached_scalp_scan(chart_dir, scenarios):
        if (hit.meta or {}).get("scenario_id") != "nabzbours":
            continue
        if _try_open_nabz(user_id, hit):
            opened += 1
    return opened


def _try_open_nabz(user_id: int, hit: PatternHit) -> int | None:
    cfg = get_config(user_id)
    meta = hit.meta or {}
    key = f"nabzbours:{hit.timeframe}:{meta.get('setup_key')}"
    if signal_consumed(user_id, key):
        return None
    direction = _direction_from_pattern(meta)
    price = float(meta.get("entry_px") or 0) or latest_btc_price()
    if not direction or not price:
        return None
    stop = float(meta.get("stop_px") or 0)
    tp = float(meta.get("tp_px") or 0)
    if stop <= 0 or tp <= 0:
        return None
    sl_pct = abs(price - stop) / price * 100.0
    tp_pct = abs(tp - price) / price * 100.0
    risk = _source_risk(cfg, "scalp", "nabzbours")
    return insert_open_position(
        user_id,
        source_type="scalp",
        source_key=key,
        timeframe=str(hit.timeframe or "5m"),
        direction=direction,
        entry_price=price,
        margin_usdt=risk["margin_usdt"],
        leverage=risk["leverage"],
        fee_rate=float(cfg["fee_rate"]),
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        signal_title=f"نبض‌بورس · امتیاز {meta.get('score', '')}",
    )


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
