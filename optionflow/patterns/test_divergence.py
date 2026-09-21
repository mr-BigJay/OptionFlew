from datetime import datetime, timedelta, timezone

from optionflow.patterns.divergence import (
    EARLY_RIGHT,
    ENTRY_LEG1_WEIGHT,
    ENTRY_LEG2_WEIGHT,
    LOOKBACK_LEFT,
    LOOKBACK_RIGHT,
    RANGE_P1_P3,
    RSI_PERIOD,
    _bearish_ok,
    _bullish_ok,
    _entry_lines,
    _forming_pivot,
    detect_rsi_divergence,
    divergence_rank,
    pick_confirmed_divergence,
)
from optionflow.patterns.indicators import (
    rsi,
    rsi_pivot_high_confirmations,
    rsi_pivot_low_confirmations,
)
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit


def test_constants_match_bigbeluga() -> None:
    assert RSI_PERIOD == 24
    assert LOOKBACK_LEFT == 10
    assert LOOKBACK_RIGHT == 10
    assert EARLY_RIGHT == 2
    assert RANGE_P1_P3 == 120
    assert ENTRY_LEG1_WEIGHT == 0.35
    assert ENTRY_LEG2_WEIGHT == 0.65


def test_consecutive_pivots_not_first_vs_last() -> None:
    """دو pivot RSI آخر با هم مقایسه می‌شوند (مثل valuewhen)."""
    n = 160
    rs: list[float | None] = [45.0 - i * 0.01 for i in range(n)]
    rs[50] = 80.0
    rs[85] = 78.0
    rs[115] = 72.0
    ph = rsi_pivot_high_confirmations(rs, left=10, right=10)
    assert len(ph) >= 2
    _conf_b, p_b = ph[-1]
    _conf_a, p_a = ph[-2]
    assert p_b > p_a
    assert p_a == 85
    assert p_b == 115


def test_rsi_rma_period() -> None:
    closes = [100.0 + i * 0.1 for i in range(40)]
    rs = rsi(closes, RSI_PERIOD)
    assert rs[RSI_PERIOD - 1] is not None
    assert rs[RSI_PERIOD - 2] is None


def test_ohlc_helper_roundtrip() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        OhlcBar(
            ts=t0 + timedelta(minutes=5 * i),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1.0,
        )
        for i in range(10)
    ]
    hit = detect_rsi_divergence(bars, "5m")
    assert hit is None


def test_forming_pivot_needs_two_bars_right() -> None:
    n = 50
    rs: list[float | None] = [40.0 - i * 0.02 for i in range(n)]
    rs[n - 1 - 2] = 78.0
    found = _forming_pivot(rs, high=True, n=n)
    assert found is not None
    p, right = found
    assert p == n - 1 - 2
    assert right == 2


def test_entry_lines_include_early_and_final_prices() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        OhlcBar(
            ts=t0 + timedelta(minutes=5 * i),
            open=65000 + i,
            high=65100 + i,
            low=64900 + i,
            close=65000 + i,
            volume=1.0,
        )
        for i in range(30)
    ]
    p_b = 10
    early_ix, final_ix, early_px, final_px, extra = _entry_lines(
        bars, p_b, early=False
    )
    assert early_ix == 12
    assert final_ix == 20
    assert early_px == 65012
    assert final_px == 65020
    assert "65012" in extra.replace(",", "")
    assert "65020" in extra.replace(",", "")
    _e, fin, _ep, fp, extra_early = _entry_lines(bars, p_b, early=True)
    assert fin is None
    assert fp is None
    assert "اولیه" in extra_early
    assert "پله‌ای" not in extra_early


def test_consecutive_pair_when_no_first_third() -> None:
    rs: list[float | None] = [40.0] * 160
    highs = [100.0] * 160
    p1, p2, p3 = 50, 80, 110
    rs[p1], rs[p2], rs[p3] = 70.0, 75.0, 72.0
    highs[p1], highs[p2], highs[p3] = 100.0, 106.0, 108.0
    pivots = [(p1 + 10, p1), (p2 + 10, p2), (p3 + 10, p3)]
    assert _bearish_ok(rs, highs, p1, p3) is None
    assert _bearish_ok(rs, highs, p2, p3) is not None
    found = pick_confirmed_divergence(pivots, rs, highs, _bearish_ok)
    assert found is not None
    assert found["p_a"] == p2
    assert found["p_c"] == p3
    assert found["p_mid"] is None
    assert found["ladder"] == {}


def test_prefers_consecutive_when_both_valid() -> None:
    rs: list[float | None] = [40.0] * 160
    highs = [100.0] * 160
    p1, p2, p3 = 50, 80, 110
    rs[p1], rs[p2], rs[p3] = 78.0, 74.0, 70.0
    highs[p1], highs[p2], highs[p3] = 100.0, 106.0, 108.0
    pivots = [(p1 + 10, p1), (p2 + 10, p2), (p3 + 10, p3)]
    assert _bearish_ok(rs, highs, p2, p3) is not None
    assert _bearish_ok(rs, highs, p1, p3) is not None
    found = pick_confirmed_divergence(pivots, rs, highs, _bearish_ok)
    assert found is not None
    assert found["p_a"] == p2
    assert found["p_mid"] is None


def test_third_pivot_merges_with_second_when_div_vs_first() -> None:
    rs: list[float | None] = [40.0] * 160
    highs = [100.0] * 160
    p1, p2, p3 = 50, 80, 110
    rs[p1], rs[p2], rs[p3] = 75.0, 70.0, 72.0
    highs[p1], highs[p2], highs[p3] = 100.0, 106.0, 108.0
    pivots = [(p1 + 10, p1), (p2 + 10, p2), (p3 + 10, p3)]
    assert _bearish_ok(rs, highs, p2, p3) is None
    assert _bearish_ok(rs, highs, p1, p3) is not None
    found = pick_confirmed_divergence(pivots, rs, highs, _bearish_ok)
    assert found is not None
    assert found["p_a"] == p1
    assert found["p_c"] == p3
    assert found["p_mid"] == p2
    ladder = found["ladder"]
    assert ladder["entry_pivot_2_index"] == p2
    assert ladder["entry_pivot_3_index"] == p3
    assert ladder["entry_blended_px"] == highs[p2] * 0.35 + highs[p3] * 0.65


def test_older_fourth_pivot_is_ignored() -> None:
    rs: list[float | None] = [40.0] * 200
    highs = [100.0] * 200
    p0, p1, p2, p3 = 20, 50, 80, 110
    rs[p0], rs[p1], rs[p2], rs[p3] = 82.0, 75.0, 70.0, 72.0
    highs[p0], highs[p1], highs[p2], highs[p3] = 90.0, 100.0, 106.0, 108.0
    pivots = [
        (p0 + 10, p0),
        (p1 + 10, p1),
        (p2 + 10, p2),
        (p3 + 10, p3),
    ]
    found = pick_confirmed_divergence(pivots, rs, highs, _bearish_ok)
    assert found is not None
    assert found["p_a"] == p1
    assert found["p_mid"] == p2


def test_bullish_merge_uses_last_three_only() -> None:
    rs: list[float | None] = [60.0] * 160
    lows = [100.0] * 160
    p1, p2, p3 = 50, 80, 110
    rs[p1], rs[p2], rs[p3] = 28.0, 32.0, 30.0
    lows[p1], lows[p2], lows[p3] = 100.0, 94.0, 92.0
    pivots = [(p1 + 10, p1), (p2 + 10, p2), (p3 + 10, p3)]
    assert _bullish_ok(rs, lows, p2, p3) is None
    found = pick_confirmed_divergence(pivots, rs, lows, _bullish_ok)
    assert found is not None
    assert found["p_a"] == p1
    assert found["p_mid"] == p2


def test_entry_lines_append_ladder_when_merged() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        OhlcBar(
            ts=t0 + timedelta(minutes=5 * i),
            open=65000 + i,
            high=65100 + i,
            low=64900 + i,
            close=65000 + i,
            volume=1.0,
        )
        for i in range(30)
    ]
    ladder = {
        "entry_pivot_2_px": 65100.0,
        "entry_pivot_3_px": 65200.0,
    }
    _e, _f, _ep, _fp, extra = _entry_lines(
        bars, 10, early=False, ladder=ladder
    )
    assert "35" in extra
    assert "65" in extra
    assert "پیوت دوم" in extra


def test_divergence_rank_confirmed_beats_early() -> None:
    early = PatternHit(
        category="divergence",
        timeframe="5m",
        pattern_id="rsi_bearish",
        title_fa="",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={"stage": "early", "pivot_b": (110, 1.0)},
    )
    confirmed = PatternHit(
        category="divergence",
        timeframe="5m",
        pattern_id="rsi_bearish",
        title_fa="",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={"stage": "confirmed", "pivot_b": (110, 1.0)},
    )
    assert divergence_rank(confirmed) > divergence_rank(early)
