from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.three_rp import detect_three_rp


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


def test_three_rp_only_1h() -> None:
    bars = [_bar(100, 101, 99, 100)] * 5
    assert detect_three_rp(bars, "5m") is None
    assert detect_three_rp(bars, "15m") is None


def test_bullish_three_rp_detected() -> None:
    bars = [
        _bar(100, 100, 90, 92, 0),
        _bar(91, 94, 88, 90, 1),
        _bar(90, 101, 89, 95, 2),
    ]
    hit = detect_three_rp(bars, "1h")
    assert hit is not None
    assert hit.pattern_id == "three_rp_bull"
    assert hit.meta["direction"] == "up"
    assert hit.meta["signal_index"] == 2


def test_bearish_three_rp_enhanced_confirmed() -> None:
    bars = [
        _bar(90, 100, 89, 98, 0),
        _bar(99, 102, 97, 101, 1),
        _bar(100, 101, 86, 88, 2),
    ]
    hit = detect_three_rp(bars, "1h")
    assert hit is not None
    assert hit.pattern_id == "three_rp_bear"
    assert hit.meta.get("enhanced") is True
    assert hit.meta.get("stage") == "confirmed"
