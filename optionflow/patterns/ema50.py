from __future__ import annotations

from optionflow.patterns.indicators import atr, ema
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

EMA_LEN = 50
LEFT_PAD = 24
SLOPE_BARS = {"5m": 10, "15m": 8, "1h": 6, "4h": 5, "1d": 4}
STEEP_SLOPE = {"5m": 0.0022, "15m": 0.003, "1h": 0.0045, "4h": 0.006, "1d": 0.008}
CHOP_BARS = {"5m": 30, "15m": 24, "1h": 20, "4h": 16, "1d": 12}
MAX_CROSSES = {"5m": 5, "15m": 4, "1h": 4, "4h": 3, "1d": 3}
STRETCH_MIN = 6  # بیشتر از ۵ کندل فاصله
TREND_EXIT_CLOSES = 3
NEAR = 0.15


def _slope_pct(ema_vals: list[float | None], i: int, lookback: int) -> float | None:
    if i - lookback < 0:
        return None
    a, b = ema_vals[i - lookback], ema_vals[i]
    if a is None or b is None or a <= 0:
        return None
    return (b - a) / a


def _is_chop(
    closes: list[float],
    ema_vals: list[float | None],
    end_i: int,
    timeframe: str,
) -> bool:
    span = CHOP_BARS.get(timeframe, 24)
    start = max(EMA_LEN, end_i - span)
    crosses = 0
    prev: bool | None = None
    for i in range(start, end_i + 1):
        e = ema_vals[i]
        if e is None:
            continue
        side = closes[i] >= e
        if prev is not None and side != prev:
            crosses += 1
        prev = side
    return crosses >= MAX_CROSSES.get(timeframe, 4)


def _wick_and_body(bar: OhlcBar) -> tuple[float, float, float]:
    body = abs(bar.close - bar.open)
    upper = bar.high - max(bar.open, bar.close)
    lower = min(bar.open, bar.close) - bar.low
    return body, upper, lower


def _rejection_wick(bar: OhlcBar, *, above: bool) -> bool:
    """ویک بیرونی (دور از EMA) از بادی بزرگ‌تر است."""
    body, upper, lower = _wick_and_body(bar)
    wick = upper if above else lower
    return wick > body and wick > 0


def _side_of(close: float, ema_v: float, atr_now: float) -> str | None:
    pad = atr_now * NEAR
    if close > ema_v + pad:
        return "above"
    if close < ema_v - pad:
        return "below"
    return None


def _away_run(
    bars: list[OhlcBar],
    ema_vals: list[float | None],
    *,
    end_i: int,
    atr_now: float,
    side: str,
) -> int:
    run = 0
    for i in range(end_i, EMA_LEN - 1, -1):
        e = ema_vals[i]
        if e is None:
            break
        if _side_of(bars[i].close, e, atr_now) != side:
            break
        run += 1
    return run


def _touches_ema(bar: OhlcBar, ema_v: float) -> bool:
    return bar.low <= ema_v <= bar.high


def ema50_slice(n: int, sig: int, pullback: int, early: int) -> tuple[int, int]:
    start = max(0, min(int(pullback), int(early), sig) - LEFT_PAD)
    before = max(1, sig - start)
    end = min(n, sig + 2 * before + 1)
    return start, end


def _visible(entry_i: int, n: int, pullback: int) -> bool:
    start = max(0, min(pullback, entry_i) - LEFT_PAD)
    before = max(1, entry_i - start)
    return n - 1 - entry_i <= 2 * before


def _setup(
    *,
    mode: str,
    direction: str,
    entry_i: int,
    pullback_i: int,
    entry_px: float,
    sl_px: float,
    exit_style: str,
    stage: str,
) -> dict:
    return {
        "mode": mode,
        "direction": direction,
        "entry_index": entry_i,
        "confirm_index": entry_i,
        "break_index": entry_i if stage == "confirmed" else None,
        "pullback_index": pullback_i,
        "early_index": entry_i,
        "early_side": "low" if direction == "up" else "high",
        "entry_px": entry_px,
        "sl_px": sl_px,
        "exit_style": exit_style,
        "stage": stage,
    }


def _flat_stretch(
    bars: list[OhlcBar],
    ema_vals: list[float | None],
    atr_now: float,
    n: int,
) -> dict | None:
    """شیب خیلی کم: بیش از ۵ کندل فاصله + ویک > بادی → ورود با کلوز، خروج با لمس EMA."""
    e = ema_vals[n - 1]
    if e is None:
        return None
    last = bars[n - 1]
    side = _side_of(last.close, e, atr_now)
    if side is None:
        return None
    run = _away_run(bars, ema_vals, end_i=n - 1, atr_now=atr_now, side=side)
    if run < STRETCH_MIN:
        return None
    direction = "down" if side == "above" else "up"
    sl = last.high + atr_now * 0.08 if direction == "down" else last.low - atr_now * 0.08
    wick_ok = _rejection_wick(last, above=(side == "above"))
    return _setup(
        mode="flat",
        direction=direction,
        entry_i=n - 1,
        pullback_i=max(EMA_LEN, n - run),
        entry_px=last.close,
        sl_px=sl,
        exit_style="ema_touch",
        stage="confirmed" if wick_ok else "early",
    )


def _steep_trend(
    bars: list[OhlcBar],
    ema_vals: list[float | None],
    atr_now: float,
    n: int,
    slope: float,
) -> dict | None:
    """شیب شدید: ورود همگام با ترند (نزدیک خط)، خروج با ۳ کلوز آن‌طرف EMA."""
    e = ema_vals[n - 1]
    if e is None:
        return None
    last = bars[n - 1]
    near = atr_now * 1.15
    if slope > 0:
        if last.close < e - atr_now * 0.35:
            return None
        touched = any(
            ema_vals[i] is not None and _touches_ema(bars[i], float(ema_vals[i]))
            for i in range(max(EMA_LEN, n - 6), n)
        )
        if not touched and abs(last.low - e) > near:
            return None
        with_trend = last.close > last.open
        return _setup(
            mode="trend",
            direction="up",
            entry_i=n - 1,
            pullback_i=n - 4,
            entry_px=last.close,
            sl_px=min(last.low, e) - atr_now * 0.08,
            exit_style="three_closes",
            stage="confirmed" if with_trend else "early",
        )
    if last.close > e + atr_now * 0.35:
        return None
    touched = any(
        ema_vals[i] is not None and _touches_ema(bars[i], float(ema_vals[i]))
        for i in range(max(EMA_LEN, n - 6), n)
    )
    if not touched and abs(last.high - e) > near:
        return None
    with_trend = last.close < last.open
    return _setup(
        mode="trend",
        direction="down",
        entry_i=n - 1,
        pullback_i=n - 4,
        entry_px=last.close,
        sl_px=max(last.high, e) + atr_now * 0.08,
        exit_style="three_closes",
        stage="confirmed" if with_trend else "early",
    )


def _to_hit(
    bars: list[OhlcBar],
    timeframe: str,
    setup: dict,
    *,
    ema_now: float | None,
    slope: float,
) -> PatternHit:
    direction = setup["direction"]
    mode = setup["mode"]
    stage = setup["stage"]
    role = "لانگ" if direction == "up" else "شورت"
    titles = {
        "flat": f"EMA50 فاصله {role}",
        "trend": f"EMA50 روند {role}",
    }
    exits = {
        "ema_touch": "خروج با اولین لمس EMA50",
        "three_closes": "خروج با سه کلوز آن‌طرف EMA50",
    }
    last = bars[-1]
    if stage == "early":
        status = "سیگنال اولیه"
        if mode == "flat":
            forecast = "منتظر کندل با ویک بزرگ‌تر از بادی برای ورود روی بسته شدن."
        else:
            forecast = f"شیب شدید است؛ منتظر کندل همگام با ترند برای ورود {role}."
    else:
        status = "تأییدشده"
        forecast = (
            f"ورود با بسته شدن {setup['entry_px']:,.0f}. "
            f"{exits[setup['exit_style']]}."
        )
    summary = f"{titles[mode]}. قیمت {last.close:,.0f}."
    return PatternHit(
        category="ema50",
        timeframe=timeframe,
        pattern_id=f"ema50_{mode}_{direction}_{stage}",
        title_fa=titles[mode],
        status_fa=status,
        summary_fa=summary,
        forecast_fa=forecast,
        meta={
            "kind": "ema50",
            "mode": mode,
            "stage": stage,
            "direction": direction,
            "side": "low" if direction == "up" else "high",
            "early_side": setup["early_side"],
            "pullback_index": setup["pullback_index"],
            "confirm_index": setup["confirm_index"],
            "entry_index": setup["entry_index"],
            "early_index": setup["early_index"],
            "break_index": setup["break_index"],
            "entry_px": setup["entry_px"],
            "sl_px": setup["sl_px"],
            "tp_px": ema_now,
            "exit_style": setup["exit_style"],
            "ema_now": ema_now,
            "slope_pct": slope,
            "last_close": last.close,
        },
    )


def detect_ema50(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    allow_early: bool = True,
) -> PatternHit | None:
    if len(bars) < EMA_LEN + 8:
        return None
    n = len(bars)
    closes = [b.close for b in bars]
    ema_vals = ema(closes, EMA_LEN)
    atr_vals = atr(bars)
    atr_now = next((v for v in reversed(atr_vals) if v is not None), None)
    if atr_now is None or atr_now <= 0:
        return None
    if _is_chop(closes, ema_vals, n - 1, timeframe):
        return None
    lb = SLOPE_BARS.get(timeframe, 8)
    slope = _slope_pct(ema_vals, n - 1, lb)
    if slope is None:
        return None

    steep = STEEP_SLOPE.get(timeframe, 0.003)
    if abs(slope) >= steep:
        setup = _steep_trend(bars, ema_vals, atr_now, n, slope)
    else:
        setup = _flat_stretch(bars, ema_vals, atr_now, n)

    if setup is None:
        return None
    if setup["stage"] == "early" and not allow_early:
        return None
    if not _visible(setup["entry_index"], n, int(setup["pullback_index"])):
        return None
    return _to_hit(bars, timeframe, setup, ema_now=ema_vals[-1], slope=slope)


def evaluate_ema50_path(
    bars: list[OhlcBar],
    idx: int,
    hit: PatternHit,
) -> tuple[bool | None, str]:
    meta = hit.meta
    direction = meta.get("direction")
    entry = meta.get("entry_px")
    style = meta.get("exit_style") or "ema_touch"
    if direction not in ("up", "down") or not entry:
        return None, "سطوح ورود/خروج EMA50 ناقص است."
    if idx + 1 >= len(bars):
        return None, "کندل کافی بعد از ورود برای ارزیابی نبود."

    ema_vals = ema([b.close for b in bars], EMA_LEN)
    exit_i = None
    exit_px = None
    reason = ""
    against = 0
    for i in range(idx + 1, len(bars)):
        b = bars[i]
        e = ema_vals[i]
        if e is None:
            continue
        if style == "ema_touch" and _touches_ema(b, e):
            exit_i, exit_px, reason = i, float(e), "لمس EMA50"
            break
        if style == "three_closes":
            wrong = b.close < e if direction == "up" else b.close > e
            against = against + 1 if wrong else 0
            if against >= TREND_EXIT_CLOSES:
                exit_i, exit_px, reason = i, b.close, "سه کلوز آن‌طرف EMA50"
                break
    if exit_i is None or exit_px is None:
        return None, "شرط خروج هنوز دیده نشد."

    if direction == "up":
        pct = (exit_px - entry) / entry
    else:
        pct = (entry - exit_px) / entry
    meta["entry_index"] = meta.get("entry_index", idx)
    meta["exit_index"] = exit_i
    meta["path_pct"] = pct
    ok = pct > 0
    note = (
        f"بازده مسیر ورود تا {reason}: "
        f"{pct*100:+.2f}٪ ({entry:,.0f} → {exit_px:,.0f})"
    )
    return ok, note
