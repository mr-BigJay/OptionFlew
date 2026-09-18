from datetime import datetime, timedelta, timezone

from optionflow.patterns.divergence import (
    EARLY_RIGHT,
    LOOKBACK_LEFT,
    LOOKBACK_RIGHT,
    MIN_PRICE_PCT,
    MIN_RSI_DIFF,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    _entry_lines,
    _forming_pivot,
    detect_rsi_divergence,
)
from optionflow.patterns.indicators import (
    rsi,
    rsi_pivot_high_confirmations,
    rsi_pivot_low_confirmations,
)
from optionflow.patterns.ohlc import OhlcBar


def test_constants_match_tv() -> None:
    assert LOOKBACK_LEFT == 5
    assert LOOKBACK_RIGHT == 5
    assert EARLY_RIGHT == 2
    assert MIN_RSI_DIFF == 3.0
    assert RSI_OVERBOUGHT == 65.0
    assert RSI_OVERSOLD == 35.0
    assert MIN_PRICE_PCT == 0.0012


def test_consecutive_pivots_not_first_vs_last() -> None:
    """اگر بیش از دو سقف RSI باشد، فقط دو تای آخر باید با هم مقایسه شوند."""
    n = 120
    rs: list[float | None] = [45.0 - i * 0.01 for i in range(n)]
    rs[40] = 80.0
    rs[70] = 78.0
    rs[95] = 72.0
    ph = rsi_pivot_high_confirmations(rs, left=5, right=5)
    assert len(ph) >= 2
    _conf_b, p_b = ph[-1]
    _conf_a, p_a = ph[-2]
    assert p_b > p_a
    assert p_a != 40 or p_b != 95
    # last two should be the later pair, not first-to-last
    assert p_a == 70
    assert p_b == 95


def test_rsi_rma_period() -> None:
    closes = [100.0 + i * 0.1 for i in range(40)]
    rs = rsi(closes)
    assert rs[13] is not None
    assert rs[12] is None


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
    n = 40
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
        for i in range(20)
    ]
    p_b = 10
    early_ix, final_ix, early_px, final_px, extra = _entry_lines(
        bars, p_b, early=False
    )
    assert early_ix == 12
    assert final_ix == 15
    assert early_px == 65012
    assert final_px == 65015
    assert "65012" in extra.replace(",", "")
    assert "65015" in extra.replace(",", "")
    _e, fin, _ep, fp, extra_early = _entry_lines(bars, p_b, early=True)
    assert fin is None
    assert fp is None
    assert "هنوز" in extra_early
