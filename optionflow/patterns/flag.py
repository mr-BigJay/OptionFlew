from __future__ import annotations

from optionflow.patterns.indicators import atr
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit


def detect_flag(bars: list[OhlcBar], timeframe: str) -> PatternHit | None:
    if len(bars) < 60:
        return None
    window = bars[-80:]
    closes = [b.close for b in window]
    highs = [b.high for b in window]
    lows = [b.low for b in window]

    pole_len = {"5m": 12, "15m": 10, "1h": 8, "4h": 6, "1d": 5}.get(timeframe, 10)
    flag_len = {"5m": 15, "15m": 12, "1h": 10, "4h": 8, "1d": 6}.get(timeframe, 12)
    if len(closes) < pole_len + flag_len + 5:
        return None

    pole_start = -(pole_len + flag_len)
    pole_end = -flag_len
    flag_start = -flag_len

    p0 = closes[pole_start]
    p1 = closes[pole_end]
    if p0 <= 0:
        return None
    pole_ret = (p1 - p0) / p0
    min_pole = {"5m": 0.012, "15m": 0.018, "1h": 0.022, "4h": 0.028, "1d": 0.035}.get(
        timeframe, 0.015
    )
    if abs(pole_ret) < min_pole:
        return None

    flag_cl = closes[flag_start:]
    flag_hi = highs[flag_start:]
    flag_lo = lows[flag_start:]
    flag_range = max(flag_hi) - min(flag_lo)
    pole_range = max(highs[pole_start:pole_end]) - min(lows[pole_start:pole_end])
    if pole_range <= 0 or flag_range / pole_range > 0.55:
        return None

    atr_vals = atr(window)
    atr_last = atr_vals[-1] or atr_vals[-2]
    if atr_last and flag_range > atr_last * 3:
        return None

    if pole_ret > 0:
        if flag_cl[-1] > flag_cl[0] * 1.002:
            return None
        title = "پرچم صعودی (Bull Flag)"
        forecast = (
            "پیش‌بینی: در صورت شکست بالای کانال پرچم، ادامهٔ حرکت صعودی "
            "هم‌جهت با قطب (pole) محتمل است."
        )
        pattern_id = "flag_bull"
        direction = "up"
    else:
        if flag_cl[-1] < flag_cl[0] * 0.998:
            return None
        title = "پرچم نزولی (Bear Flag)"
        forecast = (
            "پیش‌بینی: در صورت شکست پایین کانال پرچم، ادامهٔ حرکت نزولی "
            "هم‌جهت با قطب محتمل است."
        )
        pattern_id = "flag_bear"
        direction = "down"

    status = "تأییدشده" if flag_range / pole_range < 0.35 else "در حال شکل‌گیری"

    return PatternHit(
        category="flag",
        timeframe=timeframe,
        pattern_id=pattern_id,
        title_fa=title,
        status_fa=status,
        summary_fa=(
            f"حرکت شارپ {'صعودی' if pole_ret > 0 else 'نزولی'} (قدرت {abs(pole_ret)*100:.1f}٪) "
            f"و سپس کانال فشرده؛ طول پرچم حدود {flag_len} کندل (کمتر از ۵۵٪ قطب)."
        ),
        forecast_fa=forecast,
        meta={
            "pole_start": len(bars) - (pole_len + flag_len),
            "pole_end": len(bars) - flag_len,
            "flag_start": len(bars) - flag_len,
            "pole_ret": pole_ret,
            "direction": direction,
            "flag_high": max(flag_hi),
            "flag_low": min(flag_lo),
        },
    )
