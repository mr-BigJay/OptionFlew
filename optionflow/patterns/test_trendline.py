from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.trendline import detect_trendline


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
    assert hit.meta["stage"] == "early"
    assert hit.meta["side"] == "low"
    assert "اولیه" in hit.status_fa


def test_three_touch_support_is_confirmed() -> None:
    bars = _empty(100, 100_400)
    _set_swing(bars, 24, 98_800, "low")
    _set_swing(bars, 48, 99_200, "low")
    _set_swing(bars, 72, 99_600, "low")
    _set_swing(bars, 36, 101_400, "high")
    _set_swing(bars, 60, 101_500, "high")
    hit = detect_trendline(bars, "15m")
    assert hit is not None
    assert hit.meta["stage"] == "confirmed"
    assert hit.meta["side"] == "low"
    assert hit.meta.get("kind") in ("trendline", "channel")


def test_early_hidden_when_allow_early_false() -> None:
    bars = _empty(90, 100_200)
    _set_swing(bars, 28, 99_000, "low")
    _set_swing(bars, 52, 99_480, "low")
    _set_swing(bars, 36, 101_200, "high")
    _set_swing(bars, 66, 101_050, "high")
    hit = detect_trendline(bars, "15m", allow_early=False)
    if hit is not None:
        assert hit.meta["stage"] != "early"


def test_falling_resistance_trendline() -> None:
    bars = _empty(78, 101_250)
    _set_swing(bars, 22, 102_600, "high")
    _set_swing(bars, 46, 102_050, "high")
    _set_swing(bars, 34, 99_400, "low")
    _set_swing(bars, 58, 99_700, "low")
    hit = detect_trendline(bars, "15m")
    assert hit is not None
    assert hit.meta["direction"] == "down"
    assert hit.meta["side"] == "high" or hit.meta.get("kind") == "channel"
