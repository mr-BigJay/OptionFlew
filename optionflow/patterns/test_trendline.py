from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.trendline import detect_channel, detect_trendline


def _empty(n: int, price: float) -> list[OhlcBar]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        OhlcBar(
            ts=t0 + timedelta(minutes=15 * i),
            open=price,
            high=price + 40,
            low=price - 40,
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


def test_early_rising_support_trendline() -> None:
    bars = _empty(90, 100_200)
    _set_swing(bars, 28, 99_000, "low")
    _set_swing(bars, 52, 99_480, "low")
    _set_swing(bars, 36, 101_200, "high")
    _set_swing(bars, 66, 101_050, "high")
    hit = detect_trendline(bars, "15m")
    assert hit is not None
    assert hit.category == "trendline"
    assert hit.meta["kind"] == "trendline"
    assert hit.meta["stage"] == "early"
    assert hit.meta["side"] == "low"
    assert "اولیه" in hit.status_fa


def test_three_touch_support_is_confirmed() -> None:
    bars = _empty(80, 99_780)
    _set_swing(bars, 24, 98_800, "low")
    _set_swing(bars, 48, 99_200, "low")
    _set_swing(bars, 72, 99_600, "low")
    _set_swing(bars, 36, 101_400, "high")
    _set_swing(bars, 60, 101_500, "high")
    hit = detect_trendline(bars, "15m")
    assert hit is not None
    assert hit.category == "trendline"
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["side"] == "low"


def test_falling_resistance_trendline() -> None:
    bars = _empty(54, 101_650)
    _set_swing(bars, 22, 102_600, "high")
    _set_swing(bars, 46, 102_050, "high")
    _set_swing(bars, 34, 99_400, "low")
    _set_swing(bars, 50, 99_250, "low")
    hit = detect_trendline(bars, "15m")
    assert hit is not None
    assert hit.meta["direction"] == "down"
    assert hit.meta["side"] == "high"
    assert hit.meta["kind"] == "trendline"


def test_parallel_descending_channel() -> None:
    bars = _empty(86, 99_700)
    _set_swing(bars, 20, 100_400, "high")
    _set_swing(bars, 32, 99_850, "low")
    _set_swing(bars, 44, 100_200, "high")
    _set_swing(bars, 56, 99_650, "low")
    _set_swing(bars, 68, 100_000, "high")
    _set_swing(bars, 80, 99_450, "low")
    hit = detect_channel(bars, "15m")
    assert hit is not None
    assert hit.category == "channel"
    assert hit.meta["kind"] == "channel"
    assert "نزولی" in hit.title_fa or hit.meta["direction"] == "down"


def test_early_hidden_when_allow_early_false() -> None:
    bars = _empty(90, 100_200)
    _set_swing(bars, 28, 99_000, "low")
    _set_swing(bars, 52, 99_480, "low")
    _set_swing(bars, 36, 101_200, "high")
    _set_swing(bars, 66, 101_050, "high")
    hit = detect_trendline(bars, "15m", allow_early=False)
    if hit is not None:
        assert hit.meta["stage"] != "early"


def test_dump_then_recover_is_not_channel() -> None:
    """اسکرین ۲: ریزش عمیق زیر خط بعداً نباید کانال نزولی شود."""
    bars = _empty(110, 97_000)
    _set_swing(bars, 18, 97_200, "high")
    _set_swing(bars, 32, 92_000, "low")
    _set_swing(bars, 50, 96_800, "high")
    _set_swing(bars, 70, 94_800, "low")
    _set_swing(bars, 88, 96_200, "high")
    _set_swing(bars, 100, 95_000, "low")
    assert detect_channel(bars, "5m") is None
