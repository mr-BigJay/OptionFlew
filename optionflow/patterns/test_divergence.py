from datetime import datetime, timedelta, timezone

from optionflow.patterns.divergence import (
    EARLY_RIGHT,
    ENTRY_LEG1_WEIGHT,
    ENTRY_LEG2_WEIGHT,
    LOOKBACK_LEFT,
    LOOKBACK_RIGHT,
    RSI_PERIOD,
    _bearish_ok,
    _best_bearish_pair,
    _entry_ladder,
    _entry_lines,
    _forming_pivot,
    detect_rsi_divergence,
)
from optionflow.patterns.indicators import (
    rsi,
    rsi_pivot_high_confirmations,
)
from optionflow.patterns.ohlc import OhlcBar


def test_constants_match_bigbeluga() -> None:
    assert RSI_PERIOD == 24
    assert LOOKBACK_LEFT == 10
    assert LOOKBACK_RIGHT == 10
    assert EARLY_RIGHT == 2
    assert ENTRY_LEG1_WEIGHT == 0.35
    assert ENTRY_LEG2_WEIGHT == 0.65


def test_pivot1_to_pivot3_allows_wide_gap() -> None:
    from optionflow.patterns.divergence import _best_bullish_pair, _gap_ok

    assert _gap_ok(50, 180, adjacent=False) is True
    assert _gap_ok(50, 180, adjacent=True) is False
    rs: list[float | None] = [40.0] * 250
    lows = [100.0] * 250
    rs[50] = 74.0
    rs[120] = 70.0
    rs[180] = 77.0
    lows[50] = 100.0
    lows[120] = 106.0
    lows[180] = 98.0
    pivots = [(60, 50), (130, 120), (190, 180)]
    found = _best_bullish_pair(rs, lows, pivots, 180)
    assert found is not None
    assert found[0] == 50


def test_compare_order_prefers_first_on_third_pivot() -> None:
    from optionflow.patterns.divergence import _compare_order

    pivots = [(60, 50), (120, 100), (180, 150)]
    order = _compare_order(pivots, 150)
    assert order[0] == 50
    assert order[1] == 100


def test_third_pivot_can_diverge_with_first_not_second() -> None:
    rs: list[float | None] = [40.0] * 200
    highs = [100.0 + i * 0.1 for i in range(200)]
    p1, p2, p3 = 50, 80, 110
    rs[p1] = 75.0
    rs[p2] = 70.0
    rs[p3] = 72.0
    highs[p1] = 100.0
    highs[p2] = 106.0
    highs[p3] = 108.0
    pivots = [(p1 + 10, p1), (p2 + 10, p2), (p3 + 10, p3)]
    assert _bearish_ok(rs, highs, p2, p3) is None
    found = _best_bearish_pair(rs, highs, pivots, p3)
    assert found is not None
    p_a, p_c, _ra, _rb = found
    assert p_a == p1
    assert p_c == p3


def test_entry_ladder_two_pivots_only_35_percent() -> None:
    prices = [100.0] * 120
    prices[80] = 105.0
    pivots = [(60, 50), (90, 80)]
    ladder = _entry_ladder(pivots, 80, prices)
    assert ladder["entry_pivot_2_index"] == 80
    assert ladder["entry_pivot_3_index"] is None
    assert ladder["entry_blended_px"] == 105.0


def test_entry_ladder_three_pivots_blended() -> None:
    prices = [100.0] * 140
    prices[80] = 102.0
    prices[110] = 104.0
    pivots = [(60, 50), (90, 80), (120, 110)]
    ladder = _entry_ladder(pivots, 110, prices)
    assert ladder["entry_pivot_2_index"] == 80
    assert ladder["entry_pivot_3_index"] == 110
    assert ladder["entry_blended_px"] == 102.0 * 0.35 + 104.0 * 0.65


def test_consecutive_pivots_compare_latest_with_older() -> None:
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


def test_entry_lines_include_ladder_text() -> None:
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
    _early_ix, final_ix, _ep, final_px, extra = _entry_lines(
        bars, 10, early=False, ladder=ladder
    )
    assert final_ix == 20
    assert final_px == 65020
    assert "pivot سوم" in extra
