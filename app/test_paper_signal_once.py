from optionflow.patterns.types import PatternHit

from app.pattern_store import event_key_for_hit, trade_key_for_hit
from app.position_store import (
    close_position,
    deposit,
    get_config,
    init_position_db,
    insert_open_position,
    signal_consumed,
)


def test_trade_key_ignores_stage_for_trendline() -> None:
    meta_early = {
        "stage": "early",
        "side": "low",
        "y_now": 95000.0,
    }
    meta_conf = {**meta_early, "stage": "confirmed"}
    h1 = PatternHit(
        category="trendline",
        timeframe="1h",
        pattern_id="trendline_low",
        title_fa="t",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta=meta_early,
    )
    h2 = PatternHit(
        category="trendline",
        timeframe="1h",
        pattern_id="trendline_low",
        title_fa="t",
        status_fa="",
        summary_fa="",
        forecast_fa="",
        meta=meta_conf,
    )
    assert trade_key_for_hit(h1) == trade_key_for_hit(h2)
    assert event_key_for_hit(h1) != event_key_for_hit(h2)


def test_signal_consumed_after_close() -> None:
    init_position_db()
    uid = 9999301
    deposit(uid, 500.0)
    cfg = get_config(uid)
    key = "trendline:1h:setup-a"
    assert signal_consumed(uid, key) is False
    pid = insert_open_position(
        uid,
        source_type="pattern",
        source_key=key,
        timeframe="1h",
        direction="long",
        entry_price=100_000.0,
        margin_usdt=50.0,
        leverage=5.0,
        fee_rate=float(cfg["fee_rate"]),
        sl_pct=1.0,
        tp_pct=0.5,
        signal_title="t",
    )
    assert pid is not None
    assert signal_consumed(uid, key) is True
    ok = close_position(
        uid,
        pid,
        exit_price=99_000.0,
        status="closed_sl",
        fee_rate=float(cfg["fee_rate"]),
    )
    assert ok is True
    assert signal_consumed(uid, key) is True
