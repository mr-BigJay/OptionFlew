from __future__ import annotations

from typing import Any

from optionflow.patterns.indicators import atr, ema
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit


def _crossover(ma1: list, ma2: list, i: int) -> bool:
    if i < 1:
        return False
    a0, a1 = ma1[i - 1], ma1[i]
    b0, b1 = ma2[i - 1], ma2[i]
    if a0 is None or a1 is None or b0 is None or b1 is None:
        return False
    return a0 <= b0 and a1 > b1


def _crossunder(ma1: list, ma2: list, i: int) -> bool:
    if i < 1:
        return False
    a0, a1 = ma1[i - 1], ma1[i]
    b0, b1 = ma2[i - 1], ma2[i]
    if a0 is None or a1 is None or b0 is None or b1 is None:
        return False
    return a0 >= b0 and a1 < b1


def _swing_extremes(bars: list[OhlcBar], i: int, lookback: int) -> tuple[float, float]:
    start = max(0, i - lookback + 1)
    chunk = bars[start : i + 1]
    return min(b.low for b in chunk), max(b.high for b in chunk)


def detect_bjorgum(
    bars: list[OhlcBar],
    timeframe: str,
    scenario: dict[str, Any],
    params: dict[str, Any],
) -> PatternHit | None:
    """BjorGum — MA cross + swing/ATR stop & R:R target (Pine Bj Bot defaults)."""
    if timeframe != "1h":
        return None

    ma_len1 = int(params.get("ma_length_1", 21))
    ma_len2 = int(params.get("ma_length_2", 50))
    atr_len = int(params.get("atr_len", 14))
    swing_lb = int(params.get("swing_lookback", 5))
    risk_m = float(params.get("risk_m", 1.0))
    tp_rr = float(params.get("tp_rr", 1.0))
    long_ok = bool(params.get("long_trades", True))
    short_ok = bool(params.get("short_trades", True))

    min_bars = max(ma_len1, ma_len2, atr_len) + swing_lb + 5
    n = len(bars)
    if n < min_bars:
        return None

    closes = [b.close for b in bars]
    ma1 = ema(closes, ma_len1)
    ma2 = ema(closes, ma_len2)
    atr_vals = atr(bars, period=atr_len)
    i = n - 1
    atr_now = atr_vals[i]
    if atr_now is None or atr_now <= 0:
        return None

    lowest, highest = _swing_extremes(bars, i, swing_lb)
    bar = bars[i]
    sid = scenario["scenario_id"]
    title = scenario.get("title_fa", "BjorGum")

    if long_ok and _crossover(ma1, ma2, i):
        stop = lowest - atr_now * risk_m
        risk = bar.close - stop
        if risk <= 0:
            risk = bar.close * 1e-6
        tp = bar.close + tp_rr * risk
        sk = f"long:{i}:{int(round(bar.close))}"
        return PatternHit(
            category="scalp",
            timeframe=timeframe,
            pattern_id=f"scalp_{sid}",
            title_fa=f"{title} · Long",
            status_fa="فعال",
            summary_fa=(
                f"کراس MA{ma_len1} بالای MA{ma_len2} · ورود {bar.close:,.0f} · "
                f"استاپ {stop:,.0f} · TP {tp:,.0f} (R×{tp_rr:g})"
            ),
            forecast_fa="هدف مکانیکی TP یا استاپ swing+ATR.",
            meta={
                "scenario_id": sid,
                "direction": "up",
                "entry_px": bar.close,
                "stop_px": stop,
                "tp_px": tp,
                "entry_index": i,
                "confirm_index": i,
                "setup_key": sk,
                "stage": "active",
                "tp_rr": tp_rr,
                "ma_length_1": ma_len1,
                "ma_length_2": ma_len2,
                "swing_lookback": swing_lb,
                "risk_m": risk_m,
            },
        )

    if short_ok and _crossunder(ma1, ma2, i):
        stop = highest + atr_now * risk_m
        risk = stop - bar.close
        if risk <= 0:
            risk = bar.close * 1e-6
        tp = bar.close - tp_rr * risk
        sk = f"short:{i}:{int(round(bar.close))}"
        return PatternHit(
            category="scalp",
            timeframe=timeframe,
            pattern_id=f"scalp_{sid}",
            title_fa=f"{title} · Short",
            status_fa="فعال",
            summary_fa=(
                f"کراس MA{ma_len1} زیر MA{ma_len2} · ورود {bar.close:,.0f} · "
                f"استاپ {stop:,.0f} · TP {tp:,.0f} (R×{tp_rr:g})"
            ),
            forecast_fa="هدف مکانیکی TP یا استاپ swing+ATR.",
            meta={
                "scenario_id": sid,
                "direction": "down",
                "entry_px": bar.close,
                "stop_px": stop,
                "tp_px": tp,
                "entry_index": i,
                "confirm_index": i,
                "setup_key": sk,
                "stage": "active",
                "tp_rr": tp_rr,
                "ma_length_1": ma_len1,
                "ma_length_2": ma_len2,
                "swing_lookback": swing_lb,
                "risk_m": risk_m,
            },
        )

    return None
