from __future__ import annotations

from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit


def _is_bullish_reversal(bars: list[OhlcBar], i: int) -> bool:
    if i < 2:
        return False
    b0, b1, b2 = bars[i - 2], bars[i - 1], bars[i]
    return (
        b0.close < b0.open
        and b1.low < b0.low
        and b1.high < b0.high
        and b1.close < b1.open
        and b2.close > b2.open
        and b2.high > b0.high
    )


def _is_bearish_reversal(bars: list[OhlcBar], i: int) -> bool:
    if i < 2:
        return False
    b0, b1, b2 = bars[i - 2], bars[i - 1], bars[i]
    return (
        b0.close > b0.open
        and b1.high > b0.high
        and b1.low > b0.low
        and b1.close > b1.open
        and b2.close < b2.open
        and b2.low < b0.low
    )


def _bull_support(b1: OhlcBar, b2: OhlcBar) -> float:
    return min(b1.low, b2.low)


def _bear_resistance(b1: OhlcBar, b2: OhlcBar) -> float:
    return max(b1.high, b2.high)


def _follow_bull(
    bars: list[OhlcBar], i: int, pattern_high: float, support: float
) -> tuple[str, int | None]:
    """Stage after detection bar i through last bar."""
    enhanced_at_detect = bars[i].close > pattern_high
    for j in range(i + 1, len(bars)):
        prev = bars[j - 1]
        if _is_bearish_reversal(bars, j) or prev.close < support:
            return "failed", None
        if prev.close > pattern_high:
            return "confirmed", j - 1
    if enhanced_at_detect:
        return "confirmed", i
    return "detected", None


def _follow_bear(
    bars: list[OhlcBar], i: int, pattern_low: float, resistance: float
) -> tuple[str, int | None]:
    enhanced_at_detect = bars[i].close < pattern_low
    for j in range(i + 1, len(bars)):
        prev = bars[j - 1]
        if _is_bullish_reversal(bars, j) or prev.close > resistance:
            return "failed", None
        if prev.close < pattern_low:
            return "confirmed", j - 1
    if enhanced_at_detect:
        return "confirmed", i
    return "detected", None


def detect_three_rp(bars: list[OhlcBar], timeframe: str) -> PatternHit | None:
    """LuxAlgo Three Bar Reversal — فقط تایم‌فریم ۱ ساعته."""
    if timeframe != "1h":
        return None
    if len(bars) < 3:
        return None

    max_back = min(48, len(bars) - 2)
    for off in range(max_back + 1):
        i = len(bars) - 1 - off
        b0, b1, b2 = bars[i - 2], bars[i - 1], bars[i]
        if _is_bullish_reversal(bars, i):
            pattern_high = b0.high
            support = _bull_support(b1, b2)
            enhanced = b2.close > pattern_high
            stage, confirm_i = _follow_bull(bars, i, pattern_high, support)
            if stage == "failed" and i < len(bars) - 1:
                continue
            status = {
                "confirmed": "تأییدشده",
                "detected": "سیگنال ۳RP",
                "failed": "رد شده",
            }[stage]
            kind = "enhanced" if enhanced else "normal"
            return PatternHit(
                category="three_rp",
                timeframe=timeframe,
                pattern_id="three_rp_bull",
                title_fa="۳RP صعودی (Three Bar Reversal)",
                status_fa=status,
                summary_fa=(
                    f"برگشت سه‌کندلی صعودی ({kind})؛ "
                    f"سقف الگو {pattern_high:,.0f} · کف ساختار {support:,.0f}."
                ),
                forecast_fa=(
                    "پیش‌بینی: در صورت تأیید (بسته شدن بالای سقف کندل اول)، "
                    "احتمال حرکت صعودی؛ شکست زیر کف الگو = باطل."
                ),
                meta={
                    "direction": "up",
                    "stage": stage,
                    "kind": kind,
                    "signal_index": i,
                    "confirm_index": confirm_i if confirm_i is not None else i,
                    "bar_first": i - 2,
                    "bar_middle": i - 1,
                    "pattern_high": pattern_high,
                    "pattern_low": pattern_high,
                    "support_line": support,
                    "resistance_line": pattern_high,
                    "enhanced": enhanced,
                },
            )

        if _is_bearish_reversal(bars, i):
            pattern_low = b0.low
            resistance = _bear_resistance(b1, b2)
            enhanced = b2.close < pattern_low
            stage, confirm_i = _follow_bear(bars, i, pattern_low, resistance)
            if stage == "failed" and i < len(bars) - 1:
                continue
            status = {
                "confirmed": "تأییدشده",
                "detected": "سیگنال ۳RP",
                "failed": "رد شده",
            }[stage]
            kind = "enhanced" if enhanced else "normal"
            return PatternHit(
                category="three_rp",
                timeframe=timeframe,
                pattern_id="three_rp_bear",
                title_fa="۳RP نزولی (Three Bar Reversal)",
                status_fa=status,
                summary_fa=(
                    f"برگشت سه‌کندلی نزولی ({kind})؛ "
                    f"کف الگو {pattern_low:,.0f} · سقف ساختار {resistance:,.0f}."
                ),
                forecast_fa=(
                    "پیش‌بینی: در صورت تأیید (بسته شدن زیر کف کندل اول)، "
                    "احتمال حرکت نزولی؛ شکست بالای سقف الگو = باطل."
                ),
                meta={
                    "direction": "down",
                    "stage": stage,
                    "kind": kind,
                    "signal_index": i,
                    "confirm_index": confirm_i if confirm_i is not None else i,
                    "bar_first": i - 2,
                    "bar_middle": i - 1,
                    "pattern_high": pattern_low,
                    "pattern_low": pattern_low,
                    "support_line": pattern_low,
                    "resistance_line": resistance,
                    "enhanced": enhanced,
                },
            )

    return None
