from datetime import datetime, timedelta, timezone

from optionflow.patterns.divergence import (
    LOOKBACK_LEFT,
    LOOKBACK_RIGHT,
    RANGE_LOWER,
    RANGE_UPPER,
    RSI_PERIOD,
    _bearish_ok,
    _bullish_ok,
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


def test_bearish_regular_conditions() -> None:
    rs: list[float | None] = [40.0] * 120
    highs = [100.0] * 120
    rs[50], rs[80] = 75.0, 70.0
    highs[50], highs[80] = 100.0, 105.0
    ok = _bearish_ok(rs, highs, 50, 80)
    assert ok == (75.0, 70.0)


def test_bullish_regular_conditions() -> None:
    rs: list[float | None] = [40.0] * 120
    lows = [100.0] * 120
    rs[50], rs[80] = 30.0, 35.0
    lows[50], lows[80] = 100.0, 95.0
    ok = _bullish_ok(rs, lows, 50, 80)
    assert ok == (30.0, 35.0)
