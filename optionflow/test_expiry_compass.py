from datetime import datetime, timezone

from optionflow.report_chart import scenario_plan_from_snapshot
from optionflow.report_service import ReportSnapshot
from optionflow.expiry_compass import (
    PriorCompass,
    apply_shift,
    build_compass,
    classify_shift,
    expected_move,
)


NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _row(expiry: str, strike: int, opt: str, oi: float, iv: float = 50.0) -> dict:
    side = "C" if opt == "call" else "P"
    return {
        "instrument_name": f"BTC-{expiry}-{strike}-{side}",
        "open_interest": oi,
        "mark_iv": iv,
    }


def test_expected_move_one_day() -> None:
    move = expected_move(80_000, 50.0, 24.0)
    assert 2_000 < move < 2_200


def test_zone_is_the_heavy_cluster_not_the_average() -> None:
    books = []
    for strike, oi in ((78_000, 40), (79_000, 8), (82_000, 6), (86_000, 5)):
        books.append(_row("26SEP26", strike, "put", oi))
        books.append(_row("26SEP26", strike, "call", oi))
    books.append(_row("27SEP26", 90_000, "call", 100, iv=55))
    books.append(_row("27SEP26", 90_000, "put", 100, iv=55))
    compass = build_compass(books, 84_000, now=NOW)
    assert compass is not None
    assert compass.primary is not None
    assert compass.primary.expiry == "26SEP26"
    assert len(compass.expiries) == 2
    assert compass.zone_down is not None
    assert compass.zone_down.mid == 78_000
    assert compass.path_side == "down"
    assert compass.path_level == 78_000


def test_diffuse_book_has_no_path() -> None:
    books = []
    for strike in (76_000, 78_000, 80_000, 86_000, 88_000, 90_000):
        books.append(_row("26SEP26", strike, "put", 10))
        books.append(_row("26SEP26", strike, "call", 10))
    compass = build_compass(books, 84_000, now=NOW)
    assert compass is not None
    assert compass.path_level is None
    assert compass.path_side == ""


def test_shift_down_only_when_band_and_zone_both_drop() -> None:
    books = []
    for strike, oi in ((76_000, 50), (86_000, 10)):
        books.append(_row("26SEP26", strike, "put", oi, iv=60))
        books.append(_row("26SEP26", strike, "call", oi, iv=60))
    compass = build_compass(books, 84_000, now=NOW)
    assert compass is not None and compass.zone_down is not None
    prior = PriorCompass(
        band_low=compass.primary.band_low + 800,
        down_zone_mid=compass.zone_down.mid + 2_000,
        up_zone_mid=None,
    )
    assert classify_shift(prior, compass) == "down"
    pointed = apply_shift(compass, "down")
    assert pointed.path_level == compass.zone_down.mid

    flat = PriorCompass(
        band_low=compass.primary.band_low,
        down_zone_mid=compass.zone_down.mid,
    )
    assert classify_shift(flat, compass) == "flat"
    assert classify_shift(None, compass) == "unknown"


def test_chart_plan_keeps_band_and_zone() -> None:
    snapshot = ReportSnapshot(
        created_at="2026-09-25T00:00:00Z",
        window_hours=4,
        report_kind="4h",
        paragraph="x",
        headline="h",
        bias="neutral",
        score=0,
        confidence_pct=50,
        support_zone=80_000,
        target_zone=86_000,
        spot=84_000,
        trade_count=10,
        scenario_b=78_000,
        band_low=76_000,
        band_high=90_000,
        zone_low=77_500,
        zone_high=78_500,
    )
    plan = scenario_plan_from_snapshot(snapshot)
    assert plan is not None
    assert plan.band_low == 76_000
    assert plan.band_high == 90_000
    assert plan.zone_low == 77_500
    assert plan.zone_high == 78_500
    assert plan.two_legs is False
