from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.three_rp import (
    DEFAULT_PATTERN_TYPE,
    PULLBACK_WAIT_BARS,
    _matches_pattern_type,
    detect_three_rp,
    detect_three_rp_at,
    enumerate_three_rp_enhanced,
    resolve_three_rp_entry,
    third_candle_range_pct,
)


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


def test_default_pattern_type_is_enhanced() -> None:
    assert DEFAULT_PATTERN_TYPE == "Enhanced"


def test_normal_bull_reversal_rejected() -> None:
    bars = [
        _bar(100, 100, 90, 92, 0),
        _bar(91, 94, 88, 90, 1),
        _bar(90, 101, 89, 95, 2),
    ]
    assert detect_three_rp_at(bars, "1h", 2) is None


def test_bullish_enhanced_small_candle_entry_on_close() -> None:
    bars = [
        _bar(100, 100, 90, 92, 0),
        _bar(91, 94, 88, 90, 1),
        _bar(101, 102, 101.2, 102, 2),
    ]
    hit = detect_three_rp(bars, "1h")
    assert hit is not None
    assert hit.meta["entry_mode"] == "close_third"
    assert hit.meta["entry_index"] == 2
    assert hit.meta["entry_px"] == 102
    assert third_candle_range_pct(bars[2]) < 1.0


def test_bullish_large_candle_waits_for_mid_touch() -> None:
    bars = [
        _bar(100, 100, 90, 92, 0),
        _bar(91, 94, 88, 90, 1),
        _bar(90, 105, 89, 102, 2),
        _bar(102, 103, 96, 101, 3),
    ]
    hit = detect_three_rp_at(bars, "1h", 2)
    assert hit is not None
    assert hit.meta["entry_mode"] == "mid_touch"
    assert hit.meta["entry_index"] == 3
    mid = (105 + 89) / 2
    assert hit.meta["entry_px"] == mid
    assert detect_three_rp(bars, "1h") is not None


def test_large_candle_no_touch_within_eight_bars_returns_none() -> None:
    bars = [
        _bar(100, 100, 90, 92, 0),
        _bar(91, 94, 88, 90, 1),
        _bar(90, 105, 89, 102, 2),
    ]
    bars += [_bar(102, 104, 101, 103, i) for i in range(3, 3 + PULLBACK_WAIT_BARS)]
    assert detect_three_rp_at(bars, "1h", 2) is None


def test_large_candle_mid_touch_on_forming_bar_signals() -> None:
    from optionflow.patterns.three_rp import third_candle_mid

    now = datetime.now(timezone.utc).replace(minute=10, second=0, microsecond=0)
    t0 = now - timedelta(hours=3)
    bars = [
        _bar(100, 100, 90, 92, 0),
        _bar(91, 94, 88, 90, 1),
        _bar(90, 105, 89, 102, 2),
        _bar(102, 104, 100, 101, 3),
    ]
    for i, b in enumerate(bars):
        b.ts = t0 + timedelta(hours=i)
    mid = third_candle_mid(bars[2])
    assert bars[3].low > mid
    assert detect_three_rp(bars, "1h") is None
    bars[3].low = mid - 1
    hit = detect_three_rp(bars, "1h")
    assert hit is not None
    assert hit.meta["entry_mode"] == "mid_touch"
    assert hit.meta["entry_index"] == 3


def test_large_candle_on_last_bar_waits_for_mid() -> None:
    bars = [
        _bar(100, 100, 90, 92, 0),
        _bar(91, 94, 88, 90, 1),
        _bar(90, 105, 89, 102, 2),
    ]
    assert detect_three_rp(bars, "1h") is None


def test_no_stale_pattern_from_lookback() -> None:
    bars = [
        _bar(100, 100, 90, 92, 0),
        _bar(91, 94, 88, 90, 1),
        _bar(101, 102, 101.2, 102, 2),
        _bar(102, 103, 101, 101.5, 3),
        _bar(101, 102, 100, 100.5, 4),
    ]
    assert detect_three_rp(bars, "1h") is None


def test_bearish_enhanced_confirmed() -> None:
    bars = [
        _bar(90, 100, 89, 98, 0),
        _bar(99, 102, 97, 101, 1),
        _bar(88.6, 89.05, 88.25, 88.3, 2),
    ]
    hit = detect_three_rp_at(bars, "1h", 2)
    assert hit is not None
    assert hit.pattern_id == "three_rp_bear"
    assert hit.meta.get("stage") == "confirmed"
    assert hit.meta["entry_mode"] == "close_third"


def test_enumerate_counts_each_bar_once() -> None:
    bars = [
        _bar(100, 100, 90, 92, 0),
        _bar(91, 94, 88, 90, 1),
        _bar(101, 102, 101.2, 102, 2),
        _bar(102, 103, 101, 101.5, 3),
    ]
    t0 = bars[0].ts
    hits = enumerate_three_rp_enhanced(
        bars,
        "1h",
        start=t0,
        end=bars[-1].ts + timedelta(hours=1),
    )
    assert len(hits) == 1
    assert hits[0][0] == 2


def test_matches_pattern_type_enhanced_bull() -> None:
    b0 = _bar(100, 100, 90, 92, 0)
    b2 = _bar(90, 105, 89, 102, 2)
    assert _matches_pattern_type(bullish=True, b0=b0, b2=b2, pattern_type="Enhanced")
    b2n = _bar(90, 99, 89, 95, 2)
    assert not _matches_pattern_type(
        bullish=True, b0=b0, b2=b2n, pattern_type="Enhanced"
    )


def test_resolve_mid_touch_bull() -> None:
    bars = [
        _bar(100, 100, 90, 92, 0),
        _bar(91, 94, 88, 90, 1),
        _bar(90, 105, 89, 102, 2),
        _bar(102, 103, 96, 101, 3),
    ]
    ent = resolve_three_rp_entry(
        bars,
        2,
        direction="up",
        b2=bars[2],
        support=88.0,
        resistance=100.0,
    )
    assert ent == (3, (105 + 89) / 2, "mid_touch")
