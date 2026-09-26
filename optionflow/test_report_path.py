from datetime import datetime, timezone

from optionflow.expiry_compass import PriorCompass
from optionflow.path_v2 import PathV2, build_path_v2
from optionflow.report_path import (
    classify_level_shift,
    format_path_paragraph,
    path_quality,
)
from optionflow.report_service import _window_for_kind

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
SPOT = 83_945.0


def _book(expiry: str, strike: int, opt: str, oi: float) -> dict:
    side = "C" if opt == "call" else "P"
    return {
        "instrument_name": f"BTC-{expiry}-{strike}-{side}",
        "open_interest": oi,
        "mark_iv": 50.0,
    }


def _trade(strike: int, opt: str, direction: str, amount: float, price: float) -> dict:
    side = "C" if opt == "call" else "P"
    return {
        "instrument_name": f"BTC-26SEP26-{strike}-{side}",
        "direction": direction,
        "amount": amount,
        "price": price,
        "index_price": SPOT,
    }


def test_former_4h_report_uses_a_two_hour_window() -> None:
    _start, _end, label, hours = _window_for_kind("4h")
    assert hours == 2.0
    assert label == "۲ ساعت اخیر"


def test_call_premium_path_is_one_leg_not_a_formula() -> None:
    books = [
        _book("26SEP26", 83_500, "put", 500),
        _book("26SEP26", 85_000, "call", 40),
        _book("27SEP26", 90_000, "call", 10),
        _book("27SEP26", 90_000, "put", 10),
    ]
    trades = [
        _trade(85_000, "call", "buy", 2.0, 0.02),
        _trade(81_700, "put", "buy", 0.3, 0.01),
    ]
    path = build_path_v2(books=books, trades=trades, spot=SPOT, now=NOW)
    text = format_path_paragraph(
        path=path,
        spot=SPOT,
        window_label="۲ ساعت اخیر",
        bands=[],
        shift="unknown",
    )
    assert path is not None and path.target == 85_000
    assert "85,000" in text
    assert "حرکت دوم" not in text
    assert "1.5" not in text
    _bias, _score, confidence = path_quality(path)
    assert confidence >= 48


def test_balanced_book_does_not_invent_a_percent_target() -> None:
    books = []
    for strike in (76_000, 80_000, 88_000, 92_000):
        books.append(_book("26SEP26", strike, "call", 10))
        books.append(_book("26SEP26", strike, "put", 10))
    trades = [
        _trade(88_000, "call", "buy", 1.0, 0.01),
        _trade(80_000, "put", "buy", 1.0, 0.01),
    ]
    path = build_path_v2(books=books, trades=trades, spot=SPOT, now=NOW)
    assert path is not None and path.target is None
    text = format_path_paragraph(
        path=path,
        spot=SPOT,
        window_label="۲ ساعت اخیر",
        bands=[],
        shift="flat",
    )
    assert "مقصد مشخص نیست" in text
    assert path_quality(path)[2] == 35


def test_shift_needs_band_and_the_same_side_level() -> None:
    prior = PriorCompass(band_low=80_000, down_zone_mid=78_000, up_zone_mid=86_000)
    assert (
        classify_level_shift(
            prior, spot=84_000, band_low=79_000, down_mid=77_000, up_mid=86_000
        )
        == "down"
    )
    assert (
        classify_level_shift(
            prior, spot=84_000, band_low=80_000, down_mid=77_000, up_mid=86_000
        )
        == "flat"
    )
    assert classify_level_shift(None, spot=84_000, band_low=79_000, down_mid=77_000, up_mid=86_000) == "unknown"
