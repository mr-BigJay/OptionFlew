from app.position_store import (
    close_position,
    deposit,
    get_config,
    get_wallet,
    has_open_pattern_category,
    init_position_db,
    insert_open_position,
    pattern_timeframes_from_form,
    save_config,
    selected_timeframes,
)


def test_has_open_pattern_category_blocks_duplicate() -> None:
    init_position_db()
    uid = 9999202
    deposit(uid, 1000.0)
    cfg = get_config(uid)
    assert has_open_pattern_category(uid, "trendline") is False
    pid = insert_open_position(
        uid,
        source_type="pattern",
        source_key="trendline:1h:abc",
        timeframe="1h",
        direction="long",
        entry_price=100_000.0,
        margin_usdt=50.0,
        leverage=5.0,
        fee_rate=float(cfg["fee_rate"]),
        sl_pct=1.0,
        tp_pct=0.5,
        signal_title="ترند",
    )
    assert pid is not None
    assert has_open_pattern_category(uid, "trendline") is True
    assert has_open_pattern_category(uid, "triangle") is False


def test_paper_open_close_long_tp() -> None:
    init_position_db()
    uid = 99991
    deposit(uid, 500.0)
    cfg = get_config(uid)
    pid = insert_open_position(
        uid,
        source_type="pattern",
        source_key="test:1",
        timeframe="1h",
        direction="long",
        entry_price=100_000.0,
        margin_usdt=100.0,
        leverage=5.0,
        fee_rate=float(cfg["fee_rate"]),
        sl_pct=1.0,
        tp_pct=0.5,
        signal_title="تست",
    )
    assert pid is not None
    ok = close_position(
        uid,
        pid,
        exit_price=100_500.0,
        status="closed_tp",
        fee_rate=float(cfg["fee_rate"]),
    )
    assert ok is True
    w = get_wallet(uid)
    assert float(w["balance_usdt"]) > 400.0


def test_pattern_timeframe_form_and_defaults() -> None:
    parsed = pattern_timeframes_from_form(
        ["trendline|1h", "trendline|5m", "three_rp|5m", "three_rp|1h", "flag|15m"]
    )
    assert parsed["trendline"] == ["5m", "1h"]
    assert parsed["three_rp"] == ["1h"]
    assert parsed["flag"] == ["15m"]
    assert parsed["meaningful_behavior"] == []
    assert selected_timeframes({}, "ema50") == ["5m", "15m", "1h"]
    assert selected_timeframes({"pattern_timeframes": parsed}, "flag") == ["15m"]
    assert selected_timeframes({"pattern_timeframes": parsed}, "meaningful_behavior") == []


def test_pattern_timeframes_roundtrip() -> None:
    init_position_db()
    uid = 9999301
    get_config(uid)
    save_config(
        uid,
        pattern_categories=["trendline", "three_rp"],
        pattern_timeframes=pattern_timeframes_from_form(
            ["trendline|15m", "three_rp|1h"]
        ),
    )
    cfg = get_config(uid)
    assert cfg["pattern_timeframes"]["trendline"] == ["15m"]
    assert cfg["pattern_timeframes"]["three_rp"] == ["1h"]
    assert selected_timeframes(cfg, "trendline") == ["15m"]
    assert "5m" not in selected_timeframes(cfg, "three_rp")
