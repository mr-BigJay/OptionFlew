from __future__ import annotations

from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar
from optionflow.nabzbours.strategy import (
    TradeStat,
    evaluate_entry,
    macd_lines,
    merge_config,
    session_vwap_at,
    summarize_trades,
)


def _bars(n: int, start: float, step: float) -> list[OhlcBar]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = []
    px = start
    for i in range(n):
        px += step
        out.append(
            OhlcBar(
                ts=t0 + timedelta(minutes=5 * i),
                open=px - 1,
                high=px + 2,
                low=px - 2,
                close=px,
                volume=10 + i,
            )
        )
    return out


def test_vwap_and_macd_defined() -> None:
    bars = _bars(80, 100, 0.4)
    assert session_vwap_at(bars, 40) is not None
    line, sig, hist = macd_lines([b.close for b in bars])
    assert line[-1] is not None and sig[-1] is not None and hist[-1] is not None


def test_long_setup_on_rising_series() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    px = 100.0
    for i in range(160):
        if i % 17 < 4:
            px -= 0.6
        else:
            px += 1.1
        bars.append(
            OhlcBar(
                ts=t0 + timedelta(minutes=5 * i),
                open=px - 0.4,
                high=px + 0.8,
                low=px - 0.8,
                close=px,
                volume=20,
            )
        )
    cfg = merge_config(
        {
            "require_higher_tf": False,
            "use_divergence": False,
            "min_score": 4,
            "ema_length": 20,
            "pivot_left": 3,
            "pivot_right": 3,
        }
    )
    setup = None
    for i in range(80, len(bars)):
        setup = evaluate_entry(bars, i, cfg, higher_bars=None)
        if setup is not None:
            break
    assert setup is not None
    assert setup.direction == "long"
    assert setup.score >= 3
    assert "LONG SIGNAL" in setup.log
    assert "Score:" in setup.log


def test_short_not_on_rising_series() -> None:
    bars = _bars(120, 100, 0.8)
    cfg = merge_config({"require_higher_tf": False, "long_trades": False, "min_score": 3})
    setup = evaluate_entry(bars, len(bars) - 1, cfg)
    assert setup is None


def test_summary_stats() -> None:
    trades = [
        TradeStat("long", 1.5, True, "", "", "tp"),
        TradeStat("short", -1.0, False, "", "", "sl"),
        TradeStat("long", 0.5, True, "", "", "tp"),
    ]
    s = summarize_trades(trades)
    assert s["trades"] == 3
    assert s["longs"] == 2
    assert s["shorts"] == 1
    assert "برد" in s["text"]
