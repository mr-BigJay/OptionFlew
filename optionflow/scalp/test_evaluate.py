from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit
from optionflow.scalp.evaluate import evaluate_scalp_path


def _bars(prices: list[float]) -> list[OhlcBar]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out: list[OhlcBar] = []
    for i, c in enumerate(prices):
        out.append(
            OhlcBar(
                ts=t0 + timedelta(minutes=5 * i),
                open=c,
                high=c + 50,
                low=c - 50,
                close=c,
                volume=1.0,
            )
        )
    return out


def test_scalp_stop_before_tp_long() -> None:
    prices = [100_000.0, 100_100.0, 99_800.0, 100_500.0]
    bars = _bars(prices)
    bars[2] = OhlcBar(
        bars[2].ts, 100_050, 100_080, 99_750, 99_800, 1.0
    )
    hit = PatternHit(
        category="scalp",
        timeframe="5m",
        pattern_id="scalp_test",
        title_fa="t",
        status_fa="s",
        summary_fa="",
        forecast_fa="",
        meta={
            "direction": "up",
            "entry_px": 100_100.0,
            "stop_px": 99_900.0,
            "tp_px": 100_400.0,
            "entry_index": 1,
            "max_hold_bars": 10,
        },
    )
    ok, note = evaluate_scalp_path(bars, hit, bar_index=1)
    assert ok is False
    assert "استاپ" in note


def test_scalp_hits_tp_long() -> None:
    prices = [100_000.0, 100_100.0, 100_350.0]
    bars = _bars(prices)
    bars[2] = OhlcBar(
        bars[2].ts, 100_200, 100_450, 100_150, 100_350, 1.0
    )
    hit = PatternHit(
        category="scalp",
        timeframe="5m",
        pattern_id="scalp_test",
        title_fa="t",
        status_fa="s",
        summary_fa="",
        forecast_fa="",
        meta={
            "direction": "up",
            "entry_px": 100_100.0,
            "stop_px": 99_900.0,
            "tp_px": 100_400.0,
            "entry_index": 1,
            "max_hold_bars": 10,
        },
    )
    ok, _ = evaluate_scalp_path(bars, hit, bar_index=1)
    assert ok is True
