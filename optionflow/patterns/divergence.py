from __future__ import annotations

from optionflow.patterns.indicators import (
    is_pivot_high,
    is_pivot_low,
    rsi,
    rsi_pivot_high_confirmations,
    rsi_pivot_low_confirmations,
)
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

# Trading Toolkit (BigBeluga) — Regular RSI divergence
RSI_PERIOD = 24
LOOKBACK_LEFT = 10
LOOKBACK_RIGHT = 10
EARLY_RIGHT = 2
RANGE_LOWER = 5
RANGE_UPPER = 60  # فاصله pivot متوالی (دوم ↔ سوم)
RANGE_UPPER_WIDE = 288  # pivot اول ↔ سوم روی 5m (~۲۴h)
ENTRY_LEG1_WEIGHT = 0.35
ENTRY_LEG2_WEIGHT = 0.65


def _in_range(p_a: int, p_b: int) -> bool:
    return RANGE_LOWER <= (p_b - p_a) <= RANGE_UPPER


def _gap_ok(p_a: int, p_c: int, *, adjacent: bool) -> bool:
    gap = p_c - p_a
    if gap < RANGE_LOWER:
        return False
    cap = RANGE_UPPER if adjacent else RANGE_UPPER_WIDE
    return gap <= cap


def _pivot_bars(pivots: list[tuple[int, int]], p_c: int) -> list[int]:
    return sorted({p for _, p in pivots if p < p_c})


def _compare_order(pivots: list[tuple[int, int]], p_c: int) -> list[int]:
    """با pivot سوم: اول pivot اول، بعد pivot قبلی (دوم)."""
    bars = _pivot_bars(pivots, p_c)
    if not bars:
        return []
    immediate = bars[-1]
    if len(bars) >= 2:
        first = bars[0]
        mid = list(reversed(bars[1:-1]))
        return [first, immediate] + mid
    return [immediate]


def _forming_after_last(
    rs: list[float | None],
    pivots: list[tuple[int, int]],
    *,
    high: bool,
    n: int,
) -> tuple[int, int] | None:
    """Pivot در حال شکل‌گیری بعد از آخرین pivot تأییدشده (مثلاً سوم)."""
    fp = _forming_pivot(rs, high=high, n=n)
    if fp is None or not pivots:
        return None
    p_f, _right = fp
    _, p_last = pivots[-1]
    if p_f <= p_last:
        return None
    return fp


def _recent_confirm(conf_b: int, n: int, right: int) -> bool:
    return conf_b >= n - right - 2


def _forming_pivot(
    values: list[float | None],
    *,
    high: bool,
    n: int,
) -> tuple[int, int] | None:
    for right in range(EARLY_RIGHT, LOOKBACK_RIGHT):
        p = n - 1 - right
        if p < LOOKBACK_LEFT:
            continue
        ok = (
            is_pivot_high(values, p, LOOKBACK_LEFT, right)
            if high
            else is_pivot_low(values, p, LOOKBACK_LEFT, right)
        )
        if ok:
            return p, right
    return None


def _bearish_ok(
    rs: list[float | None],
    highs: list[float],
    p_a: int,
    p_b: int,
) -> tuple[float, float] | None:
    ra, rb = rs[p_a], rs[p_b]
    if ra is None or rb is None:
        return None
    if rb >= ra:
        return None
    if highs[p_b] <= highs[p_a]:
        return None
    return float(ra), float(rb)


def _bullish_ok(
    rs: list[float | None],
    lows: list[float],
    p_a: int,
    p_b: int,
) -> tuple[float, float] | None:
    ra, rb = rs[p_a], rs[p_b]
    if ra is None or rb is None:
        return None
    if rb <= ra:
        return None
    if lows[p_b] >= lows[p_a]:
        return None
    return float(ra), float(rb)


def _best_bearish_pair(
    rs: list[float | None],
    highs: list[float],
    pivots: list[tuple[int, int]],
    p_c: int,
) -> tuple[int, int, float, float] | None:
    """آخرین pivot: اول با pivot قبلی، بعد pivot اول و بقیه."""
    prev_bar = None
    bars_before = _pivot_bars(pivots, p_c)
    if len(bars_before) >= 2:
        prev_bar = bars_before[-1]
    for p_a in _compare_order(pivots, p_c):
        adjacent = prev_bar is not None and p_a == prev_bar
        if not _gap_ok(p_a, p_c, adjacent=adjacent):
            continue
        pair = _bearish_ok(rs, highs, p_a, p_c)
        if pair:
            return p_a, p_c, pair[0], pair[1]
    return None


def _best_bullish_pair(
    rs: list[float | None],
    lows: list[float],
    pivots: list[tuple[int, int]],
    p_c: int,
) -> tuple[int, int, float, float] | None:
    prev_bar = None
    bars_before = _pivot_bars(pivots, p_c)
    if len(bars_before) >= 2:
        prev_bar = bars_before[-1]
    for p_a in _compare_order(pivots, p_c):
        adjacent = prev_bar is not None and p_a == prev_bar
        if not _gap_ok(p_a, p_c, adjacent=adjacent):
            continue
        pair = _bullish_ok(rs, lows, p_a, p_c)
        if pair:
            return p_a, p_c, pair[0], pair[1]
    return None


def _chronological_pivots(
    pivots: list[tuple[int, int]],
    p_c: int,
) -> list[int]:
    ps = sorted({p for _, p in pivots} | {p_c})
    return ps


def _entry_ladder(
    pivots: list[tuple[int, int]],
    p_c: int,
    prices: list[float],
) -> dict:
    """۳۵٪ روی pivot دوم؛ ۶۵٪ روی pivot سوم (در صورت وجود)."""
    ordered = _chronological_pivots(pivots, p_c)
    out: dict = {
        "entry_pivot_2_index": None,
        "entry_pivot_2_px": None,
        "entry_pivot_3_index": None,
        "entry_pivot_3_px": None,
        "entry_leg1_weight": ENTRY_LEG1_WEIGHT,
        "entry_leg2_weight": None,
        "entry_blended_px": None,
        "pivot_count": len(ordered),
    }
    if len(ordered) >= 3:
        p2, p3 = ordered[-2], ordered[-1]
        px2, px3 = prices[p2], prices[p3]
        out.update(
            {
                "entry_pivot_2_index": p2,
                "entry_pivot_2_px": px2,
                "entry_pivot_3_index": p3,
                "entry_pivot_3_px": px3,
                "entry_leg2_weight": ENTRY_LEG2_WEIGHT,
                "entry_blended_px": px2 * ENTRY_LEG1_WEIGHT + px3 * ENTRY_LEG2_WEIGHT,
            }
        )
        return out
    if len(ordered) >= 2:
        p2 = ordered[-1]
        px2 = prices[p2]
        out.update(
            {
                "entry_pivot_2_index": p2,
                "entry_pivot_2_px": px2,
                "entry_blended_px": px2,
            }
        )
    return out


def _bar_close(bars: list[OhlcBar], idx: int) -> float | None:
    if idx < 0 or idx >= len(bars):
        return None
    return float(bars[idx].close)


def _price_txt(px: float | None) -> str:
    if px is None:
        return "—"
    return f"{px:,.0f}"


def _entry_lines(
    bars: list[OhlcBar],
    p_b: int,
    *,
    early: bool,
    ladder: dict,
) -> tuple[int, int | None, float | None, float | None, str]:
    early_ix = p_b + EARLY_RIGHT
    final_ix = p_b + LOOKBACK_RIGHT
    early_px = _bar_close(bars, early_ix)
    final_px = None if early else _bar_close(bars, final_ix)
    px2 = ladder.get("entry_pivot_2_px")
    px3 = ladder.get("entry_pivot_3_px")
    if ladder.get("entry_pivot_3_px") is not None:
        ladder_txt = (
            f"ورود پله‌ای: {int(ENTRY_LEG1_WEIGHT * 100)}٪ در pivot دوم "
            f"({_price_txt(px2)}) و {int(ENTRY_LEG2_WEIGHT * 100)}٪ در pivot سوم "
            f"({_price_txt(px3)})."
        )
    elif px2 is not None:
        ladder_txt = (
            f"ورود {int(ENTRY_LEG1_WEIGHT * 100)}٪ در pivot دوم ({_price_txt(px2)})؛ "
            "pivot سوم هنوز نیست."
        )
    else:
        ladder_txt = ""
    if early:
        extra = (
            f"تأیید اولیه در قیمت {_price_txt(early_px)}؛ "
            f"منتظر pivot RSI {LOOKBACK_LEFT}/{LOOKBACK_RIGHT}. {ladder_txt}"
        )
        return early_ix, None, early_px, None, extra
    extra = (
        f"تأیید نهایی در {_price_txt(final_px)}. {ladder_txt}"
    )
    return early_ix, final_ix, early_px, final_px, extra


def _hit_bearish(
    bars: list[OhlcBar],
    timeframe: str,
    p_a: int,
    p_c: int,
    highs: list[float],
    ra: float,
    rb: float,
    confirm_index: int,
    pivots: list[tuple[int, int]],
    *,
    early: bool,
) -> PatternHit:
    diff = ra - rb
    delay = EARLY_RIGHT if early else LOOKBACK_RIGHT
    status = "سیگنال اولیه" if early else "تأییدشده"
    ladder = _entry_ladder(pivots, p_c, highs)
    early_ix, final_ix, early_px, final_px, extra = _entry_lines(
        bars, p_c, early=early, ladder=ladder
    )
    ref_note = ""
    ordered = _chronological_pivots(pivots, p_c)
    if len(ordered) >= 3 and p_a == ordered[0] and p_c == ordered[-1]:
        ref_note = " (مقایسه pivot اول و سوم)"
    extra_meta: dict = {}
    if len(ordered) >= 3:
        p_mid = ordered[-2]
        extra_meta["pivot_mid"] = (p_mid, highs[p_mid])
        extra_meta["pivot_sequence"] = [(i, highs[i]) for i in ordered]
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id=f"rsi_bearish_{p_a}_{p_c}",
        title_fa="واگرایی نزولی RSI",
        status_fa=status,
        summary_fa=(
            f"Regular Bearish (BigBeluga){ref_note} · "
            f"قیمت HH ({highs[p_c]:,.0f} > {highs[p_a]:,.0f})، "
            f"RSI LH ({rb:.1f} < {ra:.1f}، Δ{diff:.1f}). {extra}"
        ),
        forecast_fa=(
            "احتمال اصلاح نزولی؛ تأیید با شکست کف کوتاه‌مدت."
            if not early
            else "سقف RSI در حال شکل‌گیری است؛ pivot سوم با pivotهای قبل هم چک می‌شود."
        ),
        meta={
            "pivot_a": (p_a, highs[p_a]),
            "pivot_b": (p_c, highs[p_c]),
            "rsi_a": ra,
            "rsi_b": rb,
            "direction": "down",
            "confirm_index": confirm_index,
            "early_index": early_ix,
            "final_index": final_ix,
            "early_price": early_px,
            "final_price": final_px,
            "tv_pivot": True,
            "stage": "early" if early else "confirmed",
            "delay_bars": delay,
            "rsi_period": RSI_PERIOD,
            "lookback": LOOKBACK_LEFT,
            **ladder,
            **extra_meta,
        },
    )


def _hit_bullish(
    bars: list[OhlcBar],
    timeframe: str,
    p_a: int,
    p_c: int,
    lows: list[float],
    ra: float,
    rb: float,
    confirm_index: int,
    pivots: list[tuple[int, int]],
    *,
    early: bool,
) -> PatternHit:
    diff = rb - ra
    delay = EARLY_RIGHT if early else LOOKBACK_RIGHT
    status = "سیگنال اولیه" if early else "تأییدشده"
    ladder = _entry_ladder(pivots, p_c, lows)
    early_ix, final_ix, early_px, final_px, extra = _entry_lines(
        bars, p_c, early=early, ladder=ladder
    )
    ref_note = ""
    ordered = _chronological_pivots(pivots, p_c)
    if len(ordered) >= 3 and p_a == ordered[0] and p_c == ordered[-1]:
        ref_note = " (مقایسه pivot اول و سوم)"
    extra_meta: dict = {}
    if len(ordered) >= 3:
        p_mid = ordered[-2]
        extra_meta["pivot_mid"] = (p_mid, lows[p_mid])
        extra_meta["pivot_sequence"] = [(i, lows[i]) for i in ordered]
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id=f"rsi_bullish_{p_a}_{p_c}",
        title_fa="واگرایی مثبت RSI",
        status_fa=status,
        summary_fa=(
            f"Regular Bullish (BigBeluga){ref_note} · "
            f"قیمت LL ({lows[p_c]:,.0f} < {lows[p_a]:,.0f})، "
            f"RSI HL ({rb:.1f} > {ra:.1f}، Δ{diff:.1f}). {extra}"
        ),
        forecast_fa=(
            "احتمال اصلاح صعودی؛ تأیید با شکست سقف کوتاه‌مدت."
            if not early
            else "کف RSI در حال شکل‌گیری است؛ pivot سوم با pivotهای قبل هم چک می‌شود."
        ),
        meta={
            "pivot_a": (p_a, lows[p_a]),
            "pivot_b": (p_c, lows[p_c]),
            "rsi_a": ra,
            "rsi_b": rb,
            "direction": "up",
            "confirm_index": confirm_index,
            "early_index": early_ix,
            "final_index": final_ix,
            "early_price": early_px,
            "final_price": final_px,
            "tv_pivot": True,
            "stage": "early" if early else "confirmed",
            "delay_bars": delay,
            "rsi_period": RSI_PERIOD,
            "lookback": LOOKBACK_LEFT,
            **ladder,
            **extra_meta,
        },
    )


def _try_bearish(
    bars: list[OhlcBar],
    timeframe: str,
    rs: list[float | None],
    highs: list[float],
    pivots: list[tuple[int, int]],
    p_c: int,
    confirm_index: int,
    *,
    early: bool,
) -> PatternHit | None:
    found = _best_bearish_pair(rs, highs, pivots, p_c)
    if not found:
        return None
    p_a, _pc, ra, rb = found
    return _hit_bearish(
        bars,
        timeframe,
        p_a,
        p_c,
        highs,
        ra,
        rb,
        confirm_index,
        pivots,
        early=early,
    )


def _try_bullish(
    bars: list[OhlcBar],
    timeframe: str,
    rs: list[float | None],
    lows: list[float],
    pivots: list[tuple[int, int]],
    p_c: int,
    confirm_index: int,
    *,
    early: bool,
) -> PatternHit | None:
    found = _best_bullish_pair(rs, lows, pivots, p_c)
    if not found:
        return None
    p_a, _pc, ra, rb = found
    return _hit_bullish(
        bars,
        timeframe,
        p_a,
        p_c,
        lows,
        ra,
        rb,
        confirm_index,
        pivots,
        early=early,
    )


def detect_rsi_divergence(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    allow_early: bool = True,
) -> PatternHit | None:
    min_len = LOOKBACK_LEFT + LOOKBACK_RIGHT + RANGE_UPPER + RSI_PERIOD + 20
    if len(bars) < min_len:
        return None

    closes = [b.close for b in bars]
    rs = rsi(closes, RSI_PERIOD)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    n = len(bars)

    ph = rsi_pivot_high_confirmations(
        rs, left=LOOKBACK_LEFT, right=LOOKBACK_RIGHT
    )
    pl = rsi_pivot_low_confirmations(
        rs, left=LOOKBACK_LEFT, right=LOOKBACK_RIGHT
    )

    if allow_early:
        forming_bear = _forming_after_last(rs, ph, high=True, n=n)
        if forming_bear:
            p_c, right = forming_bear
            hit = _try_bearish(
                bars,
                timeframe,
                rs,
                highs,
                ph,
                p_c,
                p_c + right,
                early=True,
            )
            if hit:
                return hit
        forming_bull = _forming_after_last(rs, pl, high=False, n=n)
        if forming_bull:
            p_c, right = forming_bull
            hit = _try_bullish(
                bars,
                timeframe,
                rs,
                lows,
                pl,
                p_c,
                p_c + right,
                early=True,
            )
            if hit:
                return hit

    if len(ph) >= 2:
        conf_c, p_c = ph[-1]
        if _recent_confirm(conf_c, n, LOOKBACK_RIGHT):
            hit = _try_bearish(
                bars,
                timeframe,
                rs,
                highs,
                ph,
                p_c,
                conf_c,
                early=False,
            )
            if hit:
                return hit

    if len(pl) >= 2:
        conf_c, p_c = pl[-1]
        if _recent_confirm(conf_c, n, LOOKBACK_RIGHT):
            hit = _try_bullish(
                bars,
                timeframe,
                rs,
                lows,
                pl,
                p_c,
                conf_c,
                early=False,
            )
            if hit:
                return hit

    return None
