from __future__ import annotations

from optionflow.patterns.indicators import (
    rsi,
    rsi_pivot_high_confirmations,
    rsi_pivot_low_confirmations,
)
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

# BigBeluga Trading Toolkit — Regular RSI divergence (Pine source only)
RSI_PERIOD = 24
LOOKBACK_LEFT = 10
LOOKBACK_RIGHT = 10
RANGE_LOWER = 5
RANGE_UPPER = 60


def _in_range(p_a: int, p_b: int) -> bool:
    return RANGE_LOWER <= (p_b - p_a) <= RANGE_UPPER


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


def _hit_bearish(
    timeframe: str,
    p_a: int,
    p_b: int,
    highs: list[float],
    ra: float,
    rb: float,
    confirm_index: int,
) -> PatternHit:
    diff = ra - rb
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bearish",
        title_fa="واگرایی نزولی RSI",
        status_fa="تأییدشده",
        summary_fa=(
            f"Regular Bearish (BigBeluga) · "
            f"قیمت HH ({highs[p_b]:,.0f} > {highs[p_a]:,.0f})، "
            f"RSI LH ({rb:.1f} < {ra:.1f}، Δ{diff:.1f})"
        ),
        forecast_fa="احتمال اصلاح نزولی؛ تأیید با شکست کف کوتاه‌مدت.",
        meta={
            "pivot_a": (p_a, highs[p_a]),
            "pivot_b": (p_b, highs[p_b]),
            "rsi_a": ra,
            "rsi_b": rb,
            "direction": "down",
            "confirm_index": confirm_index,
            "final_index": confirm_index,
        },
    )


def _hit_bullish(
    timeframe: str,
    p_a: int,
    p_b: int,
    lows: list[float],
    ra: float,
    rb: float,
    confirm_index: int,
) -> PatternHit:
    diff = rb - ra
    return PatternHit(
        category="divergence",
        timeframe=timeframe,
        pattern_id="rsi_bullish",
        title_fa="واگرایی مثبت RSI",
        status_fa="تأییدشده",
        summary_fa=(
            f"Regular Bullish (BigBeluga) · "
            f"قیمت LL ({lows[p_b]:,.0f} < {lows[p_a]:,.0f})، "
            f"RSI HL ({rb:.1f} > {ra:.1f}، Δ{diff:.1f})"
        ),
        forecast_fa="احتمال اصلاح صعودی؛ تأیید با شکست سقف کوتاه‌مدت.",
        meta={
            "pivot_a": (p_a, lows[p_a]),
            "pivot_b": (p_b, lows[p_b]),
            "rsi_a": ra,
            "rsi_b": rb,
            "direction": "up",
            "confirm_index": confirm_index,
            "final_index": confirm_index,
        },
    )


def detect_rsi_divergence(
    bars: list[OhlcBar],
    timeframe: str,
    *,
    allow_early: bool = True,  # deprecated; ignored — Pine has no early alert
) -> PatternHit | None:
    del allow_early
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
        if conf_b == n - 1:
            _, p_a = ph[-2]
            if _in_range(p_a, p_b):
                pair = _bearish_ok(rs, highs, p_a, p_b)
                if pair:
                    ra, rb = pair
                    return _hit_bearish(
                        timeframe, p_a, p_b, highs, ra, rb, conf_b
                    )

    if len(pl) >= 2:
        conf_b, p_b = pl[-1]
        if conf_b == n - 1:
            _, p_a = pl[-2]
            if _in_range(p_a, p_b):
                pair = _bullish_ok(rs, lows, p_a, p_b)
                if pair:
                    ra, rb = pair
                    return _hit_bullish(
                        timeframe, p_a, p_b, lows, ra, rb, conf_b
                    )

    return None
