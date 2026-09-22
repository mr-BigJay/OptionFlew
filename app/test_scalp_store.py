from optionflow.patterns.types import PatternHit

from app.scalp_store import event_key_for_scalp


def test_scalp_event_key_stable_on_line_drift() -> None:
    meta = {
        "scenario_id": "range_break",
        "setup_key": "up:100000:99400",
        "entry_px": 100_012,
        "stop_px": 99_380,
        "tp_px": 100_560,
    }
    a = PatternHit(
        category="scalp",
        timeframe="5m",
        pattern_id="scalp_range_break",
        title_fa="t",
        status_fa="s",
        summary_fa="",
        forecast_fa="",
        meta=dict(meta),
    )
    b = PatternHit(
        category="scalp",
        timeframe="5m",
        pattern_id="scalp_range_break",
        title_fa="t",
        status_fa="s",
        summary_fa="",
        forecast_fa="",
        meta={**meta, "entry_px": 100_048, "tp_px": 100_590},
    )
    assert event_key_for_scalp(a) == event_key_for_scalp(b)
