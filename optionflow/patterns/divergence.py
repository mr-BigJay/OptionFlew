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

# BigBeluga Trading Toolkit — Regular RSI divergence (Pine) + تأیید اولیه ۱ کندل
RSI_PERIOD = 24
LOOKBACK_LEFT = 10
LOOKBACK_RIGHT = 10
EARLY_RIGHT = 1
RANGE_LOWER = 5
RANGE_UPPER = 60


def _in_range(p_a: int, p_b: int) -> bool:
    return RANGE_LOWER <= (p_b - p_a) <= RANGE_UPPER


def _recent_confirm(conf_b: int, n: int, right: int) -> bool:
    """سیگنال تأییدشده هنوز تازه است (چند کندل بعد از pivot 10/10)."""
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
) -> tuple[int, int | None, float | None, float | None, str]:
    early_ix = p_b + EARLY_RIGHT
    final_ix = p_b + LOOKBACK_RIGHT
    early_px = _bar_close(bars, early_ix)
    final_px = None if early else _bar_close(bars, final_ix)
    if early:
        extra = (
            f"تأیید اولیه در قیمت {_price_txt(early_px)}؛ "
            f"منتظر pivot RSI {LOOKBACK_LEFT}/{LOOKBACK_RIGHT} "
            f"(یک کندل بعد از سقف/کف)."
        )
        return early_ix, None, early_px, None, extra
    extra = (
        f"تأیید اولیه در قیمت {_price_txt(early_px)}، "
        f"تأیید نهایی (BigBeluga) در قیمت {_price_txt(final_px)}."
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
) -> PatternHit:
    diff = ra - rb
    status = "سیگنال اولیه" if early else "تأییدشده"
    early_ix, final_ix, early_px, final_px, extra = _entry_lines(
        bars, p_b, early=early
    )
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bearish",
        title_fa="واگرایی نزولی RSI",
        status_fa=status,
        summary_fa=(
            f"Regular Bearish (BigBeluga) · "
            f"قیمت HH ({highs[p_b]:,.0f} > {highs[p_a]:,.0f})، "
            f"RSI LH ({rb:.1f} < {ra:.1f}، Δ{diff:.1f}). {extra}"
        ),
        forecast_fa=(
            "احتمال اصلاح نزولی؛ تأیید با شکست کف کوتاه‌مدت."
            if not early
            else "سقف RSI در حال شکل‌گیری؛ با یک کندل راست تأیید می‌شود."
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
            "stage": "early" if early else "confirmed",
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
) -> PatternHit:
    diff = rb - ra
    status = "سیگنال اولیه" if early else "تأییدشده"
    early_ix, final_ix, early_px, final_px, extra = _entry_lines(
        bars, p_b, early=early
    )
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bullish",
        title_fa="واگرایی مثبت RSI",
        status_fa=status,
        summary_fa=(
            f"Regular Bullish (BigBeluga) · "
            f"قیمت LL ({lows[p_b]:,.0f} < {lows[p_a]:,.0f})، "
            f"RSI HL ({rb:.1f} > {ra:.1f}، Δ{diff:.1f}). {extra}"
        ),
        forecast_fa=(
            "احتمال اصلاح صعودی؛ تأیید با شکست سقف کوتاه‌مدت."
            if not early
            else "کف RSI در حال شکل‌گیری؛ با یک کندل راست تأیید می‌شود."
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
            "stage": "early" if early else "confirmed",
        },
    )


def detect_rsi_divergence(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    allow_early: bool = True,
    early_only: bool = False,
    rs: list[float | None] | None = None,
) -> PatternHit | None:
    min_len = LOOKBACK_LEFT + LOOKBACK_RIGHT + RANGE_UPPER + RSI_PERIOD + 20
    if len(bars) < min_len:
        return None

    closes = [b.close for b in bars]
    if rs is None:
        rs = rsi(closes, RSI_PERIOD)
    elif len(rs) < len(bars):
        rs = rsi(closes, RSI_PERIOD)
    else:
        rs = rs[: len(bars)]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    n = len(bars)

    ph = rsi_pivot_high_confirmations(
        rs, left=LOOKBACK_LEFT, right=LOOKBACK_RIGHT
    )
    pl = rsi_pivot_low_confirmations(
        rs, left=LOOKBACK_LEFT, right=LOOKBACK_RIGHT
    )

    if not early_only and len(ph) >= 2:
        conf_b, p_b = ph[-1]
        if _recent_confirm(conf_b, n, LOOKBACK_RIGHT):
            _, p_a = ph[-2]
            if _in_range(p_a, p_b):
                pair = _bearish_ok(rs, highs, p_a, p_b)
                if pair:
                    ra, rb = pair
                    return _hit_bearish(
                        bars,
                        timeframe,
                        p_a,
                        p_b,
                        highs,
                        ra,
                        rb,
                        conf_b,
                        early=False,
                    )

    if not early_only and len(pl) >= 2:
        conf_b, p_b = pl[-1]
        if _recent_confirm(conf_b, n, LOOKBACK_RIGHT):
            _, p_a = pl[-2]
            if _in_range(p_a, p_b):
                pair = _bullish_ok(rs, lows, p_a, p_b)
                if pair:
                    ra, rb = pair
                    return _hit_bullish(
                        bars,
                        timeframe,
                        p_a,
                        p_b,
                        lows,
                        ra,
                        rb,
                        conf_b,
                        early=False,
                    )

    if not allow_early:
        return None

    forming_h = _forming_pivot(rs, high=True, n=n)
    if forming_h and ph:
        p_b, right = forming_h
        _, p_a = ph[-1]
        if p_a < p_b and _in_range(p_a, p_b):
            pair = _bearish_ok(rs, highs, p_a, p_b)
            if pair:
                ra, rb = pair
                return _hit_bearish(
                    bars,
                    timeframe,
                    p_a,
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
        _, p_a = pl[-1]
        if p_a < p_b and _in_range(p_a, p_b):
            pair = _bullish_ok(rs, lows, p_a, p_b)
            if pair:
                ra, rb = pair
                return _hit_bullish(
                    bars,
                    timeframe,
                    p_a,
                    p_b,
                    lows,
                    ra,
                    rb,
                    p_b + right,
                    early=True,
                )

    return None
