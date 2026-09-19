from __future__ import annotations


def ema(values: list[float], length: int) -> list[float | None]:
    """TradingView `ta.ema`: بذر SMA سپس alpha=2/(len+1)."""
    n = len(values)
    out: list[float | None] = [None] * n
    if length < 1 or n < length:
        return out
    alpha = 2.0 / (length + 1)
    prev = sum(values[:length]) / length
    out[length - 1] = prev
    for i in range(length, n):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def rma(values: list[float], period: int) -> list[float | None]:
    """RMA / SMMA (همان ta.rma در TradingView)."""
    n = len(values)
    out: list[float | None] = [None] * n
    if period < 1 or n < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """RSI built-in TradingView: RMA روی up/down از ta.change(close)."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < 2 or period < 1:
        return out

    changes = [0.0] + [closes[i] - closes[i - 1] for i in range(1, n)]
    ups = [max(c, 0.0) for c in changes]
    downs = [-min(c, 0.0) for c in changes]

    up_r = rma(ups, period)
    down_r = rma(downs, period)

    for i in range(n):
        u = up_r[i]
        d = down_r[i]
        if u is None or d is None:
            continue
        if d == 0:
            out[i] = 100.0
        elif u == 0:
            out[i] = 0.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + u / d)
    return out


def is_pivot_low(values: list[float | None], p: int, left: int, right: int) -> bool:
    if p - left < 0 or p + right >= len(values):
        return False
    val = values[p]
    if val is None:
        return False
    for j in range(p - left, p + right + 1):
        v = values[j]
        if v is None:
            return False
        if j != p and v < val:
            return False
    return True


def is_pivot_high(values: list[float | None], p: int, left: int, right: int) -> bool:
    if p - left < 0 or p + right >= len(values):
        return False
    val = values[p]
    if val is None:
        return False
    for j in range(p - left, p + right + 1):
        v = values[j]
        if v is None:
            return False
        if j != p and v > val:
            return False
    return True


def rsi_pivot_low_confirmations(
    rs: list[float | None], *, left: int = 5, right: int = 5
) -> list[tuple[int, int]]:
    """(confirm_bar, pivot_bar) — مثل ta.pivotlow با تأخیر right."""
    out: list[tuple[int, int]] = []
    for conf in range(left + right, len(rs)):
        p = conf - right
        if is_pivot_low(rs, p, left, right):
            out.append((conf, p))
    return out


def rsi_pivot_high_confirmations(
    rs: list[float | None], *, left: int = 5, right: int = 5
) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for conf in range(left + right, len(rs)):
        p = conf - right
        if is_pivot_high(rs, p, left, right):
            out.append((conf, p))
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
