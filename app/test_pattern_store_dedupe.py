from optionflow.patterns.types import PatternHit

from app.pattern_store import event_key_for_hit, pattern_content_signature


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


def test_triangle_key_stable_when_channel_lines_drift() -> None:
    sk = "ascending:H100000-100020:L98400-98900-99350"
    meta_forming = {
        "kind": "ascending",
        "stage": "forming",
        "structure_key": sk,
        "upper_now": 100_012.3,
        "lower_now": 99_401.7,
    }
    meta_forming_later = {
        **meta_forming,
        "upper_now": 100_048.9,
        "lower_now": 99_428.1,
        "confirm_index": 999,
    }
    hit_a = PatternHit(
        category="triangle",
        timeframe="1h",
        pattern_id="triangle_ascending",
        title_fa="t",
        status_fa="s",
        summary_fa="",
        forecast_fa="",
        meta=meta_forming,
    )
    hit_b = PatternHit(
        category="triangle",
        timeframe="1h",
        pattern_id="triangle_ascending",
        title_fa="t",
        status_fa="s",
        summary_fa="",
        forecast_fa="",
        meta=meta_forming_later,
    )
    assert event_key_for_hit(hit_a) == event_key_for_hit(hit_b)


def test_triangle_signature_uses_structure_key() -> None:
    sig = pattern_content_signature(
        category="triangle",
        pattern_id="triangle_symmetrical",
        meta={
            "stage": "forming",
            "structure_key": "symmetrical:H102800-102000-101300:L97600-98300-99000",
            "upper_now": 100_500,
            "lower_now": 99_800,
        },
    )
    assert "symmetrical:H102800" in sig
    assert "100500" not in sig
