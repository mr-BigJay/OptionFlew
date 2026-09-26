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


def test_triangle_entry_waits_for_two_closes() -> None:
    from app.paper_engine import pattern_hit_allows_entry

    def hit(stage: str, held: bool) -> PatternHit:
        return PatternHit(
            category="triangle",
            timeframe="15m",
            pattern_id="triangle_descending",
            title_fa="مثلث",
            status_fa="",
            summary_fa="",
            forecast_fa="",
            meta={"direction": "up", "stage": stage, "held": held},
        )

    assert pattern_hit_allows_entry(hit("breakout", False)) is False
    assert pattern_hit_allows_entry(hit("fakeout", False)) is False
    assert pattern_hit_allows_entry(hit("breakout", True)) is True


def test_trendline_entry_requires_a_touch() -> None:
    from app.paper_engine import pattern_hit_allows_entry

    away = PatternHit(
        category="trendline",
        timeframe="5m",
        pattern_id="trendline_low_early",
        title_fa="ترندلاین حمایت",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={"direction": "up", "testing": False, "y_now": 83000},
    )
    touched = PatternHit(
        category="trendline",
        timeframe="5m",
        pattern_id="trendline_low_early",
        title_fa="ترندلاین حمایت",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={"direction": "up", "testing": True, "y_now": 83000},
    )
    assert pattern_hit_allows_entry(away) is False
    assert pattern_hit_allows_entry(touched) is True
    confirmed_no_touch = PatternHit(
        category="trendline",
        timeframe="5m",
        pattern_id="trendline_high_confirmed",
        title_fa="t",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={"direction": "down", "stage": "confirmed", "testing": False},
    )
    assert pattern_hit_allows_entry(confirmed_no_touch, {"pattern_early": []}) is False
    assert pattern_hit_allows_entry(confirmed_no_touch, {"pattern_early": ["trendline"]}) is False
    early = PatternHit(
        category="trendline",
        timeframe="5m",
        pattern_id="trendline_low_early",
        title_fa="t",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={"testing": True, "stage": "early"},
    )
    final = PatternHit(
        category="trendline",
        timeframe="5m",
        pattern_id="trendline_low_confirmed",
        title_fa="t",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta={"testing": True, "stage": "confirmed"},
    )
    assert pattern_hit_allows_entry(early, {"pattern_early": ["trendline"]}) is True
    assert pattern_hit_allows_entry(final, {"pattern_early": ["trendline"]}) is False
    assert pattern_hit_allows_entry(early, {"pattern_early": []}) is False
    assert pattern_hit_allows_entry(final, {"pattern_early": []}) is True


def test_trendline_entry_price_is_the_line_not_the_close() -> None:
    from app.paper_engine import trendline_entry_price

    assert trendline_entry_price({"y_now": 83976.4, "last_close": 84217}) == 83976.4
    assert trendline_entry_price({}) is None
