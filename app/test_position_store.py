from app.position_store import (
    close_position,
    deposit,
    get_config,
    get_wallet,
    init_position_db,
    insert_open_position,
)


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
