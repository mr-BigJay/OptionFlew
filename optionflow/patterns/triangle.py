from __future__ import annotations

from optionflow.patterns.indicators import atr
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.pivots import zigzag_pivots
from optionflow.patterns.types import PatternHit


def _line_fit(indices: list[int], prices: list[float]) -> tuple[float, float]:
    n = len(indices)
    if n < 2:
        return 0.0, prices[0] if prices else 0.0
    sx = sum(indices)
    sy = sum(prices)
    sxx = sum(i * i for i in indices)
    sxy = sum(i * p for i, p in zip(indices, prices))
    den = n * sxx - sx * sx
    if abs(den) < 1e-9:
        return 0.0, sy / n
    slope = (n * sxy - sx * sy) / den
    intercept = (sy - slope * sx) / n
    return slope, intercept


def detect_triangle(bars: list[OhlcBar], timeframe: str) -> PatternHit | None:
    if len(bars) < 80:
        return None
    window = bars[-120:]
    n = len(window)
    highs = [b.high for b in window]
    lows = [b.low for b in window]
    pct = {"5m": 0.0035, "15m": 0.007, "1h": 0.011, "4h": 0.016, "1d": 0.022}.get(timeframe, 0.008)
    pivots = zigzag_pivots(highs, lows, pct=pct)
    ph = [p for p in pivots if p.kind == "high"]
    pl = [p for p in pivots if p.kind == "low"]
    if len(ph) < 2 or len(pl) < 2:
        return None

    hi_idx = [p.index for p in ph[-3:]]
    hi_px = [p.price for p in ph[-3:]]
    lo_idx = [p.index for p in pl[-3:]]
    lo_px = [p.price for p in pl[-3:]]

    su, iu = _line_fit(hi_idx, hi_px)
    sl, il = _line_fit(lo_idx, lo_px)

    start_i, end_i = min(hi_idx + lo_idx), max(hi_idx + lo_idx)
    if end_i - start_i < 15:
        return None

    upper_start = su * start_i + iu
    upper_end = su * end_i + iu
    lower_start = sl * start_i + il
    lower_end = sl * end_i + il
    gap_start = upper_start - lower_start
    gap_end = upper_end - lower_end
    if gap_start <= 0 or gap_end <= 0:
        return None
    if gap_end >= gap_start * 0.85:
        return None

    atr_vals = atr(window)
    atr_recent = [v for v in atr_vals[-20:] if v is not None]
    atr_old = [v for v in atr_vals[-40:-20] if v is not None]
    if atr_recent and atr_old and sum(atr_recent) / len(atr_recent) > sum(atr_old) / len(atr_old) * 1.05:
        return None

    flat = 0.0003 * window[-1].close
    if abs(su) < flat and sl > 0:
        kind = "ascending"
        title = "مثلث صعودی (فشردگی)"
        forecast = "پیش‌بینی: شکست بالای مقاومت افقی و حرکت صعودی در صورت تأیید حجم."
    elif abs(sl) < flat and su < 0:
        kind = "descending"
        title = "مثلث نزولی (فشردگی)"
        forecast = "پیش‌بینی: شکست پایین حمایت افقی و ادامهٔ نزول در صورت تأیید."
    else:
        kind = "symmetrical"
        title = "مثلث متقارن (فشردگی)"
        forecast = "پیش‌بینی: شکست جهت‌دار از محدودهٔ فشرده؛ جهت را کندل تأییدکننده مشخص می‌کند."

    last_close = window[-1].close
    mid = (upper_end + lower_end) / 2
    status = "تأییدشده" if gap_end / gap_start < 0.55 else "در حال شکل‌گیری"

    return PatternHit(
        category="triangle",
        timeframe=timeframe,
        pattern_id=f"triangle_{kind}",
        title_fa=title,
        status_fa=status,
        summary_fa=(
            f"حداقل دو برخورد به خط بالایی و پایینی؛ فاصلهٔ بین خطوط از {gap_start:,.0f} "
            f"به {gap_end:,.0f} دلار کاهش یافته (ATR در حال فروکش)."
        ),
        forecast_fa=forecast,
        meta={
            "upper_slope": su,
            "upper_intercept": iu,
            "lower_slope": sl,
            "lower_intercept": il,
            "start_i": start_i,
            "end_i": end_i,
            "window_offset": len(bars) - n,
            "kind": kind,
            "last_close": last_close,
            "mid": mid,
        },
    )
