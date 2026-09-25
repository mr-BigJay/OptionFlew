from __future__ import annotations

from datetime import datetime, timezone

from optionflow.patterns.backtest import (
    divergence_entry_index,
    evaluate_divergence_target_profit,
)
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit


def _bars(closes: list[float]) -> list[OhlcBar]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out: list[OhlcBar] = []
    for i, c in enumerate(closes):
        out.append(
            OhlcBar(
                ts=t0,
                open=c,
                high=c + 50,
                low=c - 50,
                close=c,
                volume=1.0,
            )
        )
    return out


def _bullish_hit(*, pivot_low: float, entry_i: int) -> PatternHit:
    return PatternHit(
        category="divergence",
        timeframe="5m",
        pattern_id="rsi_bullish",
        title_fa="",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={
            "direction": "up",
            "stage": "confirmed",
            "pivot_a": (10, pivot_low + 200),
            "pivot_b": (30, pivot_low),
            "final_index": entry_i,
            "early_index": entry_i - 9,
            "confirm_index": entry_i,
        },
    )


def test_divergence_entry_on_early_uses_early_index() -> None:
    hit = _bullish_hit(pivot_low=99_800.0, entry_i=40)
    assert divergence_entry_index(hit, entry_on_early=False) == 40
    assert divergence_entry_index(hit, entry_on_early=True) == 31


def test_divergence_fails_when_pivot_low_breaks_before_target() -> None:
    entry_i = 40
    entry_px = 100_000.0
    pivot_low = 99_800.0
    closes = [entry_px] * (entry_i + 1)
    closes += [99_700.0, 99_650.0]
    closes += [100_600.0] * 40
    bars = _bars(closes)
    hit = _bullish_hit(pivot_low=pivot_low, entry_i=entry_i)
    ok, note = evaluate_divergence_target_profit(
        bars, entry_i, hit, 0.5, timeframe="5m"
    )
    assert ok is False
    assert "شکست کف" in note


def test_divergence_fails_on_stop_loss_before_target() -> None:
    entry_i = 20
    entry_px = 100_000.0
    closes = [entry_px] * (entry_i + 1)
    closes += [99_400.0]
    closes += [100_600.0] * 10
    bars = _bars(closes)
    hit = _bullish_hit(pivot_low=99_900.0, entry_i=entry_i)
    ok, note = evaluate_divergence_target_profit(
        bars, entry_i, hit, 0.5, timeframe="5m", stop_loss_pct=0.5
    )
    assert ok is False
    assert "استاپ" in note


def test_divergence_fails_if_target_only_after_forward_window() -> None:
    entry_i = 20
    entry_px = 100_000.0
    closes = [entry_px] * (entry_i + 1)
    closes += [100_050.0] * 50
    closes += [100_600.0]
    bars = _bars(closes)
    hit = _bullish_hit(pivot_low=99_900.0, entry_i=entry_i)
    ok, note = evaluate_divergence_target_profit(
        bars, entry_i, hit, 0.5, timeframe="5m"
    )
    assert ok is False
    assert "36 کندل" in note


def test_divergence_success_when_target_within_window() -> None:
    entry_i = 20
    entry_px = 100_000.0
    closes = [entry_px] * (entry_i + 1)
    closes += [100_200.0, 100_600.0]
    bars = _bars(closes)
    hit = _bullish_hit(pivot_low=99_900.0, entry_i=entry_i)
    ok, note = evaluate_divergence_target_profit(
        bars, entry_i, hit, 0.5, timeframe="5m"
    )
    assert ok is True
    assert "بستن در سود" in note
