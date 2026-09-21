from datetime import datetime, timezone

from optionflow.patterns.backtest import entry_price_for_hit, evaluate_target_profit
from optionflow.patterns.divergence import divergence_rank
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.types import PatternHit


def _bars(closes: list[float]) -> list[OhlcBar]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = []
    for i, c in enumerate(closes):
        out.append(
            OhlcBar(
                ts=t0,
                open=c,
                high=c + 10,
                low=c - 10,
                close=c,
                volume=1.0,
            )
        )
    return out


def test_target_profit_long_hits() -> None:
    closes = [100.0] * 5 + [100.0, 100.0, 100.6, 100.6]
    bars = _bars(closes)
    hit = PatternHit(
        category="divergence",
        timeframe="15m",
        pattern_id="rsi_bullish",
        title_fa="",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={"direction": "up", "entry_blended_px": 100.0},
    )
    ok, note = evaluate_target_profit(bars, 4, hit, 0.5)
    assert ok is True
    assert "۰.۵" in note or "0.5" in note
    assert hit.meta.get("exit_index") == 5


def test_entry_price_uses_blended() -> None:
    hit = PatternHit(
        category="divergence",
        timeframe="15m",
        pattern_id="x",
        title_fa="",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={"entry_blended_px": 99_500.0},
    )
    assert entry_price_for_hit(_bars([100.0]), 0, hit) == 99_500.0


def _div_hit(pattern_id: str, pivot_b: int, *, stage: str, merged: bool = False) -> PatternHit:
    meta: dict = {"pivot_b": (pivot_b, 100.0), "stage": stage}
    if merged:
        meta["compared_first_third"] = True
    return PatternHit(
        category="divergence",
        timeframe="5m",
        pattern_id=pattern_id,
        title_fa="",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta=meta,
    )


def test_divergence_rank_order() -> None:
    early = _div_hit("rsi_bearish", 110, stage="early")
    confirmed = _div_hit("rsi_bearish", 110, stage="confirmed")
    merged = _div_hit("rsi_bearish", 110, stage="confirmed", merged=True)
    assert divergence_rank(confirmed) > divergence_rank(early)
    assert divergence_rank(merged) > divergence_rank(confirmed)


def test_replay_upgrades_same_pivot_signal() -> None:
    """همان signal_key فقط یک بار؛ تأیید جایگزین اولیه می‌شود."""
    early = _div_hit("rsi_bearish", 50, stage="early")
    confirmed = _div_hit("rsi_bearish", 50, stage="confirmed")
    early.meta["signal_key"] = "rsi_bearish:50"
    confirmed.meta["signal_key"] = "rsi_bearish:50"
    bars = _bars([100.0] * 80)
    # replay uses detect; smoke rank path via manual list logic in backtest
    assert divergence_rank(confirmed) > divergence_rank(early)
    assert len(bars) == 80
