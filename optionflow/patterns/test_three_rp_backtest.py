from datetime import datetime, timedelta, timezone

from optionflow.patterns.backtest import replay_category
from optionflow.patterns.ohlc import OhlcBar


def _bar(o, h, l, c, i=0):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return OhlcBar(
        ts=t0 + timedelta(hours=i),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=1.0,
    )


def test_replay_three_rp_finds_enhanced_on_bar_index() -> None:
    bars = [
        _bar(100, 100, 90, 92, 0),
        _bar(91, 94, 88, 90, 1),
        _bar(90, 105, 89, 102, 2),
        _bar(102, 103, 101, 101.5, 3),
    ]
    hits = replay_category(
        bars,
        category="three_rp",
        timeframe="1h",
        scan_start=0,
        scan_end=3,
    )
    assert len(hits) == 1
    idx, hit = hits[0]
    assert idx == 2
    assert hit.pattern_id == "three_rp_bull"


def test_replay_three_rp_empty_on_non_1h() -> None:
    bars = [_bar(100, 101, 99, 100, i) for i in range(5)]
    hits = replay_category(
        bars,
        category="three_rp",
        timeframe="5m",
        scan_start=0,
        scan_end=4,
    )
    assert hits == []
