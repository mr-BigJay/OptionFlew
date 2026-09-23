from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from optionflow.patterns.indicators import atr
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit
from optionflow.scalp.spline_quantile import fit_quantile_bands

_TF_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


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


def _window_closes(bars: list[OhlcBar], end_i: int, n: int) -> list[float] | None:
    start = end_i - n + 1
    if start < 0:
        return None
    return [float(b.close) for b in bars[start : end_i + 1]]


def _bands(
    bars: list[OhlcBar],
    end_i: int,
    params: dict[str, Any],
) -> dict[str, float] | None:
    n = int(params.get("lookback", 100))
    closes = _window_closes(bars, end_i, n)
    if closes is None:
        return None
    return fit_quantile_bands(
        closes,
        knots=int(params.get("knots", 3)),
        iters=int(params.get("irls_iters", 50)),
        upper_q=float(params.get("upper_q", 0.95)),
        mid_q=float(params.get("mid_q", 0.5)),
        lower_q=float(params.get("lower_q", 0.05)),
        extrapolation=int(params.get("forecast_bars", 20)),
    )


def _tp_for_long(
    entry: float,
    stop: float,
    bands: dict[str, float],
    params: dict[str, Any],
) -> float:
    target = str(params.get("tp_target", "mid")).strip().lower()
    if target == "upper":
        return float(bands["upper"])
    if target == "opposite":
        return float(bands["upper"])
    if target == "rr":
        rr = float(params.get("tp_rr", 1.5))
        risk = max(entry - stop, entry * 1e-4)
        return entry + rr * risk
    return float(bands["mid"])


def _tp_for_short(
    entry: float,
    stop: float,
    bands: dict[str, float],
    params: dict[str, Any],
) -> float:
    target = str(params.get("tp_target", "mid")).strip().lower()
    if target == "lower":
        return float(bands["lower"])
    if target == "opposite":
        return float(bands["lower"])
    if target == "rr":
        rr = float(params.get("tp_rr", 1.5))
        risk = max(stop - entry, entry * 1e-4)
        return entry - rr * risk
    return float(bands["mid"])


def _build_hit(
    *,
    scenario: dict[str, Any],
    params: dict[str, Any],
    timeframe: str,
    direction: str,
    entry: float,
    stop: float,
    tp: float,
    signal_i: int,
    bands: dict[str, float],
    summary: str,
) -> PatternHit:
    sid = scenario["scenario_id"]
    return PatternHit(
        category="scalp",
        timeframe=timeframe,
        pattern_id=f"scalp_{sid}",
        title_fa=scenario.get("title_fa", "Spline"),
        status_fa="فعال",
        summary_fa=summary,
        forecast_fa=(
            "کانال Spline Quantile — ورود از باند افراطی با میل میانه."
        ),
        meta={
            "scenario_id": sid,
            "direction": direction,
            "entry_px": entry,
            "stop_px": stop,
            "tp_px": tp,
            "entry_index": signal_i,
            "confirm_index": signal_i,
            "setup_key": (
                f"{direction}:u{int(round(bands['upper']))}:"
                f"m{int(round(bands['mid']))}:l{int(round(bands['lower']))}"
            ),
            "stage": "active",
            "max_hold_bars": int(params.get("max_hold_bars", 48)),
            "upper_band": bands.get("upper"),
            "mid_band": bands.get("mid"),
            "lower_band": bands.get("lower"),
            "mid_forecast": bands.get("mid_forecast"),
            "lookback": int(params.get("lookback", 100)),
        },
    )


def detect_spline(
    bars: list[OhlcBar],
    timeframe: str,
    scenario: dict[str, Any],
    params: dict[str, Any],
) -> PatternHit | None:
    """LuxAlgo Spline Quantile Channel — mean reversion at bands with median slope filter."""
    allowed = scenario.get("timeframes") or params.get("timeframes") or ["1h"]
    if timeframe not in allowed:
        return None

    lookback = int(params.get("lookback", 100))
    atr_len = int(params.get("atr_len", 14))
    stop_mult = float(params.get("stop_atr_mult", 0.5))
    touch_buf = float(params.get("touch_buffer_pct", 0.05)) / 100.0
    long_ok = bool(params.get("long_trades", True))
    short_ok = bool(params.get("short_trades", True))

    min_bars = lookback + atr_len + 5
    if len(bars) < min_bars:
        return None

    i = _last_closed_index(bars, timeframe)
    if i < lookback:
        return None

    bands_now = _bands(bars, i, params)
    bands_prev = _bands(bars, i - 1, params)
    if bands_now is None or bands_prev is None:
        return None

    atr_vals = atr(bars, period=atr_len)
    atr_now = atr_vals[i]
    if atr_now is None or atr_now <= 0:
        return None

    bar = bars[i]
    close = float(bar.close)
    mid_slope = bands_now["mid"] - bands_prev["mid"]
    upper = bands_now["upper"]
    lower = bands_now["lower"]
    mid = bands_now["mid"]

    if short_ok and close >= upper * (1.0 - touch_buf) and mid_slope < 0:
        stop = upper + atr_now * stop_mult
        tp = _tp_for_short(close, stop, bands_now, params)
        if tp >= close:
            return None
        return _build_hit(
            scenario=scenario,
            params=params,
            timeframe=timeframe,
            direction="down",
            entry=close,
            stop=stop,
            tp=tp,
            signal_i=i,
            bands=bands_now,
            summary=(
                f"Spline · close نزدیک باند بالا {upper:,.0f} · میانه {mid:,.0f} "
                f"(شیب نزولی) · ورود {close:,.0f} · استاپ {stop:,.0f} · TP {tp:,.0f}"
            ),
        )

    if long_ok and close <= lower * (1.0 + touch_buf) and mid_slope > 0:
        stop = lower - atr_now * stop_mult
        tp = _tp_for_long(close, stop, bands_now, params)
        if tp <= close:
            return None
        return _build_hit(
            scenario=scenario,
            params=params,
            timeframe=timeframe,
            direction="up",
            entry=close,
            stop=stop,
            tp=tp,
            signal_i=i,
            bands=bands_now,
            summary=(
                f"Spline · close نزدیک باند پایین {lower:,.0f} · میانه {mid:,.0f} "
                f"(شیب صعودی) · ورود {close:,.0f} · استاپ {stop:,.0f} · TP {tp:,.0f}"
            ),
        )

    return None
