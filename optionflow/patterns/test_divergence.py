from datetime import datetime, timedelta, timezone

from optionflow.patterns.divergence import (
    EARLY_RIGHT,
    LOOKBACK_LEFT,
    LOOKBACK_RIGHT,
    RANGE_LOWER,
    RANGE_UPPER,
    RSI_PERIOD,
    _bearish_ok,
    _bullish_ok,
    _entry_lines,
    _forming_pivot,
    detect_rsi_divergence,
)
from optionflow.patterns.indicators import (
    rsi,
    rsi_pivot_high_confirmations,
)
from optionflow.patterns.ohlc import OhlcBar


def test_constants_match_pine() -> None:
    assert RSI_PERIOD == 24
    assert LOOKBACK_LEFT == 10
    assert LOOKBACK_RIGHT == 10
    assert EARLY_RIGHT == 1
    assert RANGE_LOWER == 5
    assert RANGE_UPPER == 60


def test_consecutive_pivots_only() -> None:
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


def test_forming_pivot_needs_one_bar_right() -> None:
    n = 50
    rs: list[float | None] = [40.0 - i * 0.02 for i in range(n)]
    rs[n - 1 - 1] = 78.0
    found = _forming_pivot(rs, high=True, n=n)
    assert found is not None
    p, right = found
    assert p == n - 1 - 1
    assert right == 1
    rs_unconfirmed = [40.0 - i * 0.02 for i in range(n)]
    rs_unconfirmed[-1] = 78.0
    assert _forming_pivot(rs_unconfirmed, high=True, n=n) is None


def test_bearish_regular_conditions() -> None:
    rs: list[float | None] = [40.0] * 120
    highs = [100.0] * 120
    rs[50], rs[80] = 75.0, 70.0
    highs[50], highs[80] = 100.0, 105.0
    assert _bearish_ok(rs, highs, 50, 80) == (75.0, 70.0)


def test_entry_lines_early_and_final() -> None:
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
    early_ix, final_ix, early_px, final_px, extra = _entry_lines(
        bars, 10, early=False
    )
    assert early_ix == 11
    assert final_ix == 20
    assert final_px == 65020
    assert "BigBeluga" in extra or "نهایی" in extra
    _e, fin, _ep, fp, extra_early = _entry_lines(bars, 10, early=True)
    assert fin is None
    assert fp is None
    assert "اولیه" in extra_early


def test_short_bars_no_hit() -> None:
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
    assert detect_rsi_divergence(bars, "5m") is None
