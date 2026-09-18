from __future__ import annotations

from optionflow.patterns.indicators import (
    rsi,
    rsi_pivot_high_confirmations,
    rsi_pivot_low_confirmations,
)
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

# ساختار pivot روی RSI (چپ مثل TV؛ راست کوتاه‌تر = تأیید زودتر)
LOOKBACK_LEFT = 5
PIVOT_RIGHT = 1
RANGE_LOWER = 5
RANGE_UPPER = 60


def _in_range(anchor_p: int, pivot_p: int) -> bool:
    return RANGE_LOWER <= (pivot_p - anchor_p) <= RANGE_UPPER


def _bearish_reversal_candle(bar: OhlcBar) -> bool:
    return bar.close < bar.open


def _bullish_reversal_candle(bar: OhlcBar) -> bool:
    return bar.close > bar.open


def _pick_anchor_pivot(
    pivot_indices: list[int], latest_p: int
) -> int | None:
    """اولین (قدیمی‌ترین) pivot در بازه — برای سقف/کف سوم نسبت به اول."""
    valid = [p for p in pivot_indices if p < latest_p and _in_range(p, latest_p)]
    if not valid:
        return None
    return min(valid)


def _try_bearish(
    bars: list[OhlcBar],
    rs: list[float | None],
    highs: list[float],
    ph: list[tuple[int, int]],
    timeframe: str,
) -> PatternHit | None:
    n = len(bars)
    if len(ph) < 2:
        return None

    _, p_b = ph[-1]
    sig = p_b + PIVOT_RIGHT  # همان کندل تأیید pivot (right=1) + ورود اگر خلاف جهت بسته شد
    if sig >= n or sig != n - 1:
        return None

    if not _bearish_reversal_candle(bars[sig]):
        return None

    pivot_indices = [p for _, p in ph if p <= p_b]
    p_a = _pick_anchor_pivot(pivot_indices, p_b)
    if p_a is None:
        return None

    ra, rb = rs[p_a], rs[p_b]
    if ra is None or rb is None or rb >= ra:
        return None
    if highs[p_b] <= highs[p_a]:
        return None

    peaks_between = len([p for p in pivot_indices if p_a < p < p_b]) + 1
    peak_label = f"{peaks_between} سقف" if peaks_between >= 2 else "۲ سقف"

    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bearish",
        title_fa="واگرایی نزولی RSI",
        status_fa="سیگنال اولیه",
        summary_fa=(
            f"Regular Bearish · {peak_label} — سقف قیمت بالاتر از اول "
            f"({highs[p_b]:,.0f} > {highs[p_a]:,.0f})، "
            f"RSI سقف پایین‌تر ({rb:.1f} < {ra:.1f}). "
            f"ورود با بسته شدن کندل نزولی بلافاصله بعد از pivot."
        ),
        forecast_fa=(
            "پیش‌بینی: احتمال اصلاح نزولی؛ تأیید با شکست کف کوتاه‌مدت."
        ),
        meta={
            "pivot_a": (p_a, highs[p_a]),
            "pivot_b": (p_b, highs[p_b]),
            "rsi_a": ra,
            "rsi_b": rb,
            "direction": "down",
            "confirm_index": sig,
            "pivot_index": p_b,
            "anchor_first": True,
        },
    )


def _try_bullish(
    bars: list[OhlcBar],
    rs: list[float | None],
    lows: list[float],
    pl: list[tuple[int, int]],
    timeframe: str,
) -> PatternHit | None:
    n = len(bars)
    if len(pl) < 2:
        return None

    _, p_b = pl[-1]
    sig = p_b + PIVOT_RIGHT
    if sig >= n or sig != n - 1:
        return None

    if not _bullish_reversal_candle(bars[sig]):
        return None

    pivot_indices = [p for _, p in pl if p <= p_b]
    p_a = _pick_anchor_pivot(pivot_indices, p_b)
    if p_a is None:
        return None

    ra, rb = rs[p_a], rs[p_b]
    if ra is None or rb is None or rb <= ra:
        return None
    if lows[p_b] >= lows[p_a]:
        return None

    troughs_between = len([p for p in pivot_indices if p_a < p < p_b]) + 1
    trough_label = f"{troughs_between} کف" if troughs_between >= 2 else "۲ کف"

    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bullish",
        title_fa="واگرایی مثبت RSI",
        status_fa="سیگنال اولیه",
        summary_fa=(
            f"Regular Bullish · {trough_label} — کف قیمت پایین‌تر از اول "
            f"({lows[p_b]:,.0f} < {lows[p_a]:,.0f})، "
            f"RSI کف بالاتر ({rb:.1f} > {ra:.1f}). "
            f"ورود: بسته شدن صعودی کندل بعد از pivot."
        ),
        forecast_fa=(
            "پیش‌بینی: احتمال اصلاح صعودی؛ تأیید با شکست سقف کوتاه‌مدت."
        ),
        meta={
            "pivot_a": (p_a, lows[p_a]),
            "pivot_b": (p_b, lows[p_b]),
            "rsi_a": ra,
            "rsi_b": rb,
            "direction": "up",
            "confirm_index": sig,
            "pivot_index": p_b,
            "anchor_first": True,
        },
    )


def detect_rsi_divergence(bars: list[OhlcBar], timeframe: str) -> PatternHit | None:
    min_len = LOOKBACK_LEFT + PIVOT_RIGHT + RANGE_UPPER + 25
    if len(bars) < min_len:
        return None

    closes = [b.close for b in bars]
    rs = rsi(closes)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]

    ph = rsi_pivot_high_confirmations(rs, left=LOOKBACK_LEFT, right=PIVOT_RIGHT)
    pl = rsi_pivot_low_confirmations(rs, left=LOOKBACK_LEFT, right=PIVOT_RIGHT)

    bear = _try_bearish(bars, rs, highs, ph, timeframe)
    if bear is not None:
        return bear
    return _try_bullish(bars, rs, lows, pl, timeframe)
