from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from optionflow.deribit_client import DeribitClient
from optionflow.flow_analyzer import parse_instrument, top_strikes
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

# رفتار معنادار — فلو آپشن Deribit (مستقل از الگوهای کندلی)
TAKE_PROFIT_PCT = 0.005
SURGE_RATIO = 2.2
MIN_BURST_BTC = 28.0
MIN_BASELINE_BTC = 8.0

# burst = آخرین N دقیقه؛ baseline = کل پنجرهٔ قبل از burst (فقط تایم‌فریم 1h)
WINDOW_CFG: dict[str, tuple[int, float]] = {
    "1h": (20, 4.0),
}


def _contracts(trade: dict[str, Any]) -> float:
    return float(trade.get("contracts") or trade.get("amount") or 0)


def _aggregate(
    trades: list[dict[str, Any]],
    *,
    start_ms: int,
    end_ms: int,
) -> tuple[float, float, float, float, dict[float, float], dict[float, float]]:
    bc = bp = sc = sp = 0.0
    call_buy: dict[float, float] = defaultdict(float)
    put_buy: dict[float, float] = defaultdict(float)
    for t in trades:
        ts = int(t.get("timestamp") or 0)
        if ts < start_ms or ts > end_ms:
            continue
        strike, opt = parse_instrument(t["instrument_name"])
        direction = t["direction"]
        c = _contracts(t)
        if direction == "buy" and opt == "call":
            bc += c
            call_buy[strike] += c
        elif direction == "buy" and opt == "put":
            bp += c
            put_buy[strike] += c
        elif direction == "sell" and opt == "call":
            sc += c
        elif direction == "sell" and opt == "put":
            sp += c
    return bc, bp, sc, sp, dict(call_buy), dict(put_buy)


def _surge_ok(burst: float, baseline: float, baseline_minutes: float, burst_minutes: float) -> bool:
    if burst < MIN_BURST_BTC:
        return False
    if baseline < MIN_BASELINE_BTC and burst < MIN_BURST_BTC * 1.4:
        return False
    base_rate = baseline / max(baseline_minutes, 1.0)
    burst_rate = burst / max(burst_minutes, 1.0)
    if base_rate <= 0:
        return burst >= MIN_BURST_BTC * 1.5
    return burst_rate >= base_rate * SURGE_RATIO


def _alert_key(tf: str, pattern_id: str, end_ms: int, burst: float) -> str:
    bucket = end_ms // (15 * 60 * 1000)
    return f"{tf}:{pattern_id}:{bucket}:{int(burst // 5)}"


def evaluate_behavior_path(
    bars: list[OhlcBar],
    hit: PatternHit,
) -> tuple[bool | None, str]:
    meta = hit.meta
    direction = meta.get("direction")
    if direction not in ("up", "down"):
        return None, "جهت سیگنال مشخص نیست."

    entry_i = meta.get("entry_index")
    if not isinstance(entry_i, int):
        entry_i = len(bars) - 1
    entry_i = max(0, min(entry_i, len(bars) - 1))
    entry_px = float(bars[entry_i].close)
    if entry_px <= 0:
        return None, "قیمت ورود نامعتبر است."

    start = entry_i + 1
    if start >= len(bars):
        return None, "کندل کافی بعد از ورود نبود."

    if direction == "up":
        tp_px = entry_px * (1 + TAKE_PROFIT_PCT)
    else:
        tp_px = entry_px * (1 - TAKE_PROFIT_PCT)

    exit_i: int | None = None
    exit_px: float | None = None
    reason = ""
    for i in range(start, len(bars)):
        b = bars[i]
        if direction == "up" and b.high >= tp_px:
            exit_i, exit_px, reason = i, tp_px, "بستن در سود ۰.۵٪"
            break
        if direction == "down" and b.low <= tp_px:
            exit_i, exit_px, reason = i, tp_px, "بستن در سود ۰.۵٪"
            break

    if exit_i is None:
        exit_i = len(bars) - 1
        exit_px = float(bars[exit_i].close)
        reason = "پایان داده"

    if direction == "up":
        pct = (exit_px - entry_px) / entry_px
    else:
        pct = (entry_px - exit_px) / entry_px

    meta["entry_index"] = entry_i
    meta["entry_px"] = entry_px
    meta["exit_index"] = exit_i
    meta["path_pct"] = pct
    meta["exit_reason"] = reason
    meta["tp_px"] = tp_px
    ok = pct > 0
    note = (
        f"مسیر spot از ورود تا {reason}: {pct * 100:+.2f}٪ "
        f"({entry_px:,.0f} → {exit_px:,.0f})"
    )
    return ok, note


def detect_meaningful_behavior(
    timeframe: str,
    *,
    spot: float | None = None,
    end_ms: int | None = None,
) -> PatternHit | None:
    cfg = WINDOW_CFG.get(timeframe)
    if cfg is None:
        return None
    burst_min, window_hours = cfg
    end_ms = end_ms if end_ms is not None else int(time.time() * 1000)
    burst_ms = burst_min * 60 * 1000
    window_ms = int(window_hours * 3600 * 1000)
    baseline_start = end_ms - window_ms
    burst_start = end_ms - burst_ms

    with DeribitClient() as client:
        trades = client.fetch_option_trades(
            start_ms=baseline_start,
            end_ms=end_ms,
        )
        if spot is None:
            try:
                spot = client.get_index_price()
            except Exception:
                spot = float(trades[0]["index_price"]) if trades else None
    if spot is None or spot <= 0:
        return None

    b_bc, b_bp, b_sc, b_sp, b_calls, b_puts = _aggregate(
        trades, start_ms=burst_start, end_ms=end_ms
    )
    base_bc, base_bp, _, _, _, _ = _aggregate(
        trades, start_ms=baseline_start, end_ms=burst_start - 1
    )
    baseline_minutes = max((burst_start - baseline_start) / 60000.0, 1.0)

    candidates: list[tuple[float, PatternHit]] = []

    if _surge_ok(b_bc, base_bc, baseline_minutes, float(burst_min)) and b_bc >= b_bp * 1.15:
        top = top_strikes(b_calls, 2)
        strikes_s = "، ".join(f"{int(k):,}" for k, _ in top) if top else "—"
        alert_key = _alert_key(timeframe, "call_surge", end_ms, b_bc)
        hit = PatternHit(
            category="meaningful_behavior",
            timeframe=timeframe,
            pattern_id="call_surge",
            title_fa="ورود معنادار خرید کال",
            status_fa="فعال",
            summary_fa=(
                f"در {burst_min} دقیقهٔ اخیر حدود {b_bc:,.1f} BTC خرید کال "
                f"(نسبت به میانگین ~{base_bc / baseline_minutes * burst_min:.1f} BTC در همان مدت قبل). "
                f"strikeهای پرحجم: {strikes_s}. شاخص ~{spot:,.0f}."
            ),
            forecast_fa=(
                "تمایل صعودی کوتاه‌مدت در فلو؛ ورود spot با هدف ۰.۵٪ سود "
                f"(حدود {spot * (1 + TAKE_PROFIT_PCT):,.0f})."
            ),
            meta={
                "direction": "up",
                "stage": "confirmed",
                "burst_minutes": burst_min,
                "burst_buy_call": b_bc,
                "burst_buy_put": b_bp,
                "baseline_buy_call": base_bc,
                "dominant_strikes": top,
                "spot_at_signal": spot,
                "signal_end_ms": end_ms,
                "alert_key": alert_key,
                "early_side": "low",
            },
        )
        candidates.append((b_bc, hit))

    if _surge_ok(b_bp, base_bp, baseline_minutes, float(burst_min)) and b_bp >= b_bc * 1.15:
        top = top_strikes(b_puts, 2)
        strikes_s = "، ".join(f"{int(k):,}" for k, _ in top) if top else "—"
        alert_key = _alert_key(timeframe, "put_surge", end_ms, b_bp)
        hit = PatternHit(
            category="meaningful_behavior",
            timeframe=timeframe,
            pattern_id="put_surge",
            title_fa="ورود معنادار خرید پوت",
            status_fa="فعال",
            summary_fa=(
                f"در {burst_min} دقیقهٔ اخیر حدود {b_bp:,.1f} BTC خرید پوت "
                f"(نسبت به میانگین ~{base_bp / baseline_minutes * burst_min:.1f} BTC در همان مدت قبل). "
                f"strikeهای پرحجم: {strikes_s}. شاخص ~{spot:,.0f}."
            ),
            forecast_fa=(
                "تمایل محافظتی/نزولی کوتاه‌مدت؛ ورود spot با هدف ۰.۵٪ سود "
                f"(حدود {spot * (1 - TAKE_PROFIT_PCT):,.0f})."
            ),
            meta={
                "direction": "down",
                "stage": "confirmed",
                "burst_minutes": burst_min,
                "burst_buy_call": b_bc,
                "burst_buy_put": b_bp,
                "baseline_buy_put": base_bp,
                "dominant_strikes": top,
                "spot_at_signal": spot,
                "signal_end_ms": end_ms,
                "alert_key": alert_key,
                "early_side": "high",
            },
        )
        candidates.append((b_bp, hit))

    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]
