from __future__ import annotations

from optionflow.patterns.indicators import atr
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

SWING_LEFT = 3
SWING_RIGHT_EARLY = 2
MIN_SPAN = {"5m": 12, "15m": 10, "1h": 14, "4h": 10, "1d": 8}
MAX_PIVOT_AGE = {"5m": 18, "15m": 14, "1h": 16, "4h": 10, "1d": 8}


def _y(slope: float, intercept: float, i: float) -> float:
    return slope * i + intercept


def _line_through(i0: int, p0: float, i1: int, p1: float) -> tuple[float, float]:
    den = i1 - i0
    if abs(den) < 1e-9:
        return 0.0, p0
    slope = (p1 - p0) / den
    return slope, p0 - slope * i0


def _strict_swing(
    values: list[float], i: int, left: int, right: int, *, high: bool
) -> bool:
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
    highs: list[float], lows: list[float], *, right: int
) -> list[tuple[int, float, str]]:
    n = len(highs)
    raw: list[tuple[int, float, str]] = []
    for i in range(SWING_LEFT, n - right):
        if _strict_swing(highs, i, SWING_LEFT, right, high=True):
            raw.append((i, highs[i], "high"))
        if _strict_swing(lows, i, SWING_LEFT, right, high=False):
            raw.append((i, lows[i], "low"))
    raw.sort(key=lambda x: (x[0], 0 if x[2] == "high" else 1))
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


def _touches(
    points: list[tuple[int, float]],
    slope: float,
    intercept: float,
    tol: float,
) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for i, p in points:
        if abs(p - _y(slope, intercept, i)) <= tol:
            out.append((i, p))
    return out


def _broken(
    bars: list[OhlcBar],
    *,
    start_i: int,
    end_i: int,
    slope: float,
    intercept: float,
    side: str,
    atr_now: float,
) -> bool:
    buf = atr_now * 0.55
    last = min(end_i, len(bars) - 2)
    for i in range(start_i + 1, last + 1):
        line = _y(slope, intercept, i)
        if side == "low" and bars[i].close < line - buf:
            return True
        if side == "high" and bars[i].close > line + buf:
            return True
    return False


def _line_candidate(
    points: list[tuple[int, float]],
    bars: list[OhlcBar],
    *,
    side: str,
    atr_now: float,
    min_span: int,
    max_age: int,
) -> dict | None:
    if len(points) < 2:
        return None
    n = len(bars)
    last = bars[-1]
    tol = atr_now * 0.7
    near_lim = atr_now * 1.45
    best: dict | None = None
    pool = points[-8:]
    for a in range(len(pool)):
        for b in range(a + 1, len(pool)):
            i0, p0 = pool[a]
            i1, p1 = pool[b]
            span = i1 - i0
            if span < min_span:
                continue
            slope, intercept = _line_through(i0, p0, i1, p1)
            move = abs(p1 - p0)
            if move < atr_now * 0.35:
                continue
            if move > atr_now * 9:
                continue
            if side == "low" and (p1 - p0) < -atr_now * 1.8:
                continue
            if side == "high" and (p1 - p0) > atr_now * 1.8:
                continue
            hits = _touches(points, slope, intercept, tol)
            if len(hits) < 2:
                continue
            if _broken(
                bars,
                start_i=hits[0][0],
                end_i=n - 1,
                slope=slope,
                intercept=intercept,
                side=side,
                atr_now=atr_now,
            ):
                continue
            last_touch_i = hits[-1][0]
            last_age = n - 1 - last_touch_i
            y_now = _y(slope, intercept, n - 1)
            dist = abs(last.close - y_now)
            if side == "low":
                testing = last.low <= y_now + tol and last.close >= y_now - buf_safe(atr_now)
            else:
                testing = last.high >= y_now - tol and last.close <= y_now + buf_safe(atr_now)
            near = dist <= near_lim or testing
            if len(hits) < 3:
                if last_age > max_age and not near:
                    continue
            elif last_age > max_age * 3 and not near:
                continue
            forming = last_age <= SWING_RIGHT_EARLY
            stage = "confirmed" if len(hits) >= 3 and not forming else "early"
            score = len(hits) * 3.0 + (2.0 if testing or dist <= near_lim else 0.0)
            score += 2.0 if stage == "confirmed" else 1.0
            score -= dist / max(atr_now, 1.0) * 0.15
            cand = {
                "side": side,
                "slope": slope,
                "intercept": intercept,
                "touches": hits,
                "start_i": hits[0][0],
                "end_i": hits[-1][0],
                "y_now": y_now,
                "dist": dist,
                "testing": testing,
                "forming": forming,
                "stage": stage,
                "score": score,
            }
            if best is None or cand["score"] > best["score"]:
                best = cand
    return best


def buf_safe(atr_now: float) -> float:
    return atr_now * 0.35


def _parallel_channel(
    primary: dict,
    opp_points: list[tuple[int, float]],
    atr_now: float,
) -> dict | None:
    if len(opp_points) < 1:
        return None
    slope = primary["slope"]
    tol = atr_now * 0.85
    best_hits: list[tuple[int, float]] = []
    best_intercept = 0.0
    for i, p in opp_points:
        intercept = p - slope * i
        hits = _touches(opp_points, slope, intercept, tol)
        if len(hits) > len(best_hits):
            best_hits = hits
            best_intercept = intercept
        elif len(hits) == len(best_hits) and hits:
            # closer to the other line = tighter channel
            width = abs(
                _y(slope, intercept, primary["start_i"])
                - _y(slope, primary["intercept"], primary["start_i"])
            )
            prev_w = abs(
                _y(slope, best_intercept, primary["start_i"])
                - _y(slope, primary["intercept"], primary["start_i"])
            )
            if width < prev_w:
                best_hits = hits
                best_intercept = intercept
    if not best_hits:
        return None
    width = abs(
        _y(slope, best_intercept, primary["end_i"])
        - _y(slope, primary["intercept"], primary["end_i"])
    )
    if width < atr_now * 0.8 or width > atr_now * 12:
        return None
    return {
        "slope": slope,
        "intercept": best_intercept,
        "touches": best_hits,
        "width": width,
    }


def detect_trendline(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    allow_early: bool = True,
) -> PatternHit | None:
    if len(bars) < 50:
        return None
    window = bars[-180:] if len(bars) >= 180 else bars[:]
    n = len(window)
    highs = [b.high for b in window]
    lows = [b.low for b in window]
    swings = _price_swings(highs, lows, right=SWING_RIGHT_EARLY)
    if len(swings) < 4:
        return None
    atr_vals = atr(window)
    atr_now = next((v for v in reversed(atr_vals) if v is not None), None)
    if atr_now is None or atr_now <= 0:
        return None

    lo_pts = [(i, p) for i, p, k in swings if k == "low"]
    hi_pts = [(i, p) for i, p, k in swings if k == "high"]
    min_span = MIN_SPAN.get(timeframe, 12)
    max_age = MAX_PIVOT_AGE.get(timeframe, 14)
    support = _line_candidate(
        lo_pts, window, side="low", atr_now=atr_now, min_span=min_span, max_age=max_age
    )
    resist = _line_candidate(
        hi_pts, window, side="high", atr_now=atr_now, min_span=min_span, max_age=max_age
    )
    if support is None and resist is None:
        return None

    primary = support if resist is None or (support and support["score"] >= resist["score"]) else resist
    opposite = resist if primary is support else support
    opp_pts = hi_pts if primary["side"] == "low" else lo_pts
    ch = _parallel_channel(primary, opp_pts, atr_now)
    is_channel = False
    if ch and (opposite is None or abs(ch["slope"] - opposite["slope"]) <= abs(primary["slope"]) * 0.35 + 1e-9):
        is_channel = True
    elif opposite is not None:
        slope_gap = abs(primary["slope"] - opposite["slope"])
        if slope_gap <= atr_now * 0.02 / max(primary["end_i"] - primary["start_i"], 1):
            is_channel = True
            ch = {
                "slope": opposite["slope"],
                "intercept": opposite["intercept"],
                "touches": opposite["touches"],
                "width": abs(primary["y_now"] - opposite["y_now"]),
            }

    last = window[-1]
    n_pri = len(primary["touches"])
    n_opp = len(ch["touches"]) if is_channel and ch else 0
    if is_channel:
        stage = "confirmed" if (n_pri >= 2 and n_opp >= 2) or n_pri >= 3 else "early"
        kind = "channel"
    else:
        stage = primary["stage"]
        kind = "trendline"
        ch = None
        n_opp = 0

    if stage == "early" and not allow_early:
        return None

    slope = primary["slope"]
    if primary["side"] == "low":
        direction = "up"
        role = "حمایت"
    else:
        direction = "down"
        role = "مقاومت"

    if is_channel:
        if slope > atr_now * 0.02 / 20:
            title = "کانال صعودی"
            direction = "up"
        elif slope < -atr_now * 0.02 / 20:
            title = "کانال نزولی"
            direction = "down"
        else:
            title = "کانال افقی"
        summary = (
            f"{n_pri} برخورد {role} و {n_opp} برخورد ضلع مخالف. "
            f"عرض کانال حدود {ch['width']:,.0f} دلار. قیمت {last.close:,.0f}."
        )
        if stage == "early":
            forecast = (
                "کانال تازه در حال شکل‌گیری است؛ تا برخورد سوم یا ضلع دوم، "
                "فقط به‌عنوان محدودهٔ اولیه در نظر بگیرید."
            )
            status = "سیگنال اولیه"
        else:
            forecast = (
                f"حرکت داخل کانال؛ واکنش محتمل روی {role} "
                f"نزدیک {primary['y_now']:,.0f}."
            )
            status = "تأییدشده"
    else:
        title = f"ترندلاین {role}"
        summary = (
            f"{n_pri} برخورد روی خط {role}. "
            f"خط در قیمت فعلی حدود {primary['y_now']:,.0f} — قیمت {last.close:,.0f}."
        )
        if stage == "early":
            forecast = (
                f"خط با دو برخورد شناسایی شد (اولیه). اگر قیمت به {primary['y_now']:,.0f} برسد "
                f"و نگهدارد، برخورد سوم تأیید می‌کند."
            )
            status = "سیگنال اولیه"
        else:
            forecast = (
                f"خط با {n_pri} برخورد تأیید شده؛ واکنش روی {primary['y_now']:,.0f} "
                f"{'صعودی' if direction == 'up' else 'نزولی'} محتمل‌تر است."
            )
            status = "تأییدشده"

    if primary.get("testing"):
        summary += " کندل جاری خط را لمس کرده."

    wo = len(bars) - n
    early_ix = wo + primary["touches"][1][0] if len(primary["touches"]) >= 2 else wo + primary["end_i"]
    upper = lower = None
    if is_channel and ch:
        if primary["side"] == "low":
            lower = (primary["slope"], primary["intercept"])
            upper = (ch["slope"], ch["intercept"])
        else:
            upper = (primary["slope"], primary["intercept"])
            lower = (ch["slope"], ch["intercept"])
    elif primary["side"] == "low":
        lower = (primary["slope"], primary["intercept"])
    else:
        upper = (primary["slope"], primary["intercept"])

    return PatternHit(
        category="trendline",
        timeframe=timeframe,
        pattern_id=f"{kind}_{primary['side']}_{stage}",
        title_fa=title,
        status_fa=status,
        summary_fa=summary,
        forecast_fa=forecast,
        meta={
            "kind": kind,
            "stage": stage,
            "direction": direction,
            "side": primary["side"],
            "upper_slope": upper[0] if upper else None,
            "upper_intercept": upper[1] if upper else None,
            "lower_slope": lower[0] if lower else None,
            "lower_intercept": lower[1] if lower else None,
            "start_i": primary["start_i"],
            "end_i": n - 1,
            "window_offset": wo,
            "touch_highs": [i for i, _ in (ch["touches"] if is_channel and ch and primary["side"] == "low" else (primary["touches"] if primary["side"] == "high" else []))],
            "touch_lows": [i for i, _ in (primary["touches"] if primary["side"] == "low" else (ch["touches"] if is_channel and ch else []))],
            "y_now": primary["y_now"],
            "early_index": early_ix,
            "last_close": last.close,
        },
    )
