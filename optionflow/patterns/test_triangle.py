from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.triangle import detect_triangle


def _empty(n: int, price: float) -> list[OhlcBar]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        OhlcBar(
            ts=t0 + timedelta(minutes=5 * i),
            open=price,
            high=price + 30,
            low=price - 30,
            close=price,
            volume=1.0,
        )
        for i in range(n)
    ]


def _set_swing(bars: list[OhlcBar], i: int, px: float, kind: str) -> None:
    ts = bars[i].ts
    if kind == "high":
        bars[i] = OhlcBar(ts, px - 80, px, px - 220, px - 60, 1.0)
        for j in range(max(0, i - 3), min(len(bars), i + 3)):
            if j == i:
                continue
            b = bars[j]
            if b.high >= px:
                bars[j] = OhlcBar(b.ts, b.open, px - 90, b.low, b.close, 1.0)
    else:
        bars[i] = OhlcBar(ts, px + 80, px + 220, px, px + 60, 1.0)
        for j in range(max(0, i - 3), min(len(bars), i + 3)):
            if j == i:
                continue
            b = bars[j]
            if b.low <= px:
                bars[j] = OhlcBar(b.ts, b.open, b.high, px + 90, b.close, 1.0)


def test_chop_is_not_triangle() -> None:
    bars = _empty(120, 100_000)
    for i in range(20, 110, 4):
        bars[i] = OhlcBar(
            bars[i].ts, 100_000, 100_080, 99_920, 100_010, 1.0
        )
    assert detect_triangle(bars, "5m") is None


def test_textbook_ascending() -> None:
    """سقف افقی + کف بالاتر — مثل شکل وسط."""
    bars = _empty(125, 99_400)
    _set_swing(bars, 40, 100_000, "high")
    _set_swing(bars, 55, 98_400, "low")
    _set_swing(bars, 70, 100_020, "high")
    _set_swing(bars, 85, 98_900, "low")
    _set_swing(bars, 100, 99_980, "high")
    _set_swing(bars, 115, 99_350, "low")
    for i in range(116, 125):
        px = 99_500 + (i - 116) * 20
        bars[i] = OhlcBar(bars[i].ts, px, px + 40, px - 40, px, 1.0)
    hit = detect_triangle(bars, "5m")
    assert hit is not None
    assert hit.meta["kind"] == "ascending"
    assert hit.meta.get("direction") is None
    assert hit.meta.get("structure_key", "").startswith("ascending:H")
    assert detect_triangle(bars, "5m", require_breakout=True) is None


def test_textbook_descending() -> None:
    """کف افقی + سقف پایین‌تر — مثل شکل راست."""
    bars = _empty(125, 100_600)
    _set_swing(bars, 40, 102_200, "high")
    _set_swing(bars, 55, 100_000, "low")
    _set_swing(bars, 70, 101_700, "high")
    _set_swing(bars, 85, 99_980, "low")
    _set_swing(bars, 100, 101_200, "high")
    _set_swing(bars, 115, 100_020, "low")
    for i in range(116, 125):
        px = 100_400 - (i - 116) * 20
        bars[i] = OhlcBar(bars[i].ts, px, px + 40, px - 40, px, 1.0)
    hit = detect_triangle(bars, "5m")
    assert hit is not None
    assert hit.meta["kind"] == "descending"


def test_textbook_symmetrical() -> None:
    """سقف پایین‌تر + کف بالاتر — مثل شکل چپ."""
    bars = _empty(125, 100_000)
    _set_swing(bars, 38, 102_800, "high")
    _set_swing(bars, 54, 97_600, "low")
    _set_swing(bars, 70, 102_000, "high")
    _set_swing(bars, 86, 98_300, "low")
    _set_swing(bars, 102, 101_300, "high")
    _set_swing(bars, 116, 99_000, "low")
    for i in range(117, 125):
        px = 99_600 + (i - 117) * 30
        bars[i] = OhlcBar(bars[i].ts, px, px + 40, px - 40, px, 1.0)
    hit = detect_triangle(bars, "5m")
    assert hit is not None
    assert hit.meta["kind"] == "symmetrical"


def test_backtest_only_counts_breakout_bar() -> None:
    bars = _empty(125, 99_400)
    _set_swing(bars, 40, 100_000, "high")
    _set_swing(bars, 55, 98_400, "low")
    _set_swing(bars, 70, 100_020, "high")
    _set_swing(bars, 85, 98_900, "low")
    _set_swing(bars, 100, 99_980, "high")
    _set_swing(bars, 115, 99_350, "low")
    for i in range(116, 124):
        px = 99_500 + (i - 116) * 20
        bars[i] = OhlcBar(bars[i].ts, px, px + 40, px - 40, px, 1.0)
    bars[-1] = OhlcBar(
        bars[-1].ts, 99_800, 100_400, 99_750, 100_280, 1.0
    )
    hit = detect_triangle(bars, "5m", require_breakout=True)
    assert hit is not None
    assert hit.meta["direction"] == "up"
    assert hit.meta["stage"] == "breakout"
