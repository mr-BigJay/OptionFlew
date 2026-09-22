from datetime import datetime, timedelta, timezone

from optionflow.patterns.meaningful_behavior import (
    MIN_BURST_BTC,
    SURGE_RATIO,
    _flow_target_price,
    _surge_ok,
    behavior_forecast_fa,
    evaluate_behavior_path,
)
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit


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


def test_behavior_path_reaches_strike_target() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    px = 86000.0
    tp = 86500.0
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
        meta={
            "direction": "up",
            "entry_index": 0,
            "dominant_strikes": [(86500.0, 120.0), (87000.0, 40.0)],
        },
    )
    ok, _ = evaluate_behavior_path(bars, hit)
    assert ok is True
    assert hit.meta["tp_px"] == tp
    assert hit.meta["exit_index"] == 3


def test_put_surge_target_is_below_spot() -> None:
    spot = 85_901.0
    top = [(88_000.0, 400.0), (79_000.0, 250.0)]
    meta = {"direction": "down", "dominant_strikes": top}
    tp, label = _flow_target_price(meta, spot)
    assert tp == 79_000.0
    text = behavior_forecast_fa(
        direction="down",
        spot=spot,
        tp_px=tp,
        strikes=[88_000.0, 79_000.0],
        pattern_id="put_surge",
    )
    assert "نزول" in text or "پایین" in text
    assert "79,000" in text
    assert "88,000" in text
    assert "بیمه" in text or "ضرر" in text


def test_put_path_eval_down_to_strike() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entry = 86_000.0
    tp = 79_000.0
    bars = [
        OhlcBar(
            ts=t0 + timedelta(hours=i),
            open=entry,
            high=entry + 200,
            low=entry - 200,
            close=entry,
            volume=1.0,
        )
        for i in range(4)
    ]
    bars.append(
        OhlcBar(
            ts=t0 + timedelta(hours=4),
            open=82_000,
            high=82_500,
            low=78_500,
            close=79_500,
            volume=1.0,
        )
    )
    hit = PatternHit(
        category="meaningful_behavior",
        timeframe="1h",
        pattern_id="put_surge",
        title_fa="t",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={
            "direction": "down",
            "entry_index": 0,
            "dominant_strikes": [(88_000.0, 400.0), (79_000.0, 250.0)],
        },
    )
    ok, note = evaluate_behavior_path(bars, hit)
    assert ok is True
    assert hit.meta["tp_px"] == tp
    assert "79" in note
