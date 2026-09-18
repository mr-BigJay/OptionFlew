from __future__ import annotations

from optionflow.patterns.indicators import atr
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.pivots import zigzag_pivots
from optionflow.patterns.types import PatternHit

# فشردگی واقعی، نه هر کانال باریک‌شوندهٔ نویزی
_ZIGZAG_PCT = {"5m": 0.006, "15m": 0.01, "1h": 0.016, "4h": 0.02, "1d": 0.026}
_MIN_SPAN = {"5m": 28, "15m": 22, "1h": 18, "4h": 14, "1d": 12}
_MAX_LAST_PIVOT_AGE = {"5m": 16, "15m": 12, "1h": 10, "4h": 8, "1d": 6}
_CONTRACTION = 0.68  # gap_end باید کمتر از ۶۸٪ gap_start باشد
_TOUCH_ATR = 0.5
_FLAT_SLOPE = 0.00012  # شیب نسبی به قیمت برای خط «افقی»


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


def _y(slope: float, intercept: float, i: int) -> float:
    return slope * i + intercept


def _touches_line(
    idxs: list[int],
    px: list[float],
    slope: float,
    intercept: float,
    tol: float,
) -> bool:
    if not idxs:
        return False
    return all(abs(p - _y(slope, intercept, i)) <= tol for i, p in zip(idxs, px))


def _apex_index(su: float, iu: float, sl: float, il: float) -> float | None:
    den = su - sl
    if abs(den) < 1e-12:
        return None
    return (il - iu) / den


def detect_triangle(bars: list[OhlcBar], timeframe: str) -> PatternHit | None:
    if len(bars) < 80:
        return None
    window = bars[-120:]
    n = len(window)
    highs = [b.high for b in window]
    lows = [b.low for b in window]
    pct = _ZIGZAG_PCT.get(timeframe, 0.01)
    pivots = zigzag_pivots(highs, lows, pct=pct)
    if len(pivots) < 4:
        return None

    seq = pivots[-6:]
    kinds = [p.kind for p in seq]
    if all(kinds[i] == kinds[i + 1] for i in range(len(kinds) - 1)):
        return None
    # باید H/L یکی‌درمیان باشد (الگوی مثلث، نه دو سقف پشت‌سرهم)
    alt = seq[:]
    cleaned = [alt[0]]
    for p in alt[1:]:
        if p.kind == cleaned[-1].kind:
            # نویز zigzag: هم‌نوع را نگه ندار
            if p.kind == "high" and p.price >= cleaned[-1].price:
                cleaned[-1] = p
            elif p.kind == "low" and p.price <= cleaned[-1].price:
                cleaned[-1] = p
            continue
        cleaned.append(p)
    if len(cleaned) < 4:
        return None
    seq = cleaned[-5:]

    ph = [p for p in seq if p.kind == "high"]
    pl = [p for p in seq if p.kind == "low"]
    if len(ph) < 2 or len(pl) < 2:
        return None

    hi_idx = [p.index for p in ph]
    hi_px = [p.price for p in ph]
    lo_idx = [p.index for p in pl]
    lo_px = [p.price for p in pl]

    su, iu = _line_fit(hi_idx, hi_px)
    sl, il = _line_fit(lo_idx, lo_px)

    start_i = min(hi_idx + lo_idx)
    end_i = max(hi_idx + lo_idx)
    min_span = _MIN_SPAN.get(timeframe, 22)
    if end_i - start_i < min_span:
        return None

    last_pivot_i = max(p.index for p in seq)
    max_age = _MAX_LAST_PIVOT_AGE.get(timeframe, 12)
    if n - 1 - last_pivot_i > max_age:
        return None

    upper_start = _y(su, iu, start_i)
    upper_end = _y(su, iu, end_i)
    lower_start = _y(sl, il, start_i)
    lower_end = _y(sl, il, end_i)
    gap_start = upper_start - lower_start
    gap_end = upper_end - lower_end
    if gap_start <= 0 or gap_end <= 0:
        return None
    if gap_end >= gap_start * _CONTRACTION:
        return None

    atr_vals = atr(window)
    atr_now = next((v for v in reversed(atr_vals) if v is not None), None)
    if atr_now is None or atr_now <= 0:
        return None
    tol = atr_now * _TOUCH_ATR
    if not _touches_line(hi_idx, hi_px, su, iu, tol):
        return None
    if not _touches_line(lo_idx, lo_px, sl, il, tol):
        return None

    last = window[-1]
    u_now = _y(su, iu, n - 1)
    l_now = _y(sl, il, n - 1)
    if u_now <= l_now:
        return None
    # قیمت باید داخل مثلث باشد (بدنه از خطوط نگذشته)
    if last.close > u_now or last.close < l_now:
        return None
    if last.high > u_now + tol or last.low < l_now - tol:
        return None

    apex = _apex_index(su, iu, sl, il)
    if apex is None:
        return None
    # رأس باید جلوتر باشد، نه اینکه الگو تمام شده باشد
    if apex <= n - 1:
        return None
    if apex - (n - 1) > (end_i - start_i) * 2.5:
        return None

    px = last.close
    flat = _FLAT_SLOPE * px
    upper_falling = su < -flat * 0.35
    lower_rising = sl > flat * 0.35
    upper_flat = abs(su) <= flat
    lower_flat = abs(sl) <= flat

    if lower_rising and (upper_flat or abs(su) < abs(sl) * 0.45):
        kind = "ascending"
        title = "مثلث صعودی (فشردگی)"
        forecast = "احتمال شکست بالای مقاومت افقی و حرکت صعودی در صورت بسته شدن بالای خط."
    elif upper_falling and (lower_flat or abs(sl) < abs(su) * 0.45):
        kind = "descending"
        title = "مثلث نزولی (فشردگی)"
        forecast = "احتمال شکست پایین حمایت افقی و ادامهٔ نزول در صورت بسته شدن زیر خط."
    elif upper_falling and lower_rising:
        kind = "symmetrical"
        title = "مثلث متقارن (فشردگی)"
        forecast = "شکست جهت‌دار از محدودهٔ فشرده؛ جهت را کندل تأییدکننده مشخص می‌کند."
    else:
        return None

    status = "تأییدشده" if gap_end / gap_start < 0.5 else "در حال شکل‌گیری"

    return PatternHit(
        category="triangle",
        timeframe=timeframe,
        pattern_id=f"triangle_{kind}",
        title_fa=title,
        status_fa=status,
        summary_fa=(
            f"{len(ph)} برخورد سقف و {len(pl)} برخورد کف به خطوط؛ "
            f"فاصله از {gap_start:,.0f} به {gap_end:,.0f} دلار رسیده. "
            f"قیمت داخل الگو ({last.close:,.0f})."
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
            "last_close": last.close,
            "mid": (u_now + l_now) / 2,
            "apex_index": apex,
            "touches_high": len(ph),
            "touches_low": len(pl),
        },
    )
