from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from optionflow.patterns.indicators import atr, ema
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

_TF_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


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


def _bar_ts(bar: OhlcBar) -> datetime:
    ts = bar.ts
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _bar_is_forming(bar: OhlcBar, timeframe: str) -> bool:
    sec = _TF_SECONDS.get(timeframe, 3600)
    end = _bar_ts(bar) + timedelta(seconds=sec)
    return end > datetime.now(timezone.utc)


def _last_closed_index(bars: list[OhlcBar], timeframe: str) -> int:
    i = len(bars) - 1
    while i >= 0 and _bar_is_forming(bars[i], timeframe):
        i -= 1
    return i


def _swing_extremes(bars: list[OhlcBar], i: int, lookback: int) -> tuple[float, float]:
    start = max(0, i - lookback + 1)
    chunk = bars[start : i + 1]
    return min(b.low for b in chunk), max(b.high for b in chunk)


def _wma(values: list[float], length: int) -> list[float | None]:
    n = len(values)
    out: list[float | None] = [None] * n
    if length < 1 or n < length:
        return out
    denom = length * (length + 1) / 2
    for i in range(length - 1, n):
        wsum = 0.0
        for j in range(length):
            wsum += values[i - length + 1 + j] * (j + 1)
        out[i] = wsum / denom
    return out


def _hma(values: list[float], length: int) -> list[float | None]:
    half = max(1, length // 2)
    sqrt_len = max(1, int(length**0.5))
    wma_half = _wma(values, half)
    wma_full = _wma(values, length)
    raw = [
        2 * a - b if a is not None and b is not None else None
        for a, b in zip(wma_half, wma_full)
    ]
    filled = [x if x is not None else values[i] for i, x in enumerate(raw)]
    return _wma(filled, sqrt_len)


def _vwma(bars: list[OhlcBar], length: int) -> list[float | None]:
    n = len(bars)
    out: list[float | None] = [None] * n
    if length < 1 or n < length:
        return out
    for i in range(length - 1, n):
        pv = 0.0
        vol = 0.0
        for j in range(i - length + 1, i + 1):
            v = bars[j].volume or 1.0
            pv += bars[j].close * v
            vol += v
        out[i] = pv / vol if vol > 0 else bars[i].close
    return out


def _vwap(bars: list[OhlcBar]) -> list[float]:
    cum_pv = 0.0
    cum_v = 0.0
    out: list[float] = []
    for b in bars:
        tp = (b.high + b.low + b.close) / 3.0
        v = b.volume or 1.0
        cum_pv += tp * v
        cum_v += v
        out.append(cum_pv / cum_v if cum_v > 0 else b.close)
    return out


def _dema(values: list[float], length: int) -> list[float | None]:
    e1 = ema(values, length)
    e1f = [x if x is not None else values[i] for i, x in enumerate(e1)]
    e2 = ema(e1f, length)
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        if e1[i] is not None and e2[i] is not None:
            out[i] = 2 * e1[i] - e2[i]
    return out


def _t3(values: list[float], length: int) -> list[float | None]:
    axe1 = ema(values, length)
    a1 = [x if x is not None else values[i] for i, x in enumerate(axe1)]
    axe2 = ema(a1, length)
    a2 = [x if x is not None else a1[i] for i, x in enumerate(axe2)]
    axe3 = ema(a2, length)
    a3 = [x if x is not None else a2[i] for i, x in enumerate(axe3)]
    axe4 = ema(a3, length)
    a4 = [x if x is not None else a3[i] for i, x in enumerate(axe4)]
    axe5 = ema(a4, length)
    a5 = [x if x is not None else a4[i] for i, x in enumerate(axe5)]
    axe6 = ema(a5, length)
    ab = 0.7
    ac1 = -ab * ab * ab
    ac2 = 3 * ab * ab + 3 * ab * ab * ab
    ac3 = -6 * ab * ab - 3 * ab - 3 * ab * ab * ab
    ac4 = 1 + 3 * ab + ab * ab * ab + 3 * ab * ab
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        if axe6[i] is None:
            continue
        out[i] = (
            ac1 * axe6[i]
            + ac2 * axe5[i]
            + ac3 * axe4[i]
            + ac4 * axe3[i]
        )
    return out


def _ha_open_series(bars: list[OhlcBar]) -> list[float]:
    ha_open: list[float] = []
    ha_close_prev: float | None = None
    ha_open_prev: float | None = None
    for b in bars:
        ha_close = (b.open + b.high + b.low + b.close) / 4.0
        if ha_open_prev is None:
            ho = (b.open + b.close) / 2.0
        else:
            ho = (ha_open_prev + (ha_close_prev or ha_close)) / 2.0
        ha_open.append(ho)
        ha_open_prev = ho
        ha_close_prev = ha_close
    return ha_open


def get_ma_series(
    bars: list[OhlcBar],
    ma_type: str,
    length: int,
) -> list[float | None]:
    """همان getMA در Pine Bj Bot (پیش‌فرض EMA روی close)."""
    closes = [b.close for b in bars]
    kind = (ma_type or "EMA").upper()
    if kind == "HEMA":
        return ema(_ha_open_series(bars), length)
    if kind == "SMA":
        out: list[float | None] = [None] * len(closes)
        if length < 1 or len(closes) < length:
            return out
        for i in range(length - 1, len(closes)):
            out[i] = sum(closes[i - length + 1 : i + 1]) / length
        return out
    if kind == "HMA":
        return _hma(closes, length)
    if kind == "WMA":
        return _wma(closes, length)
    if kind == "VWMA":
        return _vwma(bars, length)
    if kind == "VWAP":
        vw = _vwap(bars)
        return vw  # type: ignore[return-value]
    if kind == "DEMA":
        return _dema(closes, length)
    if kind == "T3":
        return _t3(closes, length)
    return ema(closes, length)


def bjorgum_stops_targets(
    *,
    direction: str,
    close: float,
    lowest_low: float,
    highest_high: float,
    atr_now: float,
    risk_m: float,
    tp_rr: float,
    use_limit: bool,
) -> tuple[float, float, float | None]:
    """longStop/shortStop و limit مطابق Pine (trailStop=false)."""
    if direction == "up":
        stop = lowest_low - atr_now * risk_m
        risk = close - stop
        if risk <= 0:
            risk = close * 1e-9
        tp = close + tp_rr * risk if use_limit else None
        return close, stop, tp
    stop = highest_high + atr_now * risk_m
    risk = stop - close
    if risk <= 0:
        risk = close * 1e-9
    tp = close - tp_rr * risk if use_limit else None
    return close, stop, tp


def _build_hit(
    *,
    scenario: dict[str, Any],
    params: dict[str, Any],
    timeframe: str,
    direction: str,
    entry: float,
    stop: float,
    tp: float | None,
    signal_i: int,
    ma_len1: int,
    ma_len2: int,
    ma_type1: str,
    ma_type2: str,
) -> PatternHit:
    sid = scenario["scenario_id"]
    title = scenario.get("title_fa", "BjorGum")
    side = "Long" if direction == "up" else "Short"
    tp_rr = float(params.get("tp_rr", 1.0))
    sk = f"{direction}:{int(round(stop))}:{int(round(entry))}"
    tp_txt = f"{tp:,.0f}" if isinstance(tp, (int, float)) else "—"
    return PatternHit(
        category="scalp",
        timeframe=timeframe,
        pattern_id=f"scalp_{sid}",
        title_fa=f"{title} · {side}",
        status_fa="فعال",
        summary_fa=(
            f"کراس {ma_type1}{ma_len1} / {ma_type2}{ma_len2} · ورود {entry:,.0f} · "
            f"استاپ {stop:,.0f} · TP {tp_txt} (R×{tp_rr:g})"
        ),
        forecast_fa="خروج مکانیکی روی استاپ swing+ATR یا limit (Bj Bot).",
        meta={
            "scenario_id": sid,
            "direction": direction,
            "entry_px": entry,
            "stop_px": stop,
            "tp_px": tp if tp is not None else entry,
            "entry_index": signal_i,
            "confirm_index": signal_i,
            "setup_key": sk,
            "stage": "active",
            "tp_rr": tp_rr,
            "ma_length_1": ma_len1,
            "ma_length_2": ma_len2,
            "ma_type_1": ma_type1,
            "ma_type_2": ma_type2,
            "swing_lookback": int(params.get("swing_lookback", 5)),
            "risk_m": float(params.get("risk_m", 1.0)),
            "use_limit": bool(params.get("use_limit", True)),
            "max_hold_bars": int(params.get("max_hold_bars", 120)),
        },
    )


def detect_bjorgum(
    bars: list[OhlcBar],
    timeframe: str,
    scenario: dict[str, Any],
    params: dict[str, Any],
) -> PatternHit | None:
    """BjorGum / Bj Bot — فقط 1h · MA cross · swing+ATR stop · R:R limit."""
    if timeframe != "1h":
        return None

    ma_len1 = int(params.get("ma_length_1", 21))
    ma_len2 = int(params.get("ma_length_2", 50))
    ma_type1 = str(params.get("ma_type_1", "EMA"))
    ma_type2 = str(params.get("ma_type_2", "EMA"))
    atr_len = int(params.get("atr_len", 14))
    swing_lb = int(params.get("swing_lookback", 5))
    risk_m = float(params.get("risk_m", 1.0))
    tp_rr = float(params.get("tp_rr", 1.0))
    long_ok = bool(params.get("long_trades", True))
    short_ok = bool(params.get("short_trades", True))
    use_limit = bool(params.get("use_limit", True))

    min_bars = max(ma_len1, ma_len2, atr_len) + swing_lb + 5
    if len(bars) < min_bars:
        return None

    i = _last_closed_index(bars, timeframe)
    if i < min_bars - 1:
        return None

    ma1 = get_ma_series(bars, ma_type1, ma_len1)
    ma2 = get_ma_series(bars, ma_type2, ma_len2)
    atr_vals = atr(bars, period=atr_len)
    atr_now = atr_vals[i]
    if atr_now is None or atr_now <= 0:
        return None

    lowest, highest = _swing_extremes(bars, i, swing_lb)
    bar = bars[i]

    # Pine: short block قبل از long؛ FLIP=false → فقط سیگنال روی کراس (بدون پوزیشن)
    if short_ok and _crossunder(ma1, ma2, i):
        entry, stop, tp = bjorgum_stops_targets(
            direction="down",
            close=bar.close,
            lowest_low=lowest,
            highest_high=highest,
            atr_now=atr_now,
            risk_m=risk_m,
            tp_rr=tp_rr,
            use_limit=use_limit,
        )
        if tp is None:
            return None
        return _build_hit(
            scenario=scenario,
            params=params,
            timeframe=timeframe,
            direction="down",
            entry=entry,
            stop=stop,
            tp=tp,
            signal_i=i,
            ma_len1=ma_len1,
            ma_len2=ma_len2,
            ma_type1=ma_type1,
            ma_type2=ma_type2,
        )

    if long_ok and _crossover(ma1, ma2, i):
        entry, stop, tp = bjorgum_stops_targets(
            direction="up",
            close=bar.close,
            lowest_low=lowest,
            highest_high=highest,
            atr_now=atr_now,
            risk_m=risk_m,
            tp_rr=tp_rr,
            use_limit=use_limit,
        )
        if tp is None:
            return None
        return _build_hit(
            scenario=scenario,
            params=params,
            timeframe=timeframe,
            direction="up",
            entry=entry,
            stop=stop,
            tp=tp,
            signal_i=i,
            ma_len1=ma_len1,
            ma_len2=ma_len2,
            ma_type1=ma_type1,
            ma_type2=ma_type2,
        )

    return None
