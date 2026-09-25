from datetime import datetime, timedelta, timezone

from app.indicator_viewport import INITIAL_VIEW_SECONDS, initial_viewport
from optionflow.patterns.chart_overlays import bar_unix
from optionflow.patterns.ohlc import OhlcBar


def _bar(i: int) -> OhlcBar:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    c = 90_000.0
    return OhlcBar(
        ts=t0 + timedelta(minutes=i),
        open=c,
        high=c + 1,
        low=c - 1,
        close=c,
        volume=1.0,
    )


def test_initial_viewport_spans() -> None:
    bars = [_bar(i) for i in range(5000)]
    vp = initial_viewport("5m", bars)
    assert vp is not None
    assert vp["to"] - vp["from"] == INITIAL_VIEW_SECONDS["5m"]
    vp1 = initial_viewport("1m", bars)
    assert vp1 is not None
    assert vp1["to"] - vp1["from"] == INITIAL_VIEW_SECONDS["1m"]
    assert bar_unix(bars[-1]) == vp["to"]
