from __future__ import annotations

from optionflow.patterns.indicators import rsi
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.pivots import Pivot, zigzag_pivots
from optionflow.patterns.types import PatternHit


def _zig_pct(tf: str) -> float:
    return {"5m": 0.004, "15m": 0.008, "1h": 0.012}.get(tf, 0.01)


def detect_rsi_divergence(bars: list[OhlcBar], timeframe: str) -> PatternHit | None:
    if len(bars) < 60:
        return None
    closes = [b.close for b in bars]
    rs = rsi(closes)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    pivots = zigzag_pivots(highs, lows, pct=_zig_pct(timeframe))
    lows_p = [p for p in pivots if p.kind == "low"][-3:]
    highs_p = [p for p in pivots if p.kind == "high"][-3:]

    if len(lows_p) >= 2:
        a, b = lows_p[-2], lows_p[-1]
        if b.index - a.index < 5 or b.index - a.index > 50:
            pass
        else:
            ra, rb = rs[a.index], rs[b.index]
            if ra is not None and rb is not None and b.price < a.price and rb > ra + 3:
                diff = rb - ra
                status = "تأییدشده" if diff >= 5 else "در حال شکل‌گیری"
                return PatternHit(
                    category="divergence",
                    timeframe=timeframe,
                    pattern_id="rsi_bullish",
                    title_fa="واگرایی مثبت RSI",
                    status_fa=status,
                    summary_fa=(
                        f"قیمت کف جدید ({b.price:,.0f}) پایین‌تر از کف قبل ({a.price:,.0f}) ساخته، "
                        f"اما RSI از {ra:.0f} به {rb:.0f} بالاتر رفته — فشار فروش ضعیف‌تر شده."
                    ),
                    forecast_fa=(
                        "پیش‌بینی: احتمال اصلاح صعودی یا برگشت کوتاه‌مدت، "
                        "در صورت تأیید با شکست سقف کوچک اخیر."
                    ),
                    meta={
                        "pivot_a": (a.index, a.price),
                        "pivot_b": (b.index, b.price),
                        "rsi_a": ra,
                        "rsi_b": rb,
                        "direction": "up",
                    },
                )

    if len(highs_p) >= 2:
        a, b = highs_p[-2], highs_p[-1]
        if 5 <= b.index - a.index <= 50:
            ra, rb = rs[a.index], rs[b.index]
            if ra is not None and rb is not None and b.price > a.price and rb < ra - 3:
                diff = ra - rb
                status = "تأییدشده" if diff >= 5 else "در حال شکل‌گیری"
                return PatternHit(
                    category="divergence",
                    timeframe=timeframe,
                    pattern_id="rsi_bearish",
                    title_fa="واگرایی نزولی RSI",
                    status_fa=status,
                    summary_fa=(
                        f"قیمت سقف جدید ({b.price:,.0f}) بالاتر از سقف قبل ({a.price:,.0f})، "
                        f"اما RSI از {ra:.0f} به {rb:.0f} پایین‌تر آمده — مومنتوم صعودی ضعیف شده."
                    ),
                    forecast_fa=(
                        "پیش‌بینی: احتمال اصلاح نزولی یا برگشت کوتاه‌مدت، "
                        "در صورت تأیید با شکست کف کوچک اخیر."
                    ),
                    meta={
                        "pivot_a": (a.index, a.price),
                        "pivot_b": (b.index, b.price),
                        "rsi_a": ra,
                        "rsi_b": rb,
                        "direction": "down",
                    },
                )
    return None
