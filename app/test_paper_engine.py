from optionflow.patterns.types import PatternHit


def test_try_open_requires_direction_in_meta() -> None:
    from app.paper_engine import try_open_from_pattern_hit

    hit = PatternHit(
        category="trendline",
        timeframe="1h",
        pattern_id="t",
        title_fa="t",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={},
    )
    assert try_open_from_pattern_hit(999_999, hit) is None
