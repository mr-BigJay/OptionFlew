from __future__ import annotations

from optionflow.patterns.indicators import atr
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

SWING_LEFT = 3
SWING_RIGHT = 2
MIN_SPAN = {"5m": 16, "15m": 12, "1h": 16, "4h": 12, "1d": 8}
MAX_PIVOT_AGE = {"5m": 14, "15m": 12, "1h": 12, "4h": 8, "1d": 6}
MIN_TOUCH_GAP = {"5m": 6, "15m": 5, "1h": 5, "4h": 4, "1d": 3}
WINDOW = {"5m": 120, "15m": 120, "1h": 140, "4h": 120, "1d": 90}
TAKE_PROFIT_PCT = 0.005  # بعد از ورود: بستن در ۰.۵٪ سود
PATH_EVAL_BARS = {"5m": 48, "15m": 32, "1h": 24, "4h": 18, "1d": 12}


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


def _spaced(
    pts: list[tuple[int, float]], gap: int
) -> list[tuple[int, float]]:
    if not pts:
        return []
    out = [pts[0]]
    for i, p in pts[1:]:
        if i - out[-1][0] >= gap:
            out.append((i, p))
        elif abs(p) >= abs(out[-1][1]):
            # keep the more extreme of a cluster
            out[-1] = (i, p)
    return out


def _closes_beyond(
    bars: list[OhlcBar],
    *,
    start_i: int,
    end_i: int,
    slope: float,
    intercept: float,
    side: str,
    buf: float,
) -> int:
    n = 0
    last = min(end_i, len(bars) - 1)
    for i in range(start_i, last + 1):
        line = _y(slope, intercept, i)
        if side == "low" and bars[i].close < line - buf:
            n += 1
        if side == "high" and bars[i].close > line + buf:
            n += 1
    return n


def _beyond_line(
    bar: OhlcBar, *, line: float, side: str, buf: float
) -> bool:
    if side == "low":
        return bar.close < line - buf
    return bar.close > line + buf


def _consecutive_break(
    bars: list[OhlcBar],
    *,
    start_i: int,
    end_i: int,
    slope: float,
    intercept: float,
    side: str,
    buf: float,
) -> bool:
    run = 0
    last = min(end_i, len(bars) - 2)
    for i in range(start_i, last + 1):
        line = _y(slope, intercept, i)
        hit = _beyond_line(bar=bars[i], line=line, side=side, buf=buf)
        run = run + 1 if hit else 0
        if run >= 2:
            return True
    return False


def _take_profit_px(
    entry_px: float, *, side: str, pct: float | None = None
) -> float:
    move = TAKE_PROFIT_PCT if pct is None else pct
    if side == "low":
        return entry_px * (1 + move)
    return entry_px * (1 - move)


def _take_profit_hit(
    bar: OhlcBar, *, side: str, entry_px: float, pct: float | None = None
) -> bool:
    target = _take_profit_px(entry_px, side=side, pct=pct)
    if side == "low":
        return bar.high >= target
    return bar.low <= target


def first_valid_break(
    bars: list[OhlcBar],
    *,
    from_i: int,
    window_offset: int,
    slope: float,
    intercept: float,
    side: str,
    buf: float,
    run_need: int = 2,
) -> int | None:
    """اولین کندلی که شکست معتبر را کامل می‌کند (دو کلوز متوالی آن‌طرف خط)."""
    run = 0
    start = max(0, from_i)
    for i in range(start, len(bars)):
        line = _y(slope, intercept, i - window_offset)
        hit = _beyond_line(bar=bars[i], line=line, side=side, buf=buf)
        run = run + 1 if hit else 0
        if run >= run_need:
            return i
    return None


def evaluate_trendline_path(
    bars: list[OhlcBar],
    idx: int,
    hit: PatternHit,
    *,
    take_profit_pct: float | None = None,
    timeframe: str = "15m",
) -> tuple[bool | None, str]:
    """ورود = سیگنال اولیه؛ خروج = سود هدف یا شکست معتبر (هرکدام زودتر)."""
    meta = hit.meta
    side = meta.get("side")
    if side == "low":
        slope, intercept = meta.get("lower_slope"), meta.get("lower_intercept")
    elif side == "high":
        slope, intercept = meta.get("upper_slope"), meta.get("upper_intercept")
    else:
        slope = intercept = None
    if slope is None or intercept is None or side not in ("low", "high"):
        return None, "خط ترندلاین برای ارزیابی مسیر ناقص است."

    wo = int(meta.get("window_offset") or 0)
    early = meta.get("early_index")
    confirm = meta.get("confirm_index")
    stage = meta.get("stage")
    if stage == "confirmed" and isinstance(confirm, int):
        entry_i = confirm
    elif isinstance(early, int):
        entry_i = early
    else:
        entry_i = idx
    entry_i = max(0, min(entry_i, idx, len(bars) - 1))
    if idx + 1 >= len(bars):
        return None, "کندل کافی بعد از سیگنال برای شکست معتبر نبود."

    atr_vals = atr(bars[: idx + 1])
    atr_now = next((v for v in reversed(atr_vals) if v is not None), None)
    if atr_now is None or atr_now <= 0:
        atr_now = max(abs(bars[idx].close) * 0.004, 1.0)
    buf = atr_now * 0.5

    entry_px = bars[entry_i].close
    if entry_px <= 0:
        return None, "قیمت ورود نامعتبر است."

    start = entry_i + 1
    if start >= len(bars):
        return None, "کندل کافی بعد از ورود برای ارزیابی نبود."

    tp_pct = TAKE_PROFIT_PCT if take_profit_pct is None else take_profit_pct
    tp_px = _take_profit_px(entry_px, side=side, pct=tp_pct)
    exit_i: int | None = None
    exit_px: float | None = None
    reason = ""
    break_run = 0
    if take_profit_pct is None or tp_pct == TAKE_PROFIT_PCT:
        tp_label = "۰.۵٪"
    else:
        tp_label = f"{tp_pct * 100:g}٪"
    max_fwd = PATH_EVAL_BARS.get(timeframe, 24)
    scan_end = min(len(bars), max(entry_i + 1 + max_fwd, idx + max_fwd))
    for i in range(start, scan_end):
        b = bars[i]
        if _take_profit_hit(b, side=side, entry_px=entry_px, pct=tp_pct):
            exit_i, exit_px, reason = i, tp_px, f"بستن در سود {tp_label}"
            break
        line = _y(float(slope), float(intercept), i - wo)
        hit = _beyond_line(bar=b, line=line, side=side, buf=buf)
        break_run = break_run + 1 if hit else 0
        if break_run >= 2:
            exit_i, exit_px, reason = i, b.close, "شکست معتبر"
            break

    if exit_i is None or exit_px is None:
        return (
            False,
            f"در {max_fwd} کندل بعد از ورود نه سود {tp_label} و نه شکست معتبر دیده شد.",
        )

    if side == "low":
        pct = (exit_px - entry_px) / entry_px
    else:
        pct = (entry_px - exit_px) / entry_px

    meta["entry_index"] = entry_i
    meta["exit_index"] = exit_i
    meta["path_pct"] = pct
    meta["exit_reason"] = reason
    meta["tp_px"] = tp_px
    ok = pct > 0
    note = (
        f"بازده مسیر سیگنال اولیه تا {reason}: {pct*100:+.2f}٪ "
        f"({entry_px:,.0f} → {exit_px:,.0f})"
    )
    return ok, note


def _deep_pierce(
    bars: list[OhlcBar],
    *,
    start_i: int,
    end_i: int,
    slope: float,
    intercept: float,
    side: str,
    atr_now: float,
) -> bool:
    """ویک یا کلوز خیلی آن‌طرف خط = خط باطل است (اسکرین ریزش زیر کانال)."""
    last = min(end_i, len(bars) - 1)
    wick_lim = atr_now * 1.15
    close_lim = atr_now * 0.85
    for i in range(start_i, last + 1):
        line = _y(slope, intercept, i)
        if side == "low":
            if bars[i].low < line - wick_lim or bars[i].close < line - close_lim:
                return True
        else:
            if bars[i].high > line + wick_lim or bars[i].close > line + close_lim:
                return True
    return False


def _fit_line(
    points: list[tuple[int, float]],
    bars: list[OhlcBar],
    *,
    side: str,
    atr_now: float,
    min_span: int,
    max_age: int,
    min_gap: int,
    classic_trend: bool = False,
) -> dict | None:
    pts = _spaced(points, min_gap)
    if len(pts) < 2:
        return None
    n = len(bars)
    last = bars[-1]
    tol = atr_now * 0.38
    break_buf = atr_now * 0.5
    best: dict | None = None
    # only consecutive swing windows — not every pair of last 8
    for length in (2, 3, 4):
        if len(pts) < length:
            continue
        for start in range(0, len(pts) - length + 1):
            window = pts[start : start + length]
            i0, p0 = window[0]
            i1, p1 = window[-1]
            if i1 - i0 < min_span:
                continue
            slope, intercept = _line_through(i0, p0, i1, p1)
            move = p1 - p0
            if abs(move) < atr_now * 0.45:
                continue
            if classic_trend:
                if side == "low" and move <= 0:
                    continue
                if side == "high" and move >= 0:
                    continue
            ok = True
            for i, p in window:
                if abs(p - _y(slope, intercept, i)) > tol:
                    ok = False
                    break
            if not ok:
                continue
            if _consecutive_break(
                bars,
                start_i=i0,
                end_i=n - 1,
                slope=slope,
                intercept=intercept,
                side=side,
                buf=break_buf,
            ):
                continue
            if _deep_pierce(
                bars,
                start_i=i0,
                end_i=n - 1,
                slope=slope,
                intercept=intercept,
                side=side,
                atr_now=atr_now,
            ):
                continue
            bars_n = max(1, (n - 1) - i0)
            outside = _closes_beyond(
                bars,
                start_i=i0,
                end_i=n - 1,
                slope=slope,
                intercept=intercept,
                side=side,
                buf=break_buf,
            )
            if outside / bars_n > 0.08:
                continue
            y_now = _y(slope, intercept, n - 1)
            dist = abs(last.close - y_now)
            if side == "low":
                testing = last.low <= y_now + tol and last.close >= y_now - break_buf
            else:
                testing = last.high >= y_now - tol and last.close <= y_now + break_buf
            last_age = n - 1 - i1
            near_lim = atr_now * (2.1 if length >= 3 else 1.35)
            near = dist <= near_lim or testing
            if last_age > max_age * (2 if length >= 3 else 1) and not near:
                continue
            if length == 2 and last_age > max_age and not testing:
                continue
            forming = last_age <= SWING_RIGHT
            stage = "confirmed" if length >= 3 and not forming else "early"
            score = length * 4.0 + (3.0 if testing else 0.0) + (2.0 if stage == "confirmed" else 0.0)
            score -= dist / max(atr_now, 1.0) * 0.25
            score -= outside / bars_n * 4.0
            cand = {
                "side": side,
                "slope": slope,
                "intercept": intercept,
                "touches": window,
                "start_i": i0,
                "end_i": i1,
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


def _prep(
    bars: list[OhlcBar], timeframe: str, *, classic_trend: bool = False
) -> tuple | None:
    if len(bars) < 50:
        return None
    win_n = WINDOW.get(timeframe, 120)
    window = bars[-win_n:] if len(bars) >= win_n else bars[:]
    n = len(window)
    highs = [b.high for b in window]
    lows = [b.low for b in window]
    swings = _price_swings(highs, lows)
    if len(swings) < 4:
        return None
    atr_vals = atr(window)
    atr_now = next((v for v in reversed(atr_vals) if v is not None), None)
    if atr_now is None or atr_now <= 0:
        return None
    lo_pts = [(i, p) for i, p, k in swings if k == "low"]
    hi_pts = [(i, p) for i, p, k in swings if k == "high"]
    kwargs = dict(
        atr_now=atr_now,
        min_span=MIN_SPAN.get(timeframe, 12),
        max_age=MAX_PIVOT_AGE.get(timeframe, 12),
        min_gap=MIN_TOUCH_GAP.get(timeframe, 5),
        classic_trend=classic_trend,
    )
    support = _fit_line(lo_pts, window, side="low", **kwargs)
    resist = _fit_line(hi_pts, window, side="high", **kwargs)
    return window, n, atr_now, support, resist, len(bars) - n


def _hit(
    *,
    category: str,
    timeframe: str,
    title: str,
    status: str,
    summary: str,
    forecast: str,
    pattern_id: str,
    meta: dict,
) -> PatternHit:
    return PatternHit(
        category=category,
        timeframe=timeframe,
        pattern_id=pattern_id,
        title_fa=title,
        status_fa=status,
        summary_fa=summary,
        forecast_fa=forecast,
        meta=meta,
    )


def detect_trendline(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    allow_early: bool = True,
) -> PatternHit | None:
    prep = _prep(bars, timeframe, classic_trend=True)
    if prep is None:
        return None
    window, n, atr_now, support, resist, wo = prep
    if support is None and resist is None:
        return None
    primary = (
        support
        if resist is None or (support and support["score"] >= resist["score"])
        else resist
    )
    if primary["stage"] == "early" and not allow_early:
        return None
    last = window[-1]
    n_pri = len(primary["touches"])
    if primary["side"] == "low":
        direction = "up"
        role = "حمایت"
        lower = (primary["slope"], primary["intercept"])
        upper = (None, None)
        touch_lows = [i for i, _ in primary["touches"]]
        touch_highs: list[int] = []
    else:
        direction = "down"
        role = "مقاومت"
        upper = (primary["slope"], primary["intercept"])
        lower = (None, None)
        touch_highs = [i for i, _ in primary["touches"]]
        touch_lows = []
    stage = primary["stage"]
    title = f"ترندلاین {role}"
    if stage == "early":
        status = "سیگنال اولیه"
        forecast = (
            f"خط با دو برخورد شناسایی شد. اگر قیمت نزدیک {primary['y_now']:,.0f} "
            f"نگه دارد، برخورد سوم تأیید می‌کند."
        )
    else:
        status = "تأییدشده"
        forecast = (
            f"خط با {n_pri} برخورد؛ واکنش روی {primary['y_now']:,.0f} "
            f"{'صعودی' if direction == 'up' else 'نزولی'} محتمل‌تر است. "
            f"بعد از ورود در سود ۰.۵٪ ببند."
        )
    summary = (
        f"{n_pri} برخورد روی خط {role}. "
        f"خط حدود {primary['y_now']:,.0f} — قیمت {last.close:,.0f}."
    )
    if primary.get("testing"):
        summary += " کندل جاری خط را لمس کرده."
    early_ix = wo + primary["touches"][min(1, n_pri - 1)][0]
    confirm_ix: int | None = None
    if stage == "confirmed":
        confirm_ix = wo + primary["touches"][-1][0]
    return _hit(
        category="trendline",
        timeframe=timeframe,
        title=title,
        status=status,
        summary=summary,
        forecast=forecast,
        pattern_id=f"trendline_{primary['side']}_{stage}",
        meta={
            "kind": "trendline",
            "stage": stage,
            "direction": direction,
            "side": primary["side"],
            "early_side": primary["side"],
            "upper_slope": upper[0],
            "upper_intercept": upper[1],
            "lower_slope": lower[0],
            "lower_intercept": lower[1],
            "start_i": primary["start_i"],
            "end_i": n - 1,
            "window_offset": wo,
            "touch_highs": touch_highs,
            "touch_lows": touch_lows,
            "y_now": primary["y_now"],
            "early_index": early_ix,
            "confirm_index": confirm_ix,
            "last_close": last.close,
        },
    )


def detect_channel(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    allow_early: bool = True,
) -> PatternHit | None:
    prep = _prep(bars, timeframe)
    if prep is None:
        return None
    window, n, atr_now, support, resist, wo = prep
    if support is None or resist is None:
        return None
    su, iu = resist["slope"], resist["intercept"]
    sl, il = support["slope"], support["intercept"]
    start_i = max(support["start_i"], resist["start_i"])
    end_i = min(support["end_i"], resist["end_i"])
    if end_i - start_i < MIN_SPAN.get(timeframe, 12):
        return None
    mag = max(abs(su), abs(sl), 1e-9)
    if abs(su - sl) / mag > 0.22:
        return None
    if su * sl < 0 and min(abs(su), abs(sl)) > atr_now * 0.008 / 20:
        return None
    end_draw = n - 1
    width = abs(_y(su, iu, end_draw) - _y(sl, il, end_draw))
    if width < atr_now * 1.4 or width > atr_now * 5.0:
        return None
    inside = 0
    total = 0
    buf = atr_now * 0.35
    pierce_lim = atr_now * 1.15
    for i in range(start_i, end_draw + 1):
        up = _y(su, iu, i)
        lo = _y(sl, il, i)
        if up < lo:
            up, lo = lo, up
        total += 1
        bar = window[i]
        if bar.low < lo - pierce_lim or bar.high > up + pierce_lim:
            return None
        if lo - buf <= bar.close <= up + buf:
            inside += 1
    if total == 0 or inside / total < 0.90:
        return None
    if _deep_pierce(
        window,
        start_i=start_i,
        end_i=end_draw,
        slope=sl,
        intercept=il,
        side="low",
        atr_now=atr_now,
    ) or _deep_pierce(
        window,
        start_i=start_i,
        end_i=end_draw,
        slope=su,
        intercept=iu,
        side="high",
        atr_now=atr_now,
    ):
        return None
    n_hi = len(resist["touches"])
    n_lo = len(support["touches"])
    if n_hi < 2 or n_lo < 2:
        return None
    forming = support["forming"] or resist["forming"]
    stage = "confirmed" if (n_hi >= 3 and n_lo >= 2) or (n_lo >= 3 and n_hi >= 2) else "early"
    if forming and n_hi < 3 and n_lo < 3:
        stage = "early"
    if stage == "early" and not allow_early:
        return None
    last = window[-1]
    slope = (su + sl) / 2.0
    if slope > atr_now * 0.015 / 20:
        title = "کانال صعودی"
        direction = "up"
    elif slope < -atr_now * 0.015 / 20:
        title = "کانال نزولی"
        direction = "down"
    else:
        title = "کانال افقی"
        direction = "up" if last.close >= (support["y_now"] + resist["y_now"]) / 2 else "down"
    if stage == "early":
        status = "سیگنال اولیه"
        forecast = "کانال تازه است؛ تا برخورد سوم روی یکی از اضلاع فقط محدودهٔ اولیه است."
    else:
        status = "تأییدشده"
        role = "حمایت" if support["dist"] <= resist["dist"] else "مقاومت"
        y = support["y_now"] if role == "حمایت" else resist["y_now"]
        forecast = f"حرکت داخل کانال؛ واکنش محتمل روی {role} نزدیک {y:,.0f}."
    summary = (
        f"{n_hi} برخورد سقف و {n_lo} برخورد کف. "
        f"عرض حدود {width:,.0f} دلار. قیمت {last.close:,.0f}."
    )
    lo2 = support["touches"][min(1, n_lo - 1)][0]
    hi2 = resist["touches"][min(1, n_hi - 1)][0]
    if lo2 <= hi2:
        early_ix = wo + lo2
        early_side = "low"
    else:
        early_ix = wo + hi2
        early_side = "high"
    return _hit(
        category="channel",
        timeframe=timeframe,
        title=title,
        status=status,
        summary=summary,
        forecast=forecast,
        pattern_id=f"channel_{direction}_{stage}",
        meta={
            "kind": "channel",
            "stage": stage,
            "direction": direction,
            "side": "low" if support["dist"] <= resist["dist"] else "high",
            "early_side": early_side,
            "upper_slope": su,
            "upper_intercept": iu,
            "lower_slope": sl,
            "lower_intercept": il,
            "start_i": start_i,
            "end_i": end_draw,
            "window_offset": wo,
            "touch_highs": [i for i, _ in resist["touches"] if i >= start_i],
            "touch_lows": [i for i, _ in support["touches"] if i >= start_i],
            "y_now": support["y_now"] if support["dist"] <= resist["dist"] else resist["y_now"],
            "early_index": early_ix,
            "last_close": last.close,
        },
    )
