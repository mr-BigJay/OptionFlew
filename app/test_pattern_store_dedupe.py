from optionflow.patterns.types import PatternHit

from app.pattern_store import event_key_for_hit, pattern_content_signature, _dedupe_event_rows


def test_divergence_key_stable_when_confirm_index_shifts() -> None:
    meta_base = {
        "pivot_a": (10, 85262.0),
        "pivot_b": (40, 85999.0),
        "rsi_a": 75.6,
        "rsi_b": 70.8,
        "stage": "confirmed",
        "confirm_index": 195,
    }
    hit_a = PatternHit(
        category="divergence",
        timeframe="5m",
        pattern_id="rsi_bearish",
        title_fa="t",
        status_fa="s",
        summary_fa="",
        forecast_fa="",
        meta=dict(meta_base),
    )
    meta_b = dict(meta_base, confirm_index=199, entry_index=198)
    hit_b = PatternHit(
        category="divergence",
        timeframe="5m",
        pattern_id="rsi_bearish",
        title_fa="t",
        status_fa="s",
        summary_fa="",
        forecast_fa="",
        meta=meta_b,
    )
    assert event_key_for_hit(hit_a) == event_key_for_hit(hit_b)


def test_divergence_signature_uses_pivots() -> None:
    sig = pattern_content_signature(
        category="divergence",
        pattern_id="rsi_bearish",
        meta={
            "pivot_a": [10, 85262],
            "pivot_b": [40, 85999],
            "rsi_a": 75.6,
            "rsi_b": 70.8,
            "stage": "confirmed",
        },
    )
    assert "85999" in sig or "86000" in sig
    assert "confirmed" in sig


def test_trendline_same_line_collapses_when_price_drifts() -> None:
    def row(y: float, created: str) -> dict:
        return {
            "category": "trendline",
            "timeframe": "5m",
            "pattern_id": "trendline_low_early",
            "created_at": created,
            "meta": {
                "stage": "early",
                "side": "low",
                "y_now": y,
                "window_offset": 400,
                "touch_lows": [10, 40, 70],
                "touch_highs": [],
            },
        }

    rows = _dedupe_event_rows(
        [row(83426.0, "2026-09-24T12:17:00Z"), row(83424.0, "2026-09-24T12:00:00Z")]
    )
    assert len(rows) == 1
    assert rows[0]["meta"]["y_now"] == 83426.0
    a = PatternHit(
        category="trendline",
        timeframe="5m",
        pattern_id="trendline_low_early",
        title_fa="",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta=rows[0]["meta"],
    )
    b = PatternHit(
        category="trendline",
        timeframe="5m",
        pattern_id="trendline_low_early",
        title_fa="",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={**rows[0]["meta"], "y_now": 83424.0},
    )
    assert event_key_for_hit(a) == event_key_for_hit(b)
