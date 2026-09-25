from __future__ import annotations

from optionflow.patterns.chart_overlays import bar_unix
from optionflow.patterns.ohlc import OhlcBar

# بازهٔ نمای اول (ثانیه) — فقط zoom اولیه؛ کل داده برای pan/chart history می‌ماند
INITIAL_VIEW_SECONDS: dict[str, int] = {
    "4h": 60 * 24 * 3600,  # ~۲ ماه
    "1h": 10 * 24 * 3600,
    "15m": 2 * 24 * 3600,
    "5m": 12 * 3600,
    "1m": int(12 * 3600 / 5),  # همان نسبت ۵m → ~۲.۴ ساعت (~۱۴۴ کندل)
}


def initial_viewport(timeframe: str, bars: list[OhlcBar]) -> dict[str, int] | None:
    if not bars:
        return None
    tf = (timeframe or "15m").strip().lower()
    span = INITIAL_VIEW_SECONDS.get(tf, 2 * 24 * 3600)
    t_to = int(bar_unix(bars[-1]))
    t_from = t_to - span
    return {"from": t_from, "to": t_to}
