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
STRETCH_BARS = {"5m": 5, "15m": 4, "1h": 3, "4h": 3, "1d": 3}
STRETCH_MIN_ATR = 0.7
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
        "mode": "trend",
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
        "mode": "trend",
    }


def _stretch_run(
    bars: list[OhlcBar],
    ema_vals: list[float | None],
    *,
    end_i: int,
    atr_now: float,
    side: str,
) -> tuple[int, int, float] | None:
    """(start, extreme_i, extreme_px) اگر چند کندل یک‌طرف خط مانده باشد."""
    if end_i < EMA_LEN:
        return None
    near = atr_now * 0.25
    run = 0
    extreme_i = end_i
    extreme = bars[end_i].high if side == "above" else bars[end_i].low
    for i in range(end_i, EMA_LEN - 1, -1):
        e = ema_vals[i]
        if e is None:
            break
        c = bars[i].close
        if side == "above":
            if c < e + near:
                break
            if bars[i].high > extreme:
                extreme, extreme_i = bars[i].high, i
        else:
            if c > e - near:
                break
            if bars[i].low < extreme:
                extreme, extreme_i = bars[i].low, i
        run += 1
    if run < 2:
        return None
    return end_i - run + 1, extreme_i, extreme


def _mild_revert_setup(
    bars: list[OhlcBar],
    *,
    ema_vals: list[float | None],
    atr_now: float,
    n: int,
    timeframe: str,
) -> dict | None:
    """شیب ملایم: فاصلهٔ چند کندلی از خط → ورود به سمت EMA50."""
    e_last = ema_vals[n - 1]
    if e_last is None:
        return None
    last = bars[n - 1]
    if last.close > e_last + atr_now * 0.35:
        side = "above"
    elif last.close < e_last - atr_now * 0.35:
        side = "below"
    else:
        return None
    stretched = _stretch_run(
        bars, ema_vals, end_i=n - 1, atr_now=atr_now, side=side
    )
    if stretched is None:
        return None
    start, extreme_i, extreme = stretched
    need = STRETCH_BARS.get(timeframe, 4)
    if n - start < need:
        return None
    far = 0.0
    for i in range(start, n):
        e = ema_vals[i]
        if e is None:
            continue
        far = max(far, abs(bars[i].close - e))
    if far < atr_now * STRETCH_MIN_ATR:
        return None

    if side == "above":
        direction = "down"
        cf = None
        for j in range(start + need - 1, n):
            if _bearish_confirm(bars[j], atr_now):
                cf = j
                break
        br = None
        if cf is not None:
            cl = bars[cf].low
            expire = EARLY_AGE.get(timeframe, 6)
            for j in range(cf + 1, n):
                if bars[j].low < cl and bars[j].close < bars[cf].open:
                    br = j
                    break
                if j - cf > expire:
                    break
        entry = bars[cf].low if cf is not None else last.close
        sl = extreme + atr_now * 0.08
        tp = float(e_last)
        risk = sl - entry
        if risk <= 0:
            return None
        return {
            "direction": direction,
            "pullback_index": extreme_i,
            "confirm_index": cf if cf is not None else n - 1,
            "break_index": br,
            "entry_px": entry,
            "sl_px": sl,
            "tp_px": tp,
            "early_side": "high",
            "mode": "revert",
        }

    direction = "up"
    cf = None
    for j in range(start + need - 1, n):
        if _bullish_confirm(bars[j], atr_now):
            cf = j
            break
    br = None
    if cf is not None:
        ch = bars[cf].high
        expire = EARLY_AGE.get(timeframe, 6)
        for j in range(cf + 1, n):
            if bars[j].high > ch and bars[j].close > bars[cf].open:
                br = j
                break
            if j - cf > expire:
                break
    entry = bars[cf].high if cf is not None else last.close
    sl = extreme - atr_now * 0.08
    tp = float(e_last)
    risk = entry - sl
    if risk <= 0:
        return None
    return {
        "direction": direction,
        "pullback_index": extreme_i,
        "confirm_index": cf if cf is not None else n - 1,
        "break_index": br,
        "entry_px": entry,
        "sl_px": sl,
        "tp_px": tp,
        "early_side": "low",
        "mode": "revert",
    }


def _pick_stage(setup: dict, n: int, timeframe: str) -> str | None:
    cf = setup["confirm_index"]
    br = setup["break_index"]
    early_lim = EARLY_AGE.get(timeframe, 6)
    br_lim = BREAK_AGE.get(timeframe, 3)
    if setup.get("mode") == "revert" and br is None and cf == n - 1:
        # فاصله گرفته؛ کندل برگشت هنوز نیامده
        if n - 1 - int(setup["pullback_index"]) <= early_lim + 2:
            return "early"
        return None
    if br is not None and n - 1 - br <= br_lim:
        return "confirmed"
    if br is None and n - 1 - cf <= early_lim:
        return "early"
    return None


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
    if slope_now is None:
        return None

    back = SEARCH_BACK.get(timeframe, 40)
    sw_hi = n - 1 - SWING_RIGHT
    sw_lo = max(EMA_LEN + lb, n - back)
    best: dict | None = None
    stage = ""
    slp = slope_now

    for sw in range(sw_hi, sw_lo - 1, -1):
        setup = None
        if is_pivot_low(lows, sw, SWING_LEFT, SWING_RIGHT):
            setup = _long_setup(
                bars,
                sw=sw,
                ema_vals=ema_vals,
                atr_now=atr_now,
                n=n,
                timeframe=timeframe,
            )
        if setup is None and is_pivot_high(highs, sw, SWING_LEFT, SWING_RIGHT):
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
        cand_slp = _slope_pct(ema_vals, trend_i, lb)
        if cand_slp is None:
            continue
        # شیب تند: فقط پولبک روند
        if setup["direction"] == "up" and cand_slp < min_sl:
            continue
        if setup["direction"] == "down" and cand_slp > -min_sl:
            continue
        picked = _pick_stage(setup, n, timeframe)
        if picked is None:
            continue
        best, stage, slp = setup, picked, cand_slp
        break

    if best is None and abs(slope_now) >= min_sl * 0.12:
        revert = _mild_revert_setup(
            bars,
            ema_vals=ema_vals,
            atr_now=atr_now,
            n=n,
            timeframe=timeframe,
        )
        if revert is not None:
            picked = _pick_stage(revert, n, timeframe)
            if picked is not None:
                best, stage, slp = revert, picked, slope_now

    if best is None:
        return None
    if stage == "early" and not allow_early:
        return None

    last = bars[-1]
    direction = best["direction"]
    mode = best.get("mode") or "trend"
    role = "لانگ" if direction == "up" else "شورت"
    if mode == "revert":
        title = f"EMA50 برگشت {role}"
    else:
        title = f"EMA50 {role}"
    if stage == "early":
        status = "سیگنال اولیه"
        lvl = best["entry_px"]
        if mode == "revert":
            forecast = (
                f"قیمت چند کندل از EMA50 فاصله گرفته. "
                f"ورود به سمت خط نزدیک {lvl:,.0f}."
            )
        else:
            forecast = (
                f"پولبک به EMA50 و کندل تأیید ثبت شد. "
                f"ورود با شکست {'سقف' if direction == 'up' else 'کف'} "
                f"نزدیک {lvl:,.0f}."
            )
    else:
        status = "تأییدشده"
        target = "برگشت به EMA50" if mode == "revert" else "هدف ۱:۲"
        forecast = (
            f"ورود {best['entry_px']:,.0f} — حد ضرر {best['sl_px']:,.0f} — "
            f"{target} حدود {best['tp_px']:,.0f}."
        )
    if mode == "revert":
        summary = (
            f"شیب EMA50 ملایم؛ فاصله از خط و برگشت به سمت "
            f"{best['tp_px']:,.0f}. قیمت {last.close:,.0f}."
        )
    else:
        summary = (
            f"شیب EMA50 {'صعودی' if direction == 'up' else 'نزولی'} تند؛ "
            f"پولبک و کندل تأیید. قیمت {last.close:,.0f}."
        )
    early_ix = best["confirm_index"]
    entry_ix = best["break_index"] if stage == "confirmed" else early_ix
    pid = (
        f"ema50_revert_{direction}_{stage}"
        if mode == "revert"
        else f"ema50_{direction}_{stage}"
    )
    return PatternHit(
        category="ema50",
        timeframe=timeframe,
        pattern_id=pid,
        title_fa=title,
        status_fa=status,
        summary_fa=summary,
        forecast_fa=forecast,
        meta={
            "kind": "ema50",
            "mode": mode,
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
    if ok:
        target = (
            "برگشت به EMA50" if meta.get("mode") == "revert" else "هدف ۱:۲"
        )
    else:
        target = "حد ضرر"
    note = (
        f"بازده مسیر ورود تا {target}: "
        f"{pct*100:+.2f}٪ ({entry:,.0f} → {exit_px:,.0f})"
    )
    return ok, note
