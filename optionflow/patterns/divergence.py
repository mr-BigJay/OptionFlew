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
EARLY_RIGHT = 2  # تأیید اولیه قبل از pivot کامل ۱۰/۱۰
RANGE_LOWER = 5
RANGE_UPPER = 60
RANGE_P1_P3 = RANGE_UPPER * 2
ENTRY_LEG1_WEIGHT = 0.35
ENTRY_LEG2_WEIGHT = 0.65


def _in_range(p_a: int, p_b: int) -> bool:
    return RANGE_LOWER <= (p_b - p_a) <= RANGE_UPPER


def _recent_confirm(conf_b: int, n: int, right: int) -> bool:
    return conf_b >= n - right - 2


def _forming_pivot(
    values: list[float | None],
    *,
    high: bool,
    n: int,
) -> tuple[int, int] | None:
    """سقف/کف RSI در حال شکل‌گیری: ۲ تا ۹ کندل راست (قبل از تأیید ۱۰)."""
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


def _ladder_merge(p2: int, p3: int, prices: list[float]) -> dict:
    px2, px3 = float(prices[p2]), float(prices[p3])
    return {
        "entry_pivot_2_index": p2,
        "entry_pivot_2_px": px2,
        "entry_pivot_3_index": p3,
        "entry_pivot_3_px": px3,
        "entry_leg1_weight": ENTRY_LEG1_WEIGHT,
        "entry_leg2_weight": ENTRY_LEG2_WEIGHT,
        "entry_blended_px": px2 * ENTRY_LEG1_WEIGHT + px3 * ENTRY_LEG2_WEIGHT,
    }


def pick_confirmed_divergence(
    pivots: list[tuple[int, int]],
    rs: list[float | None],
    prices: list[float],
    ok_fn,
) -> dict | None:
    """BigBeluga: دو پیوت آخر؛ فقط اگر ۲↔۳ واگرایی نداشت، ۱↔۳ + پله ۳۵/۶۵."""
    if len(pivots) < 2:
        return None
    p2, p3 = pivots[-2][1], pivots[-1][1]
    if not _in_range(p2, p3):
        return None

    consec = ok_fn(rs, prices, p2, p3)
    if consec:
        ra, rb = consec
        return {
            "p_a": p2,
            "p_c": p3,
            "ra": ra,
            "rb": rb,
            "p_mid": None,
            "ladder": {},
        }

    if len(pivots) < 3:
        return None
    p1 = pivots[-3][1]
    if not (_in_range(p1, p2) and _in_range(p2, p3) and (p3 - p1) <= RANGE_P1_P3):
        return None
    merged = ok_fn(rs, prices, p1, p3)
    if not merged:
        return None
    ra, rb = merged
    return {
        "p_a": p1,
        "p_c": p3,
        "ra": ra,
        "rb": rb,
        "p_mid": p2,
        "ladder": _ladder_merge(p2, p3, prices),
    }


def divergence_signal_key(hit: PatternHit) -> str | None:
    pb = hit.meta.get("pivot_b")
    if not isinstance(pb, (list, tuple)) or not pb:
        return None
    try:
        return f"{hit.pattern_id}:{int(pb[0])}"
    except (TypeError, ValueError):
        return None


def divergence_rank(hit: PatternHit) -> int:
    stage = hit.meta.get("stage")
    rank = 10 if stage == "early" else 20 if stage == "confirmed" else 0
    if hit.meta.get("compared_first_third"):
        rank += 5
    return rank


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
    ladder: dict | None = None,
) -> tuple[int, int | None, float | None, float | None, str]:
    early_ix = p_b + EARLY_RIGHT
    final_ix = p_b + LOOKBACK_RIGHT
    early_px = _bar_close(bars, early_ix)
    final_px = None if early else _bar_close(bars, final_ix)
    ladder = ladder or {}
    ladder_txt = ""
    if ladder.get("entry_pivot_3_px") is not None:
        ladder_txt = (
            f" ورود پله‌ای: {int(ENTRY_LEG1_WEIGHT * 100)}٪ در پیوت دوم "
            f"({_price_txt(ladder.get('entry_pivot_2_px'))}) و "
            f"{int(ENTRY_LEG2_WEIGHT * 100)}٪ در پیوت سوم "
            f"({_price_txt(ladder.get('entry_pivot_3_px'))})."
        )
    if early:
        extra = (
            f"تأیید اولیه در قیمت {_price_txt(early_px)}؛ "
            f"منتظر pivot RSI {LOOKBACK_LEFT}/{LOOKBACK_RIGHT} (حدود "
            f"{LOOKBACK_RIGHT - EARLY_RIGHT} کندل).{ladder_txt}"
        )
        return early_ix, None, early_px, None, extra
    extra = (
        f"تأیید اولیه در قیمت {_price_txt(early_px)}، "
        f"تأیید نهایی (BigBeluga) در قیمت {_price_txt(final_px)}.{ladder_txt}"
    )
    return early_ix, final_ix, early_px, final_px, extra


def _hit_bearish(
    bars: list[OhlcBar],
    timeframe: str,
    p_a: int,
    p_b: int,
    highs: list[float],
    ra: float,
    rb: float,
    confirm_index: int,
    *,
    early: bool,
    p_mid: int | None = None,
    ladder: dict | None = None,
) -> PatternHit:
    diff = ra - rb
    delay = EARLY_RIGHT if early else LOOKBACK_RIGHT
    status = "سیگنال اولیه" if early else "تأییدشده"
    ladder = ladder or {}
    early_ix, final_ix, early_px, final_px, extra = _entry_lines(
        bars, p_b, early=early, ladder=ladder
    )
    ref = " مقایسه پیوت اول↔سوم؛ ادغام با پیوت دوم." if p_mid is not None else ""
    extra_meta: dict = dict(ladder)
    if p_mid is not None:
        extra_meta["pivot_mid"] = (p_mid, highs[p_mid])
        extra_meta["compared_first_third"] = True
    extra_meta["signal_key"] = f"rsi_bearish:{p_b}"
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bearish",
        title_fa="واگرایی نزولی RSI",
        status_fa=status,
        summary_fa=(
            f"Regular Bearish (BigBeluga) · "
            f"قیمت HH ({highs[p_b]:,.0f} > {highs[p_a]:,.0f})، "
            f"RSI LH ({rb:.1f} < {ra:.1f}، Δ{diff:.1f}).{ref} {extra}"
        ),
        forecast_fa=(
            "احتمال اصلاح نزولی؛ تأیید با شکست کف کوتاه‌مدت."
            if not early
            else "سقف RSI در حال شکل‌گیری است؛ اگر ۲ کندل راست pivot را تأیید کند، "
            "واگرایی نزولی مثل TradingView ثبت می‌شود."
        ),
        meta={
            "pivot_a": (p_a, highs[p_a]),
            "pivot_b": (p_b, highs[p_b]),
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
            **extra_meta,
        },
    )


def _hit_bullish(
    bars: list[OhlcBar],
    timeframe: str,
    p_a: int,
    p_b: int,
    lows: list[float],
    ra: float,
    rb: float,
    confirm_index: int,
    *,
    early: bool,
    p_mid: int | None = None,
    ladder: dict | None = None,
) -> PatternHit:
    diff = rb - ra
    delay = EARLY_RIGHT if early else LOOKBACK_RIGHT
    status = "سیگنال اولیه" if early else "تأییدشده"
    ladder = ladder or {}
    early_ix, final_ix, early_px, final_px, extra = _entry_lines(
        bars, p_b, early=early, ladder=ladder
    )
    ref = " مقایسه پیوت اول↔سوم؛ ادغام با پیوت دوم." if p_mid is not None else ""
    extra_meta: dict = dict(ladder)
    if p_mid is not None:
        extra_meta["pivot_mid"] = (p_mid, lows[p_mid])
        extra_meta["compared_first_third"] = True
    extra_meta["signal_key"] = f"rsi_bullish:{p_b}"
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bullish",
        title_fa="واگرایی مثبت RSI",
        status_fa=status,
        summary_fa=(
            f"Regular Bullish (BigBeluga) · "
            f"قیمت LL ({lows[p_b]:,.0f} < {lows[p_a]:,.0f})، "
            f"RSI HL ({rb:.1f} > {ra:.1f}، Δ{diff:.1f}).{ref} {extra}"
        ),
        forecast_fa=(
            "احتمال اصلاح صعودی؛ تأیید با شکست سقف کوتاه‌مدت."
            if not early
            else "کف RSI در حال شکل‌گیری است؛ اگر ۲ کندل راست pivot را تأیید کند، "
            "واگرایی مثبت مثل TradingView ثبت می‌شود."
        ),
        meta={
            "pivot_a": (p_a, lows[p_a]),
            "pivot_b": (p_b, lows[p_b]),
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
            **extra_meta,
        },
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

    if len(ph) >= 2:
        conf_b, p_b = ph[-1]
        if _recent_confirm(conf_b, n, LOOKBACK_RIGHT):
            picked = pick_confirmed_divergence(ph, rs, highs, _bearish_ok)
            if picked:
                return _hit_bearish(
                    bars,
                    timeframe,
                    picked["p_a"],
                    picked["p_c"],
                    highs,
                    picked["ra"],
                    picked["rb"],
                    conf_b,
                    early=False,
                    p_mid=picked["p_mid"],
                    ladder=picked["ladder"],
                )

    if len(pl) >= 2:
        conf_b, p_b = pl[-1]
        if _recent_confirm(conf_b, n, LOOKBACK_RIGHT):
            picked = pick_confirmed_divergence(pl, rs, lows, _bullish_ok)
            if picked:
                return _hit_bullish(
                    bars,
                    timeframe,
                    picked["p_a"],
                    picked["p_c"],
                    lows,
                    picked["ra"],
                    picked["rb"],
                    conf_b,
                    early=False,
                    p_mid=picked["p_mid"],
                    ladder=picked["ladder"],
                )

    if not allow_early:
        return None

    forming_h = _forming_pivot(rs, high=True, n=n)
    if forming_h and ph:
        p_b, right = forming_h
        _, p_last = ph[-1]
        if p_last < p_b and _in_range(p_last, p_b):
            pair = _bearish_ok(rs, highs, p_last, p_b)
            if pair:
                ra, rb = pair
                return _hit_bearish(
                    bars,
                    timeframe,
                    p_last,
                    p_b,
                    highs,
                    ra,
                    rb,
                    p_b + right,
                    early=True,
                )

    forming_l = _forming_pivot(rs, high=False, n=n)
    if forming_l and pl:
        p_b, right = forming_l
        _, p_last = pl[-1]
        if p_last < p_b and _in_range(p_last, p_b):
            pair = _bullish_ok(rs, lows, p_last, p_b)
            if pair:
                ra, rb = pair
                return _hit_bullish(
                    bars,
                    timeframe,
                    p_last,
                    p_b,
                    lows,
                    ra,
                    rb,
                    p_b + right,
                    early=True,
                )

    return None
