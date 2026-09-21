from datetime import datetime, timedelta, timezone

from optionflow.patterns.divergence import (
    EARLY_RIGHT,
    LOOKBACK_LEFT,
    LOOKBACK_RIGHT,
    MAX_PREV_PIVOTS,
    RANGE_LOWER,
    RANGE_UPPER,
    RSI_PERIOD,
    _entry_lines,
    _find_bearish_ref,
    _forming_pivot,
    _scan_bearish_prev,
    detect_rsi_divergence,
)
from optionflow.patterns.indicators import (
    rsi,
    rsi_pivot_high_confirmations,
    rsi_pivot_low_confirmations,
)
from optionflow.patterns.ohlc import OhlcBar


def test_constants_match_bigbeluga() -> None:
    assert RSI_PERIOD == 24
    assert LOOKBACK_LEFT == 10
    assert LOOKBACK_RIGHT == 10
    assert EARLY_RIGHT == 2
    assert MAX_PREV_PIVOTS == 2
    assert RANGE_LOWER == 5
    assert RANGE_UPPER == 60


def test_multi_pivot_prefers_newer_ref() -> None:
    rs: list[float | None] = [40.0] * 160
    highs = [100.0] * 160
    p1, p2, p3 = 50, 80, 110
    rs[p1], rs[p2], rs[p3] = 75.0, 70.0, 72.0
    highs[p1], highs[p2], highs[p3] = 100.0, 106.0, 108.0
    pivots = [(60, p1), (90, p2), (120, p3)]
    assert _scan_bearish_prev(pivots[:-1], p3, rs, highs) is None
    found = _find_bearish_ref(pivots, rs, highs)
    assert found is not None
    p_a, p_c, _ra, _rb = found
    assert p_a == p1
    assert p_c == p3


def test_multi_pivot_uses_immediate_prev_when_valid() -> None:
    rs: list[float | None] = [40.0] * 160
    highs = [100.0] * 160
    p1, p2, p3 = 50, 80, 110
    rs[p1], rs[p2], rs[p3] = 78.0, 74.0, 70.0
    highs[p1], highs[p2], highs[p3] = 100.0, 106.0, 108.0
    pivots = [(60, p1), (90, p2), (120, p3)]
    found = _find_bearish_ref(pivots, rs, highs)
    assert found is not None
    assert found[0] == p2


def test_consecutive_pivots_not_first_vs_last() -> None:
    """فقط دو pivot RSI آخر با هم مقایسه می‌شوند (مثل valuewhen)."""
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
