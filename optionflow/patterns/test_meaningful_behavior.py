from optionflow.patterns.meaningful_behavior import (
    MIN_BURST_BTC,
    SURGE_RATIO,
    _surge_ok,
    evaluate_behavior_path,
)
from optionflow.patterns.types import PatternHit
from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar


def test_surge_requires_min_burst() -> None:
    assert not _surge_ok(10.0, 50.0, 55.0, 5.0)
    assert _surge_ok(MIN_BURST_BTC * 1.5, 20.0, 55.0, 5.0)


def test_surge_ratio() -> None:
    baseline = 30.0
    minutes = 50.0
    burst_min = 5.0
    base_rate = baseline / minutes
    need = max(MIN_BURST_BTC * 1.5, base_rate * burst_min * SURGE_RATIO + 1)
    assert _surge_ok(need, baseline, minutes, burst_min)


def test_behavior_path_tp_short() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    px = 86000.0
    bars = [
        OhlcBar(
            ts=t0 + timedelta(hours=i),
            open=px,
            high=px + 100,
            low=px - 100,
            close=px,
            volume=1.0,
        )
        for i in range(3)
    ]
    tp = px * 1.005
    bars.append(
        OhlcBar(
            ts=t0 + timedelta(hours=3),
            open=px,
            high=tp + 10,
            low=px,
            close=tp,
            volume=1.0,
        )
    )
    hit = PatternHit(
        category="meaningful_behavior",
        timeframe="1h",
        pattern_id="call_surge",
        title_fa="t",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={"direction": "up", "entry_index": 0},
    )
    ok, _ = evaluate_behavior_path(bars, hit)
    assert ok is True
    assert hit.meta["exit_index"] == 3
