from __future__ import annotations

from optionflow.patterns.indicators import atr
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

# پیوت ساختاری (چپ/راست) — برخوردهای شکل کتابی
SWING_LEFT = 3
SWING_RIGHT = 2
_MIN_SWINGS = 5  # حداقل یک فنر کامل: مثلاً H-L-H-L-H
_MIN_SPAN = {"5m": 20, "15m": 16, "1h": 30, "4h": 14, "1d": 10}
_FLAT_PCT = {"5m": 0.0028, "15m": 0.0038, "1h": 0.005, "4h": 0.007, "1d": 0.01}
_MAX_PIVOT_AGE = {"5m": 20, "15m": 14, "1h": 18, "4h": 10, "1d": 8}


def _y(slope: float, intercept: float, i: float) -> float:
    return slope * i + intercept


def _line_through(i0: int, p0: float, i1: int, p1: float) -> tuple[float, float]:
    den = i1 - i0
    if abs(den) < 1e-9:
        return 0.0, p0
    slope = (p1 - p0) / den
    return slope, p0 - slope * i0


def _apex_index(su: float, iu: float, sl: float, il: float) -> float | None:
    den = su - sl
    if abs(den) < 1e-12:
        return None
    return (il - iu) / den


def _strict_swing(
    values: list[float], i: int, left: int, right: int, *, high: bool
) -> bool:
    """اکسترمم یکتا — فلات افقی سقف/کف حساب نمی‌شود."""
    if i - left < 0 or i + right >= len(values):
        return False
    val = values[i]
    for j in range(i - left, i + right + 1):
        if j == i:
            continue
        if high and values[j] >= val:
            return False
        if not high and values[j] <= val:
            return False
    return True


def _price_swings(
    highs: list[float], lows: list[float]
) -> list[tuple[int, float, str]]:
    n = len(highs)
    raw: list[tuple[int, float, str]] = []
    for i in range(SWING_LEFT, n - SWING_RIGHT):
        if _strict_swing(highs, i, SWING_LEFT, SWING_RIGHT, high=True):
            raw.append((i, highs[i], "high"))
        if _strict_swing(lows, i, SWING_LEFT, SWING_RIGHT, high=False):
            raw.append((i, lows[i], "low"))
    raw.sort(key=lambda x: (x[0], 0 if x[2] == "high" else 1))
    if not raw:
        return []

    alt: list[tuple[int, float, str]] = []
    for item in raw:
        if not alt:
            alt.append(item)
            continue
        i, p, k = item
        _pi, pp, pk = alt[-1]
        if k == pk:
            if (k == "high" and p >= pp) or (k == "low" and p <= pp):
                alt[-1] = item
            continue
        alt.append(item)
    return alt


def _flat_enough(values: list[float], atr_now: float, flat_pct: float) -> bool:
    span = max(values) - min(values)
    mid = sum(values) / len(values)
    return span <= max(atr_now * 0.75, mid * flat_pct)


def _points_on_line(
    idxs: list[int],
    px: list[float],
    slope: float,
    intercept: float,
    tol: float,
    *,
    side: str,
) -> bool:
    for i, p in zip(idxs, px):
        line = _y(slope, intercept, i)
        if side == "high" and p > line + tol:
            return False
        if side == "low" and p < line - tol:
            return False
        if abs(p - line) > tol * 1.8:
            return False
    return True


def _classify(
    hi_px: list[float],
    lo_px: list[float],
    atr_now: float,
    flat_pct: float,
) -> str | None:
    hi_dir = hi_px[-1] - hi_px[0]
    lo_dir = lo_px[-1] - lo_px[0]
    move = max(atr_now * 0.35, hi_px[-1] * 0.0015)
    highs_fall = hi_dir <= -move
    lows_rise = lo_dir >= move
    flat_hi = _flat_enough(hi_px, atr_now, flat_pct)
    flat_lo = _flat_enough(lo_px, atr_now, flat_pct)

    if flat_hi and lows_rise:
        return "ascending"
    if flat_lo and highs_fall:
        return "descending"
    if highs_fall and lows_rise:
        return "symmetrical"
    return None


def _score_window(
    seq: list[tuple[int, float, str]],
    n: int,
    last: OhlcBar,
    atr_now: float,
    timeframe: str,
) -> dict | None:
    ph = [(i, p) for i, p, k in seq if k == "high"]
    pl = [(i, p) for i, p, k in seq if k == "low"]
    if len(ph) < 2 or len(pl) < 2:
        return None

    hi_idx = [i for i, _ in ph]
    hi_px = [p for _, p in ph]
    lo_idx = [i for i, _ in pl]
    lo_px = [p for _, p in pl]
    start_i = min(hi_idx[0], lo_idx[0])
    end_i = max(hi_idx[-1], lo_idx[-1])
    if end_i - start_i < _MIN_SPAN.get(timeframe, 16):
        return None
    if n - 1 - seq[-1][0] > _MAX_PIVOT_AGE.get(timeframe, 16):
        return None

    kind = _classify(hi_px, lo_px, atr_now, _FLAT_PCT.get(timeframe, 0.004))
    if kind is None:
        return None

    if kind == "ascending":
        level = sum(hi_px) / len(hi_px)
        su, iu = 0.0, level
        sl, il = _line_through(lo_idx[0], lo_px[0], lo_idx[-1], lo_px[-1])
    elif kind == "descending":
        level = sum(lo_px) / len(lo_px)
        sl, il = 0.0, level
        su, iu = _line_through(hi_idx[0], hi_px[0], hi_idx[-1], hi_px[-1])
    else:
        su, iu = _line_through(hi_idx[0], hi_px[0], hi_idx[-1], hi_px[-1])
        sl, il = _line_through(lo_idx[0], lo_px[0], lo_idx[-1], lo_px[-1])

    tol = atr_now * 0.85
    if not _points_on_line(hi_idx, hi_px, su, iu, tol, side="high"):
        return None
    if not _points_on_line(lo_idx, lo_px, sl, il, tol, side="low"):
        return None

    gap_start = _y(su, iu, start_i) - _y(sl, il, start_i)
    gap_end = _y(su, iu, end_i) - _y(sl, il, end_i)
    if gap_start <= 0 or gap_end <= 0:
        return None
    if gap_end >= gap_start * 0.92:
        return None

    u_now = _y(su, iu, n - 1)
    l_now = _y(sl, il, n - 1)
    if u_now <= l_now:
        return None
    if last.close > u_now + atr_now * 2.4 or last.close < l_now - atr_now * 2.4:
        return None

    apex = _apex_index(su, iu, sl, il)
    if apex is not None and apex < end_i:
        return None

    contraction = 1.0 - (gap_end / gap_start)
    score = contraction * 10 + len(seq) + (2 if kind != "symmetrical" else 1)
    return {
        "kind": kind,
        "su": su,
        "iu": iu,
        "sl": sl,
        "il": il,
        "start_i": start_i,
        "end_i": end_i,
        "gap_start": gap_start,
        "gap_end": gap_end,
        "u_now": u_now,
        "l_now": l_now,
        "apex": apex,
        "hi_idx": hi_idx,
        "lo_idx": lo_idx,
        "score": score,
        "touches_high": len(ph),
        "touches_low": len(pl),
        "hi_px": hi_px,
        "lo_px": lo_px,
    }


def _close_side(close: float, upper: float, lower: float, buf: float) -> str | None:
    if close > upper + buf:
        return "up"
    if close < lower - buf:
        return "down"
    return None


def _wick_side(bar: OhlcBar, upper: float, lower: float, buf: float) -> str | None:
    """سایه از یک ضلع گذشته و بسته شدن داخل مثلث مانده."""
    up = bar.high > upper + buf
    down = bar.low < lower - buf
    if up and down:
        return None
    if up:
        return "up"
    if down:
        return "down"
    return None


def _resolve_triangle_break(window: list[OhlcBar], best: dict, atr_now: float) -> dict:
    """شکست معتبر دو کلوز پشت‌سرهم است. خروج یک کندل یا سایه که برگردد فیک‌اوت است."""
    n = len(window)
    su, iu = best["su"], best["iu"]
    sl, il = best["sl"], best["il"]
    buf = atr_now * 0.12
    start = max(0, int(best["end_i"]))
    pending: str | None = None
    confirmed: str | None = None
    failed: str | None = None
    remembered: str | None = None
    run = 0
    just_held = False

    for i in range(start, n):
        upper = _y(su, iu, i)
        lower = _y(sl, il, i)
        bar = window[i]
        closed = _close_side(bar.close, upper, lower, buf)
        if closed:
            if pending == closed:
                confirmed = closed
                pending = None
                failed = None
                if remembered == closed:
                    remembered = None
                run = 2
                just_held = i == n - 1
            elif confirmed == closed:
                pending = None
                failed = None
                run = max(run, 2) + 1
                just_held = False
            else:
                if pending and pending != closed:
                    remembered = pending
                pending = closed
                run = 1
                just_held = False
            continue
        wick = _wick_side(bar, upper, lower, buf)
        if pending and confirmed != pending:
            failed = pending
            remembered = pending
        elif wick and confirmed is None:
            failed = wick
            remembered = wick
        pending = None
        run = 0
        just_held = False

    last_side = _close_side(
        window[-1].close, _y(su, iu, n - 1), _y(sl, il, n - 1), buf
    )
    if last_side:
        held = confirmed == last_side and run >= 2
        fake = remembered if remembered and remembered != last_side else None
        return {
            "direction": last_side,
            "fresh": just_held and held,
            "retesting": False,
            "fake_side": fake,
            "held": held,
            "stage": "breakout",
        }
    if confirmed and failed is None:
        return {
            "direction": confirmed,
            "fresh": False,
            "retesting": True,
            "fake_side": None,
            "held": True,
            "stage": "breakout",
        }
    if failed:
        return {
            "direction": None,
            "fresh": False,
            "retesting": False,
            "fake_side": failed,
            "held": False,
            "stage": "fakeout",
        }
    return {
        "direction": None,
        "fresh": False,
        "retesting": False,
        "fake_side": None,
        "held": False,
        "stage": "forming",
    }


def detect_triangle(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    require_breakout: bool = False,
) -> PatternHit | None:
    if len(bars) < 60:
        return None
    window = bars[-180:] if len(bars) >= 180 else bars[:]
    n = len(window)
    highs = [b.high for b in window]
    lows = [b.low for b in window]
    swings = _price_swings(highs, lows)
    if len(swings) < _MIN_SWINGS:
        return None

    atr_vals = atr(window)
    atr_now = next((v for v in reversed(atr_vals) if v is not None), None)
    if atr_now is None or atr_now <= 0:
        return None

    last = window[-1]
    cleaned: list[tuple[int, float, str]] = []
    min_leg = atr_now * 0.55
    for item in swings:
        if not cleaned:
            cleaned.append(item)
            continue
        i, p, k = item
        _pi, pp, pk = cleaned[-1]
        if k == pk:
            if (k == "high" and p >= pp) or (k == "low" and p <= pp):
                cleaned[-1] = item
            continue
        if abs(p - pp) < min_leg:
            continue
        cleaned.append(item)
    swings = cleaned
    if len(swings) < _MIN_SWINGS:
        return None

    best: dict | None = None
    for length in range(_MIN_SWINGS, min(9, len(swings) + 1)):
        cand = _score_window(swings[-length:], n, last, atr_now, timeframe)
        if cand and (best is None or cand["score"] > best["score"]):
            best = cand
    if best is None:
        return None

    kind = best["kind"]
    titles = {
        "ascending": (
            "مثلث صعودی (فشردگی)",
            "مقاومت افقی و کف‌های بالاتر — ورود فقط با بسته شدن بالای مقاومت.",
        ),
        "descending": (
            "مثلث نزولی (فشردگی)",
            "حمایت افقی و سقف‌های پایین‌تر — ورود فقط با بسته شدن زیر حمایت.",
        ),
        "symmetrical": (
            "مثلث متقارن (فشردگی)",
            "سقف پایین‌تر و کف بالاتر — جهت بعد از شکست خط مشخص می‌شود.",
        ),
    }
    title, forecast = titles[kind]
    u_now, l_now = best["u_now"], best["l_now"]
    state = _resolve_triangle_break(window, best, atr_now)
    direction = state["direction"]
    fresh = state["fresh"]
    retesting = state["retesting"]
    fake_side = state["fake_side"]
    held = state["held"]
    stage = state["stage"]
    apex = best["apex"]
    apex_reached = isinstance(apex, (int, float)) and float(apex) <= (n - 1)
    if stage == "forming" and apex_reached:
        return None
    if require_breakout and not fresh:
        return None

    side_fa = {"up": "صعودی", "down": "نزولی"}
    where_fa = {"up": "بالای خط", "down": "پایین خط"}
    if stage == "fakeout" and fake_side in side_fa:
        status = f"فیک‌اوت {side_fa[fake_side]}"
        forecast = (
            f"خروج {where_fa[fake_side]} نگه داشته نشد. "
            f"قیمت {last.close:,.0f} داخل مثلث است و مسیر معتبر سمت مقابل است."
        )
        resolution = f" — فیک‌اوت {side_fa[fake_side]}؛ قیمت داخل مثلث برگشته."
    elif direction in side_fa and retesting:
        status = f"شکست {side_fa[direction]}"
        forecast = (
            f"شکست {where_fa[direction]} تأیید شده. "
            f"قیمت {last.close:,.0f} برای لمس دوباره نزدیک خط است."
        )
        resolution = f" — شکست {side_fa[direction]} تأیید شده؛ قیمت روی خط برگشته."
    elif direction in side_fa and held and fake_side in side_fa:
        status = f"شکست {side_fa[direction]}"
        forecast = (
            f"فیک‌اوت {side_fa[fake_side]} تمام شد. "
            f"شکست {where_fa[direction]} در قیمت {last.close:,.0f}."
        )
        resolution = (
            f" — فیک‌اوت {side_fa[fake_side]}، بعد تأیید شکست {side_fa[direction]}."
        )
    elif direction in side_fa and held:
        status = f"شکست {side_fa[direction]}"
        forecast = f"شکست {where_fa[direction]} در قیمت {last.close:,.0f}."
        resolution = f" — تأیید شکست {side_fa[direction]}."
    elif direction in side_fa and fake_side in side_fa:
        status = f"شکست {side_fa[direction]}"
        forecast = (
            f"فیک‌اوت {side_fa[fake_side]} بود. "
            f"کندل اول {where_fa[direction]} در {last.close:,.0f} بسته شد."
        )
        resolution = (
            f" — فیک‌اوت {side_fa[fake_side]}؛ خروج {side_fa[direction]} هنوز یک کندل است."
        )
    elif direction in side_fa:
        status = f"شکست {side_fa[direction]}"
        forecast = (
            f"کندل اول {where_fa[direction]} بسته شد ({last.close:,.0f}). "
            f"کندل بعد اگر بیرون بماند شکست معتبر است."
        )
        resolution = " — خروج کندل اول؛ منتظر کندل تأیید."
    else:
        status = "در حال فشردگی"
        forecast = titles[kind][1]
        resolution = " — هنوز داخل الگو؛ منتظر شکست."

    return PatternHit(
        category="triangle",
        timeframe=timeframe,
        pattern_id=f"triangle_{kind}",
        title_fa=title,
        status_fa=status,
        summary_fa=(
            f"{best['touches_high']} برخورد سقف و {best['touches_low']} برخورد کف. "
            f"فاصله خطوط از {best['gap_start']:,.0f} به {best['gap_end']:,.0f} دلار. "
            f"قیمت {last.close:,.0f}{resolution}"
        ),
        forecast_fa=forecast,
        meta={
            "upper_slope": best["su"],
            "upper_intercept": best["iu"],
            "lower_slope": best["sl"],
            "lower_intercept": best["il"],
            "start_i": best["start_i"],
            "end_i": best["end_i"],
            "window_offset": len(bars) - n,
            "kind": kind,
            "last_close": last.close,
            "mid": (u_now + l_now) / 2,
            "apex_index": best["apex"],
            "touches_high": best["touches_high"],
            "touches_low": best["touches_low"],
            "touch_highs": best["hi_idx"],
            "touch_lows": best["lo_idx"],
            "touch_high_prices": [float(p) for p in best["hi_px"]],
            "touch_low_prices": [float(p) for p in best["lo_px"]],
            "direction": direction,
            "stage": stage,
            "retest": retesting,
            "held": held,
            "fake_side": fake_side,
            "confirm_index": n - 1 + (len(bars) - n),
            "upper_now": u_now,
            "lower_now": l_now,
        },
    )
