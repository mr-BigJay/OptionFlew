from __future__ import annotations

from optionflow.patterns.indicators import (
    rsi,
    rsi_pivot_high_confirmations,
    rsi_pivot_low_confirmations,
)
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit

# TradingView built-in RSI divergence (ta.pivothigh/low 5/5 + consecutive swings)
LOOKBACK_LEFT = 5
LOOKBACK_RIGHT = 5
RANGE_LOWER = 5
RANGE_UPPER = 60
MIN_RSI_DIFF = 3.0
RSI_OVERBOUGHT = 65.0  # نزدیک ۷۰ — سقف اول باید در ناحیه اشباع باشد
RSI_OVERSOLD = 35.0  # نزدیک ۳۰ — کف اول باید در ناحیه اشباع فروش باشد


def _in_range(prev_pivot: int, pivot: int) -> bool:
    return RANGE_LOWER <= (pivot - prev_pivot) <= RANGE_UPPER


def _recent_confirm(conf_b: int, n: int) -> bool:
    """سیگنال وقتی pivot با right=5 تازه تأیید شده (سازگار با stride بکتست)."""
    return conf_b >= n - LOOKBACK_RIGHT - 2


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

    if len(ph) >= 2:
        conf_b, p_b = ph[-1]
        if _recent_confirm(conf_b, n):
            _, p_a = ph[-2]
            if _in_range(p_a, p_b):
                ra, rb = rs[p_a], rs[p_b]
                if (
                    ra is not None
                    and rb is not None
                    and ra >= RSI_OVERBOUGHT
                    and (ra - rb) >= MIN_RSI_DIFF
                    and highs[p_b] > highs[p_a]
                ):
                    diff = ra - rb
                    status = "تأییدشده" if diff >= 5 else "در حال شکل‌گیری"
                    return PatternHit(
                        category="divergence",
                        timeframe=timeframe,
                        pattern_id="rsi_bearish",
                        title_fa="واگرایی نزولی RSI",
                        status_fa=status,
                        summary_fa=(
                            f"Regular Bearish (TV 5/5): دو سقف متوالی — "
                            f"قیمت بالاتر ({highs[p_b]:,.0f} > {highs[p_a]:,.0f})، "
                            f"RSI پایین‌تر ({rb:.1f} < {ra:.1f}، Δ{diff:.1f})."
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
        if _recent_confirm(conf_b, n):
            _, p_a = pl[-2]
            if _in_range(p_a, p_b):
                ra, rb = rs[p_a], rs[p_b]
                if (
                    ra is not None
                    and rb is not None
                    and ra <= RSI_OVERSOLD
                    and (rb - ra) >= MIN_RSI_DIFF
                    and lows[p_b] < lows[p_a]
                ):
                    diff = rb - ra
                    status = "تأییدشده" if diff >= 5 else "در حال شکل‌گیری"
                    return PatternHit(
                        category="divergence",
                        timeframe=timeframe,
                        pattern_id="rsi_bullish",
                        title_fa="واگرایی مثبت RSI",
                        status_fa=status,
                        summary_fa=(
                            f"Regular Bullish (TV 5/5): دو کف متوالی — "
                            f"قیمت پایین‌تر ({lows[p_b]:,.0f} < {lows[p_a]:,.0f})، "
                            f"RSI بالاتر ({rb:.1f} > {ra:.1f}، Δ{diff:.1f})."
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
