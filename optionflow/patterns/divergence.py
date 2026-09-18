from __future__ import annotations

from optionflow.patterns.indicators import (
    rsi,
    rsi_pivot_high_confirmations,
    rsi_pivot_low_confirmations,
)
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

# TradingView built-in RSI divergence block (calculateDivergence)
LOOKBACK_LEFT = 5
LOOKBACK_RIGHT = 5
RANGE_LOWER = 5
RANGE_UPPER = 60


def _in_range(prev_pivot: int, pivot: int) -> bool:
    bars = pivot - prev_pivot
    return RANGE_LOWER <= bars <= RANGE_UPPER


def detect_rsi_divergence(bars: list[OhlcBar], timeframe: str) -> PatternHit | None:
    min_len = LOOKBACK_LEFT + LOOKBACK_RIGHT + RANGE_UPPER + 20
    if len(bars) < min_len:
        return None

    closes = [b.close for b in bars]
    rs = rsi(closes)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]

    pl = rsi_pivot_low_confirmations(
        rs, left=LOOKBACK_LEFT, right=LOOKBACK_RIGHT
    )
    ph = rsi_pivot_high_confirmations(
        rs, left=LOOKBACK_LEFT, right=LOOKBACK_RIGHT
    )

    n = len(bars)
    last_conf = n - 1

    # Regular bearish — آخرین pivot high تأییدشده نزدیک انتهای سری
    if len(ph) >= 2:
        conf_b, p_b = ph[-1]
        if conf_b >= n - LOOKBACK_RIGHT - 2:
            conf_a, p_a = ph[-2]
            if _in_range(p_a, p_b):
                ra, rb = rs[p_a], rs[p_b]
                if ra is not None and rb is not None and rb < ra:
                    if highs[p_b] > highs[p_a]:
                        diff = ra - rb
                        status = "تأییدشده" if diff >= 3 else "در حال شکل‌گیری"
                        return PatternHit(
                            category="divergence",
                            timeframe=timeframe,
                            pattern_id="rsi_bearish",
                            title_fa="واگرایی نزولی RSI",
                            status_fa=status,
                            summary_fa=(
                                f"Regular Bearish (TradingView): قیمت سقف بالاتر "
                                f"({highs[p_b]:,.0f} > {highs[p_a]:,.0f})، "
                                f"RSI سقف پایین‌تر ({rb:.1f} < {ra:.1f}) — pivot {LOOKBACK_LEFT}/{LOOKBACK_RIGHT}."
                            ),
                            forecast_fa=(
                                "پیش‌بینی: احتمال اصلاح نزولی یا برگشت کوتاه‌مدت، "
                                "در صورت تأیید با شکست کف کوچک اخیر."
                            ),
                            meta={
                                "pivot_a": (p_a, highs[p_a]),
                                "pivot_b": (p_b, highs[p_b]),
                                "rsi_a": ra,
                                "rsi_b": rb,
                                "direction": "down",
                                "confirm_index": conf_b,
                                "tv_pivot": True,
                            },
                        )

    if len(pl) >= 2:
        conf_b, p_b = pl[-1]
        if conf_b >= n - LOOKBACK_RIGHT - 2:
            conf_a, p_a = pl[-2]
            if _in_range(p_a, p_b):
                ra, rb = rs[p_a], rs[p_b]
                if ra is not None and rb is not None and rb > ra:
                    if lows[p_b] < lows[p_a]:
                        diff = rb - ra
                        status = "تأییدشده" if diff >= 3 else "در حال شکل‌گیری"
                        return PatternHit(
                            category="divergence",
                            timeframe=timeframe,
                            pattern_id="rsi_bullish",
                            title_fa="واگرایی مثبت RSI",
                            status_fa=status,
                            summary_fa=(
                                f"Regular Bullish (TradingView): قیمت کف پایین‌تر "
                                f"({lows[p_b]:,.0f} < {lows[p_a]:,.0f})، "
                                f"RSI کف بالاتر ({rb:.1f} > {ra:.1f})."
                            ),
                            forecast_fa=(
                                "پیش‌بینی: احتمال اصلاح صعودی یا برگشت کوتاه‌مدت، "
                                "در صورت تأیید با شکست سقف کوچک اخیر."
                            ),
                            meta={
                                "pivot_a": (p_a, lows[p_a]),
                                "pivot_b": (p_b, lows[p_b]),
                                "rsi_a": ra,
                                "rsi_b": rb,
                                "direction": "up",
                                "confirm_index": conf_b,
                                "tv_pivot": True,
                            },
                        )

    return None
