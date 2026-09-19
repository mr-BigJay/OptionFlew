from __future__ import annotations

from optionflow.patterns.indicators import atr, ema, is_pivot_high, is_pivot_low
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

EMA_LEN = 50
SWING_LEFT = 2
SWING_RIGHT = 2
SLOPE_BARS = {"5m": 10, "15m": 8, "1h": 6, "4h": 5, "1d": 4}
MIN_SLOPE = {"5m": 0.0015, "15m": 0.002, "1h": 0.003, "4h": 0.004, "1d": 0.005}
CHOP_BARS = {"5m": 30, "15m": 24, "1h": 20, "4h": 16, "1d": 12}
MAX_CROSSES = {"5m": 5, "15m": 4, "1h": 4, "4h": 3, "1d": 3}
CONFIRM_WINDOW = 6
EARLY_AGE = {"5m": 8, "15m": 6, "1h": 5, "4h": 4, "1d": 3}
BREAK_AGE = {"5m": 4, "15m": 3, "1h": 3, "4h": 2, "1d": 2}
SEARCH_BACK = {"5m": 48, "15m": 40, "1h": 32, "4h": 24, "1d": 18}
RR = 2.0


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


def _bullish_confirm(bar: OhlcBar, atr_now: float) -> bool:
    if bar.close <= bar.open:
        return False
    body = bar.close - bar.open
    rng = max(bar.high - bar.low, 1e-9)
    return body / rng >= 0.28 or body >= atr_now * 0.12


def _bearish_confirm(bar: OhlcBar, atr_now: float) -> bool:
    if bar.close >= bar.open:
        return False
    body = bar.open - bar.close
    rng = max(bar.high - bar.low, 1e-9)
    return body / rng >= 0.28 or body >= atr_now * 0.12


def _long_setup(
    bars: list[OhlcBar],
    *,
    sw: int,
    ema_vals: list[float | None],
    atr_now: float,
    n: int,
    timeframe: str,
) -> dict | None:
    e = ema_vals[sw]
    if e is None:
        return None
    low, close = bars[sw].low, bars[sw].close
    if low > e + atr_now * 0.55:
        return None
    if close < e - atr_now * 0.45:
        return None
    pre0 = max(EMA_LEN, sw - 12)
    above = 0
    peak = bars[sw].high
    for j in range(pre0, sw):
        ej = ema_vals[j]
        if ej is not None and bars[j].close > ej:
            above += 1
        peak = max(peak, bars[j].high)
    if above < max(3, int((sw - pre0) * 0.6)):
        return None
    if peak < e + atr_now * 0.65:
        return None
    cf = None
    for j in range(sw + 1, min(n, sw + 1 + CONFIRM_WINDOW)):
        if _bullish_confirm(bars[j], atr_now) and bars[j].close > bars[sw].low:
            cf = j
            break
    if cf is None:
        return None
    br = None
    ch = bars[cf].high
    expire = EARLY_AGE.get(timeframe, 6)
    for j in range(cf + 1, n):
        if bars[j].high > ch and bars[j].close > bars[cf].open:
            br = j
            break
        if j - cf > expire:
            break
    entry = ch
    sl = low - atr_now * 0.08
    risk = entry - sl
    if risk <= 0:
        return None
    return {
        "direction": "up",
        "pullback_index": sw,
        "confirm_index": cf,
        "break_index": br,
        "entry_px": entry,
        "sl_px": sl,
        "tp_px": entry + RR * risk,
        "early_side": "low",
    }


def _short_setup(
    bars: list[OhlcBar],
    *,
    sw: int,
    ema_vals: list[float | None],
    atr_now: float,
    n: int,
    timeframe: str,
) -> dict | None:
    e = ema_vals[sw]
    if e is None:
        return None
    high, close = bars[sw].high, bars[sw].close
    if high < e - atr_now * 0.55:
        return None
    if close > e + atr_now * 0.45:
        return None
    pre0 = max(EMA_LEN, sw - 12)
    below = 0
    trough = bars[sw].low
    for j in range(pre0, sw):
        ej = ema_vals[j]
        if ej is not None and bars[j].close < ej:
            below += 1
        trough = min(trough, bars[j].low)
    if below < max(3, int((sw - pre0) * 0.6)):
        return None
    if trough > e - atr_now * 0.65:
        return None
    cf = None
    for j in range(sw + 1, min(n, sw + 1 + CONFIRM_WINDOW)):
        if _bearish_confirm(bars[j], atr_now) and bars[j].close < bars[sw].high:
            cf = j
            break
    if cf is None:
        return None
    br = None
    cl = bars[cf].low
    expire = EARLY_AGE.get(timeframe, 6)
    for j in range(cf + 1, n):
        if bars[j].low < cl and bars[j].close < bars[cf].open:
            br = j
            break
        if j - cf > expire:
            break
    entry = cl
    sl = high + atr_now * 0.08
    risk = sl - entry
    if risk <= 0:
        return None
    return {
        "direction": "down",
        "pullback_index": sw,
        "confirm_index": cf,
        "break_index": br,
        "entry_px": entry,
        "sl_px": sl,
        "tp_px": entry - RR * risk,
        "early_side": "high",
    }


def detect_ema50(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    allow_early: bool = True,
) -> PatternHit | None:
    if len(bars) < EMA_LEN + 16:
        return None
    n = len(bars)
    closes = [b.close for b in bars]
    lows = [b.low for b in bars]
    highs = [b.high for b in bars]
    ema_vals = ema(closes, EMA_LEN)
    atr_vals = atr(bars)
    atr_now = next((v for v in reversed(atr_vals) if v is not None), None)
    if atr_now is None or atr_now <= 0:
        return None
    if _is_chop(closes, ema_vals, n - 1, timeframe):
        return None

    lb = SLOPE_BARS.get(timeframe, 8)
    min_sl = MIN_SLOPE.get(timeframe, 0.002)
    slope_now = _slope_pct(ema_vals, n - 1, lb)
    if slope_now is None or abs(slope_now) < min_sl * 0.12:
        return None

    back = SEARCH_BACK.get(timeframe, 40)
    sw_hi = n - 1 - SWING_RIGHT
    sw_lo = max(EMA_LEN + lb, n - back)
    best: dict | None = None
    stage = ""

    for sw in range(sw_hi, sw_lo - 1, -1):
        setup = None
        if slope_now >= -min_sl * 0.25 and is_pivot_low(
            lows, sw, SWING_LEFT, SWING_RIGHT
        ):
            setup = _long_setup(
                bars,
                sw=sw,
                ema_vals=ema_vals,
                atr_now=atr_now,
                n=n,
                timeframe=timeframe,
            )
        if setup is None and slope_now <= min_sl * 0.25 and is_pivot_high(
            highs, sw, SWING_LEFT, SWING_RIGHT
        ):
            setup = _short_setup(
                bars,
                sw=sw,
                ema_vals=ema_vals,
                atr_now=atr_now,
                n=n,
                timeframe=timeframe,
            )
        if setup is None:
            continue
        trend_i = max(EMA_LEN + lb, sw - 4)
        slp = _slope_pct(ema_vals, trend_i, lb)
        if slp is None:
            continue
        if setup["direction"] == "up" and slp < min_sl:
            continue
        if setup["direction"] == "down" and slp > -min_sl:
            continue
        cf = setup["confirm_index"]
        br = setup["break_index"]
        early_lim = EARLY_AGE.get(timeframe, 6)
        br_lim = BREAK_AGE.get(timeframe, 3)
        if br is not None and n - 1 - br <= br_lim:
            best, stage = setup, "confirmed"
            break
        if br is None and n - 1 - cf <= early_lim:
            best, stage = setup, "early"
            break

    if best is None:
        return None
    if stage == "early" and not allow_early:
        return None

    last = bars[-1]
    direction = best["direction"]
    role = "لانگ" if direction == "up" else "شورت"
    title = f"EMA50 {role}"
    if stage == "early":
        status = "سیگنال اولیه"
        lvl = best["entry_px"]
        forecast = (
            f"پولبک به EMA50 و کندل تأیید ثبت شد. "
            f"ورود با شکست {'سقف' if direction == 'up' else 'کف'} "
            f"نزدیک {lvl:,.0f}."
        )
    else:
        status = "تأییدشده"
        forecast = (
            f"ورود {best['entry_px']:,.0f} — حد ضرر {best['sl_px']:,.0f} — "
            f"هدف ۱:۲ حدود {best['tp_px']:,.0f}."
        )
    summary = (
        f"شیب EMA50 {'صعودی' if direction == 'up' else 'نزولی'}؛ "
        f"پولبک و کندل تأیید. قیمت {last.close:,.0f}."
    )
    early_ix = best["confirm_index"]
    entry_ix = best["break_index"] if stage == "confirmed" else early_ix
    return PatternHit(
        category="ema50",
        timeframe=timeframe,
        pattern_id=f"ema50_{direction}_{stage}",
        title_fa=title,
        status_fa=status,
        summary_fa=summary,
        forecast_fa=forecast,
        meta={
            "kind": "ema50",
            "stage": stage,
            "direction": direction,
            "side": "low" if direction == "up" else "high",
            "early_side": best["early_side"],
            "pullback_index": best["pullback_index"],
            "confirm_index": best["confirm_index"],
            "entry_index": entry_ix,
            "early_index": early_ix,
            "break_index": best["break_index"],
            "entry_px": best["entry_px"],
            "sl_px": best["sl_px"],
            "tp_px": best["tp_px"],
            "ema_now": ema_vals[-1],
            "slope_pct": slp,
            "last_close": last.close,
        },
    )


def evaluate_ema50_path(
    bars: list[OhlcBar],
    idx: int,
    hit: PatternHit,
) -> tuple[bool | None, str]:
    """ورود روی شکست کندل تأیید؛ خروج روی حد ضرر یا هدف ۱:۲."""
    meta = hit.meta
    direction = meta.get("direction")
    entry = meta.get("entry_px")
    sl = meta.get("sl_px")
    tp = meta.get("tp_px")
    if direction not in ("up", "down") or not entry or not sl or not tp:
        return None, "سطوح ورود/خروج EMA50 ناقص است."
    if idx + 1 >= len(bars):
        return None, "کندل کافی بعد از ورود برای ارزیابی نبود."

    exit_i = None
    exit_px = None
    both = False
    for i in range(idx + 1, len(bars)):
        b = bars[i]
        hit_sl = b.low <= sl if direction == "up" else b.high >= sl
        hit_tp = b.high >= tp if direction == "up" else b.low <= tp
        if hit_sl and hit_tp:
            both = True
            exit_i, exit_px = i, sl
            break
        if hit_sl:
            exit_i, exit_px = i, sl
            break
        if hit_tp:
            exit_i, exit_px = i, tp
            break
    if exit_i is None or exit_px is None:
        return None, "هنوز نه حد ضرر و نه هدف ۱:۲ دیده نشد."
    if both:
        return None, "حد ضرر و هدف در یک کندل بودند؛ نتیجه نامشخص."

    if direction == "up":
        pct = (exit_px - entry) / entry
    else:
        pct = (entry - exit_px) / entry
    entry_i = meta.get("entry_index", idx)
    if not isinstance(entry_i, int):
        entry_i = idx
    meta["entry_index"] = entry_i
    meta["exit_index"] = exit_i
    meta["path_pct"] = pct
    ok = pct > 0
    note = (
        f"بازده مسیر ورود تا {'هدف ۱:۲' if ok else 'حد ضرر'}: "
        f"{pct*100:+.2f}٪ ({entry:,.0f} → {exit_px:,.0f})"
    )
    return ok, note
