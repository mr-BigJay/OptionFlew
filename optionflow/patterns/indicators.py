from __future__ import annotations


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """RSI وایlder (مثل TradingView/Binance) — ایندکس هم‌تراز با closes."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))

    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    if avg_l <= 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_g / avg_l)

    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        if avg_l <= 0:
            out[i + 1] = 100.0
        else:
            rs = avg_g / avg_l
            out[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return out


def atr(bars: list, period: int = 14) -> list[float | None]:
    if len(bars) < 2:
        return [None] * len(bars)
    trs: list[float] = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    out: list[float | None] = [None] * len(bars)
    if len(trs) < period:
        return out
    val = sum(trs[:period]) / period
    out[period] = val
    for i in range(period, len(trs)):
        val = (val * (period - 1) + trs[i]) / period
        out[i + 1] = val
    return out
