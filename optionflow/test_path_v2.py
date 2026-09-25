from datetime import datetime, timezone

from optionflow.path_v2 import build_path_v2, caption_fa, path_line, premium_usd

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
SPOT = 83_945.0


def _book(expiry: str, strike: int, opt: str, oi: float) -> dict:
    side = "C" if opt == "call" else "P"
    return {
        "instrument_name": f"BTC-{expiry}-{strike}-{side}",
        "open_interest": oi,
        "mark_iv": 50.0,
    }


def _trade(expiry: str, strike: int, opt: str, direction: str, amount: float, price: float) -> dict:
    side = "C" if opt == "call" else "P"
    return {
        "instrument_name": f"BTC-{expiry}-{strike}-{side}",
        "direction": direction,
        "amount": amount,
        "price": price,
        "index_price": SPOT,
        "contracts": 10_000,
    }


def test_premium_is_option_price_not_contracts_times_spot() -> None:
    trade = _trade("26SEP26", 85_000, "call", "buy", 1.0, 0.01)
    assert premium_usd(trade) == 1.0 * 0.01 * SPOT
    assert premium_usd(trade) != 10_000 * SPOT
    assert premium_usd({**trade, "price": 0}) == 0.0


def test_call_premium_targets_above_even_if_put_oi_is_heavier() -> None:
    books = [
        _book("26SEP26", 83_500, "put", 500),
        _book("26SEP26", 83_500, "call", 20),
        _book("26SEP26", 85_000, "call", 40),
        _book("26SEP26", 85_000, "put", 10),
        _book("27SEP26", 90_000, "call", 10),
        _book("27SEP26", 90_000, "put", 10),
    ]
    trades = [
        _trade("26SEP26", 85_000, "call", "buy", 2.0, 0.02),
        _trade("26SEP26", 81_700, "put", "buy", 0.3, 0.01),
    ]
    path = build_path_v2(books=books, trades=trades, spot=SPOT, now=NOW)
    assert path is not None
    assert path.side == "up"
    assert path.target == 85_000
    assert path.target != 83_500
    assert path.scg == 85_000
    assert path.bull_premium > path.bear_premium


def test_put_premium_does_not_follow_the_call_wall() -> None:
    books = [
        _book("26SEP26", 86_000, "call", 800),
        _book("26SEP26", 81_700, "put", 30),
        _book("26SEP26", 81_000, "put", 10),
    ]
    trades = [
        _trade("26SEP26", 81_700, "put", "buy", 3.0, 0.03),
        _trade("26SEP26", 85_000, "call", "buy", 0.2, 0.01),
    ]
    path = build_path_v2(books=books, trades=trades, spot=SPOT, now=NOW)
    assert path is not None
    assert path.side == "down"
    assert path.target == 81_700


def test_balanced_flow_near_gamma_drifts_to_magnet() -> None:
    books = [
        _book("26SEP26", 84_500, "call", 400),
        _book("26SEP26", 84_500, "put", 400),
        _book("26SEP26", 78_000, "put", 40),
        _book("26SEP26", 90_000, "call", 40),
    ]
    trades = [
        _trade("26SEP26", 86_000, "call", "buy", 1.0, 0.01),
        _trade("26SEP26", 82_000, "put", "buy", 1.0, 0.01),
    ]
    path = build_path_v2(books=books, trades=trades, spot=SPOT, now=NOW)
    assert path is not None
    assert path.side == "pin"
    assert path.target == 84_500
    assert path.target != 78_000


def test_balanced_diffuse_book_has_no_line() -> None:
    books = []
    for strike in (76_000, 80_000, 88_000, 92_000):
        books.append(_book("26SEP26", strike, "call", 10))
        books.append(_book("26SEP26", strike, "put", 10))
    trades = [
        _trade("26SEP26", 88_000, "call", "buy", 1.0, 0.01),
        _trade("26SEP26", 80_000, "put", "buy", 1.0, 0.01),
    ]
    path = build_path_v2(books=books, trades=trades, spot=SPOT, now=NOW)
    assert path is not None
    assert path.target is None
    assert path.side == ""
    assert caption_fa(path) == "v2 · مسیر مشخص نیست"


def test_pin_line_starts_flat_and_ends_on_target() -> None:
    start = 1_700_000_000
    end = start + 4 * 3600
    line = path_line(SPOT, 85_000, start, end, drift="pin")
    assert line[0]["time"] == start
    assert line[0]["value"] == SPOT
    assert line[-1]["value"] == 85_000
    mid = line[len(line) // 2]["value"]
    linear_mid = SPOT + (85_000 - SPOT) * 0.5
    assert mid < linear_mid


def test_put_premium_stuck_on_spot_uses_the_next_support() -> None:
    books = [
        _book("26SEP26", 86_000, "call", 900),
        _book("26SEP26", 82_000, "put", 40),
    ]
    trades = [
        _trade("26SEP26", 83_940, "put", "buy", 5.0, 0.04),
        _trade("26SEP26", 82_000, "put", "buy", 1.0, 0.02),
        _trade("26SEP26", 86_000, "call", "buy", 0.2, 0.01),
    ]
    path = build_path_v2(books=books, trades=trades, spot=SPOT, now=NOW)
    assert path is not None
    assert path.side == "down"
    assert path.target == 82_000


def test_tiny_target_draws_no_line() -> None:
    assert path_line(SPOT, 83_950, 100, 5000) == []
