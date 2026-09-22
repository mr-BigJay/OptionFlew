from __future__ import annotations

from typing import Any

from optionflow.patterns.indicators import atr
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit


def _atr_now(bars: list[OhlcBar]) -> float | None:
    vals = atr(bars)
    for v in reversed(vals):
        if v is not None and v > 0:
            return float(v)
    return None


def _levels(
    direction: str,
    entry: float,
    stop: float,
    tp_rr: float,
) -> tuple[float, float, float]:
    risk = abs(entry - stop)
    if risk <= 0:
        risk = entry * 0.001
    if direction == "up":
        tp = entry + tp_rr * risk
    else:
        tp = entry - tp_rr * risk
    return entry, stop, tp


def _hit(
    *,
    scenario_id: str,
    title_fa: str,
    timeframe: str,
    direction: str,
    entry: float,
    stop: float,
    tp: float,
    confirm_i: int,
    setup_key: str,
    summary: str,
    forecast: str,
    params: dict[str, Any],
) -> PatternHit:
    rr = params.get("tp_rr", 1.5)
    return PatternHit(
        category="scalp",
        timeframe=timeframe,
        pattern_id=f"scalp_{scenario_id}",
        title_fa=title_fa,
        status_fa="فعال",
        summary_fa=summary,
        forecast_fa=forecast,
        meta={
            "scenario_id": scenario_id,
            "direction": direction,
            "entry_px": entry,
            "stop_px": stop,
            "tp_px": tp,
            "entry_index": confirm_i,
            "confirm_index": confirm_i,
            "setup_key": setup_key,
            "stage": "active",
            "tp_rr": rr,
            "max_hold_bars": int(params.get("max_hold_bars", 24)),
            "stop_atr_mult": params.get("stop_atr_mult"),
        },
    )


def _detect_range_break(
    bars: list[OhlcBar],
    timeframe: str,
    scenario: dict[str, Any],
    params: dict[str, Any],
) -> PatternHit | None:
    n = len(bars)
    range_bars = int(params.get("range_bars", 12))
    if n < range_bars + 25:
        return None
    atr_now = _atr_now(bars)
    if atr_now is None:
        return None
    window = bars[-(range_bars + 1) : -1]
    if len(window) < range_bars:
        return None
    rh = max(b.high for b in window)
    rl = min(b.low for b in window)
    width = rh - rl
    if width <= 0 or width > float(params.get("range_atr_mult", 1.25)) * atr_now:
        return None
    last = bars[-1]
    buf = atr_now * float(params.get("stop_atr_mult", 0.4)) * 0.25
    tp_rr = float(params.get("tp_rr", 1.5))

    if last.close > rh + buf * 0.15:
        stop = rl - buf
        entry, stop, tp = _levels("up", last.close, stop, tp_rr)
        sk = f"up:{int(round(rh))}:{int(round(rl))}"
        return _hit(
            scenario_id=scenario["scenario_id"],
            title_fa=scenario["title_fa"],
            timeframe=timeframe,
            direction="up",
            entry=entry,
            stop=stop,
            tp=tp,
            confirm_i=n - 1,
            setup_key=sk,
            summary=(
                f"شکست بالای رنج {rh:,.0f} / {rl:,.0f} · ورود {entry:,.0f} · "
                f"استاپ {stop:,.0f} · TP {tp:,.0f} (R×{tp_rr:g})"
            ),
            forecast="اسکلپ صعودی تا TP یا استاپ.",
            params=params,
        )
    if last.close < rl - buf * 0.15:
        stop = rh + buf
        entry, stop, tp = _levels("down", last.close, stop, tp_rr)
        sk = f"down:{int(round(rh))}:{int(round(rl))}"
        return _hit(
            scenario_id=scenario["scenario_id"],
            title_fa=scenario["title_fa"],
            timeframe=timeframe,
            direction="down",
            entry=entry,
            stop=stop,
            tp=tp,
            confirm_i=n - 1,
            setup_key=sk,
            summary=(
                f"شکست زیر رنج {rh:,.0f} / {rl:,.0f} · ورود {entry:,.0f} · "
                f"استاپ {stop:,.0f} · TP {tp:,.0f} (R×{tp_rr:g})"
            ),
            forecast="اسکلپ نزولی تا TP یا استاپ.",
            params=params,
        )
    return None


def _detect_sweep_reclaim(
    bars: list[OhlcBar],
    timeframe: str,
    scenario: dict[str, Any],
    params: dict[str, Any],
) -> PatternHit | None:
    n = len(bars)
    lb = int(params.get("swing_lookback", 18))
    if n < lb + 10:
        return None
    atr_now = _atr_now(bars)
    if atr_now is None:
        return None
    sweep_min = float(params.get("sweep_atr_mult", 0.35)) * atr_now
    buf = atr_now * float(params.get("stop_atr_mult", 0.35))
    tp_rr = float(params.get("tp_rr", 1.6))
    prior = bars[-lb - 1 : -1]
    ref_low = min(b.low for b in prior)
    ref_high = max(b.high for b in prior)
    last = bars[-1]

    if last.low < ref_low - sweep_min and last.close > ref_low:
        stop = last.low - buf
        entry, stop, tp = _levels("up", last.close, stop, tp_rr)
        sk = f"sweep_up:{int(round(ref_low))}:{int(round(last.low))}"
        return _hit(
            scenario_id=scenario["scenario_id"],
            title_fa=scenario["title_fa"],
            timeframe=timeframe,
            direction="up",
            entry=entry,
            stop=stop,
            tp=tp,
            confirm_i=n - 1,
            setup_key=sk,
            summary=(
                f"سویپ زیر {ref_low:,.0f} و بسته {last.close:,.0f} · "
                f"استاپ {stop:,.0f} · TP {tp:,.0f}"
            ),
            forecast="بازگشت صعودی کوتاه‌مدت.",
            params=params,
        )
    if last.high > ref_high + sweep_min and last.close < ref_high:
        stop = last.high + buf
        entry, stop, tp = _levels("down", last.close, stop, tp_rr)
        sk = f"sweep_dn:{int(round(ref_high))}:{int(round(last.high))}"
        return _hit(
            scenario_id=scenario["scenario_id"],
            title_fa=scenario["title_fa"],
            timeframe=timeframe,
            direction="down",
            entry=entry,
            stop=stop,
            tp=tp,
            confirm_i=n - 1,
            setup_key=sk,
            summary=(
                f"سویپ بالای {ref_high:,.0f} و بسته {last.close:,.0f} · "
                f"استاپ {stop:,.0f} · TP {tp:,.0f}"
            ),
            forecast="بازگشت نزولی کوتاه‌مدت.",
            params=params,
        )
    return None


def _detect_impulse_pullback(
    bars: list[OhlcBar],
    timeframe: str,
    scenario: dict[str, Any],
    params: dict[str, Any],
) -> PatternHit | None:
    n = len(bars)
    if n < 40:
        return None
    atr_now = _atr_now(bars)
    if atr_now is None:
        return None
    impulse_mult = float(params.get("impulse_atr_mult", 1.35))
    max_pb = int(params.get("pullback_max_bars", 4))
    buf = atr_now * float(params.get("stop_atr_mult", 0.45))
    tp_rr = float(params.get("tp_rr", 1.4))

    for imp_off in range(2, min(8, n - max_pb - 2)):
        imp = bars[-imp_off]
        body = abs(imp.close - imp.open)
        if body < impulse_mult * atr_now:
            continue
        bull = imp.close > imp.open
        mid = (imp.open + imp.close) / 2
        for pb_len in range(1, max_pb + 1):
            pb = bars[-imp_off + pb_len] if imp_off > pb_len else None
            if pb is None:
                break
            last = bars[-1]
            if bull:
                if pb.low > mid or last.close <= last.open:
                    continue
                if last.close <= mid:
                    continue
                stop = min(b.low for b in bars[-imp_off :]) - buf
                entry, stop, tp = _levels("up", last.close, stop, tp_rr)
                sk = f"imp_up:{int(round(imp.close))}:{pb_len}"
                return _hit(
                    scenario_id=scenario["scenario_id"],
                    title_fa=scenario["title_fa"],
                    timeframe=timeframe,
                    direction="up",
                    entry=entry,
                    stop=stop,
                    tp=tp,
                    confirm_i=n - 1,
                    setup_key=sk,
                    summary=(
                        f"Impulse صعودی و پول‌بک · ورود {entry:,.0f} · "
                        f"استاپ {stop:,.0f} · TP {tp:,.0f}"
                    ),
                    forecast="ادامهٔ impulse کوتاه‌مدت.",
                    params=params,
                )
            else:
                if pb.high < mid or last.close >= last.open:
                    continue
                if last.close >= mid:
                    continue
                stop = max(b.high for b in bars[-imp_off :]) + buf
                entry, stop, tp = _levels("down", last.close, stop, tp_rr)
                sk = f"imp_dn:{int(round(imp.close))}:{pb_len}"
                return _hit(
                    scenario_id=scenario["scenario_id"],
                    title_fa=scenario["title_fa"],
                    timeframe=timeframe,
                    direction="down",
                    entry=entry,
                    stop=stop,
                    tp=tp,
                    confirm_i=n - 1,
                    setup_key=sk,
                    summary=(
                        f"Impulse نزولی و پول‌بک · ورود {entry:,.0f} · "
                        f"استاپ {stop:,.0f} · TP {tp:,.0f}"
                    ),
                    forecast="ادامهٔ impulse کوتاه‌مدت.",
                    params=params,
                )
    return None


def _detect_four_h_rr(
    bars: list[OhlcBar],
    timeframe: str,
    scenario: dict[str, Any],
    params: dict[str, Any],
) -> PatternHit | None:
    if timeframe != "5m":
        return None
    from optionflow.patterns.ohlc import load_btcusdt
    from optionflow.scalp.four_h_rr import detect_4hrr_live

    bars_4h = load_btcusdt("4h", limit=500)
    row = {
        "scenario_id": scenario["scenario_id"],
        "title_fa": scenario.get("title_fa", "4HRR"),
    }
    return detect_4hrr_live(
        bars, bars_4h, scenario=row, params=params, timeframe=timeframe
    )


_DETECTORS = {
    "range_break": _detect_range_break,
    "sweep_reclaim": _detect_sweep_reclaim,
    "impulse_pullback": _detect_impulse_pullback,
    "four_h_rr": _detect_four_h_rr,
}


def detect_scalp_scenario(
    bars: list[OhlcBar],
    timeframe: str,
    scenario: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> PatternHit | None:
    merged = dict(scenario.get("params") or {})
    if params:
        merged.update(params)
    dtype = scenario.get("detector_type") or scenario.get("scenario_id")
    fn = _DETECTORS.get(str(dtype))
    if fn is None:
        return None
    row = {
        "scenario_id": scenario["scenario_id"],
        "title_fa": scenario.get("title_fa", scenario["scenario_id"]),
        "detector_type": dtype,
    }
    return fn(bars, timeframe, row, merged)
