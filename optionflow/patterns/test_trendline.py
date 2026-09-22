from datetime import datetime, timedelta, timezone

import pytest

from optionflow.patterns.backtest import evaluate_outcome
from optionflow.patterns.chart import render_pattern_chart
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.trendline import (
    detect_channel,
    detect_trendline,
    evaluate_trendline_path,
    first_valid_break,
)
from optionflow.patterns.types import PatternHit


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


def test_falling_support_is_not_trendline() -> None:
    """حمایت ترندلاین باید کف بالاتر باشد، نه خط نزولی."""
    bars = _empty(70, 99_200)
    _set_swing(bars, 22, 100_400, "low")
    _set_swing(bars, 48, 99_600, "low")
    _set_swing(bars, 34, 102_200, "high")
    _set_swing(bars, 60, 101_400, "high")
    hit = detect_trendline(bars, "15m")
    if hit is not None:
        assert hit.meta["side"] != "low"


def test_rising_resistance_is_not_trendline() -> None:
    """مقاومت ترندلاین باید سقف پایین‌تر باشد، نه خط صعودی."""
    bars = _empty(70, 101_200)
    _set_swing(bars, 22, 100_200, "high")
    _set_swing(bars, 48, 101_000, "high")
    _set_swing(bars, 34, 98_800, "low")
    _set_swing(bars, 60, 99_400, "low")
    hit = detect_trendline(bars, "15m")
    if hit is not None:
        assert hit.meta["side"] != "high"


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


def _set_close(bars: list[OhlcBar], i: int, close: float) -> None:
    b = bars[i]
    bars[i] = OhlcBar(
        b.ts,
        close,
        max(b.high, close),
        min(b.low, close),
        close,
        b.volume,
    )


def _support_hit(*, early: int, slope: float, intercept: float) -> PatternHit:
    return PatternHit(
        category="trendline",
        timeframe="15m",
        pattern_id="trendline_low_confirmed",
        title_fa="ترندلاین حمایت",
        status_fa="تأییدشده",
        summary_fa="",
        forecast_fa="",
        meta={
            "kind": "trendline",
            "side": "low",
            "direction": "up",
            "lower_slope": slope,
            "lower_intercept": intercept,
            "upper_slope": None,
            "upper_intercept": None,
            "window_offset": 0,
            "early_index": early,
            "start_i": 20,
            "end_i": 70,
            "touch_lows": [20, early, 70],
            "touch_highs": [],
        },
    )


def test_first_valid_break_needs_two_closes() -> None:
    bars = _empty(16, 100_000)
    assert (
        first_valid_break(
            bars,
            from_i=4,
            window_offset=0,
            slope=0.0,
            intercept=100_000,
            side="low",
            buf=50,
        )
        is None
    )
    _set_close(bars, 9, 99_000)
    assert (
        first_valid_break(
            bars,
            from_i=4,
            window_offset=0,
            slope=0.0,
            intercept=100_000,
            side="low",
            buf=50,
        )
        is None
    )
    _set_close(bars, 10, 99_000)
    assert (
        first_valid_break(
            bars,
            from_i=4,
            window_offset=0,
            slope=0.0,
            intercept=100_000,
            side="low",
            buf=50,
        )
        == 10
    )


def test_support_path_profit_from_early_to_break() -> None:
    """ورود روی سیگنال اولیه؛ خروج در ۰.۵٪ سود قبل از شکست."""
    slope, intercept = 40.0, 97_200.0
    bars = _empty(110, 102_000)
    for i, b in enumerate(bars):
        y = slope * i + intercept
        px = y + 400
        bars[i] = OhlcBar(b.ts, px, px + 50, px - 50, px, 1.0)
    _set_close(bars, 40, slope * 40 + intercept + 80)
    _set_close(bars, 92, 99_800)
    _set_close(bars, 93, 99_800)
    hit = _support_hit(early=40, slope=slope, intercept=intercept)
    ok, note = evaluate_outcome(bars, 70, hit, "15m")
    assert ok is True
    assert hit.meta["entry_index"] == 40
    assert hit.meta["exit_index"] == 44
    assert hit.meta["path_pct"] == pytest.approx(0.005, rel=1e-4)
    assert "۰.۵٪" in note


def test_take_profit_wins_before_valid_break() -> None:
    slope, intercept = 40.0, 97_200.0
    bars = _empty(110, 102_000)
    for i, b in enumerate(bars):
        y = slope * i + intercept
        px = y + 400
        bars[i] = OhlcBar(b.ts, px, px + 50, px - 50, px, 1.0)
    _set_close(bars, 40, slope * 40 + intercept + 80)
    _set_close(bars, 92, 99_800)
    _set_close(bars, 93, 99_800)
    hit = _support_hit(early=40, slope=slope, intercept=intercept)
    ok, note = evaluate_trendline_path(bars, 70, hit)
    assert ok is True
    assert hit.meta["exit_index"] == 44
    assert hit.meta.get("exit_reason") == "بستن در سود ۰.۵٪"
    assert "۰.۵٪" in note


def test_support_path_loss_when_break_is_below_entry() -> None:
    slope, intercept = 40.0, 97_200.0
    bars = _empty(110, 102_000)
    for i, b in enumerate(bars):
        y = slope * i + intercept
        px = y + 400
        bars[i] = OhlcBar(b.ts, px, px + 50, px - 50, px, 1.0)
    _set_close(bars, 40, 101_500)
    _set_close(bars, 92, 99_200)
    _set_close(bars, 93, 99_200)
    hit = _support_hit(early=40, slope=slope, intercept=intercept)
    ok, _note = evaluate_trendline_path(bars, 70, hit)
    assert ok is False
    assert hit.meta["path_pct"] < 0


def test_no_valid_break_is_unknown() -> None:
    bars = _empty(90, 98_200)
    for i in range(len(bars)):
        _set_close(bars, i, 98_200)
    hit = _support_hit(early=40, slope=0.0, intercept=98_000.0)
    ok, note = evaluate_trendline_path(bars, 70, hit)
    assert ok is None
    assert "۰.۵٪" in note
    assert "exit_index" not in hit.meta


def test_resistance_short_path_profit() -> None:
    slope, intercept = -30.0, 103_200.0
    bars = _empty(110, 98_000)
    for i, b in enumerate(bars):
        y = slope * i + intercept
        px = y - 400
        bars[i] = OhlcBar(b.ts, px, px + 50, px - 50, px, 1.0)
    _set_close(bars, 40, slope * 40 + intercept - 80)
    _set_close(bars, 92, 101_800)
    _set_close(bars, 93, 101_800)
    hit = PatternHit(
        category="trendline",
        timeframe="15m",
        pattern_id="trendline_high_confirmed",
        title_fa="ترندلاین مقاومت",
        status_fa="تأییدشده",
        summary_fa="",
        forecast_fa="",
        meta={
            "kind": "trendline",
            "side": "high",
            "direction": "down",
            "upper_slope": slope,
            "upper_intercept": intercept,
            "lower_slope": None,
            "lower_intercept": None,
            "window_offset": 0,
            "early_index": 40,
            "start_i": 20,
            "end_i": 70,
            "touch_highs": [20, 40, 70],
            "touch_lows": [],
        },
    )
    ok, _note = evaluate_trendline_path(bars, 70, hit)
    assert ok is True
    assert hit.meta["exit_index"] == 45
    assert hit.meta["path_pct"] == pytest.approx(0.005, rel=1e-4)


def test_trendline_chart_shows_path_without_error() -> None:
    slope, intercept = 40.0, 97_200.0
    bars = _empty(110, 102_000)
    for i, b in enumerate(bars):
        y = slope * i + intercept
        px = y + 400
        bars[i] = OhlcBar(b.ts, px, px + 50, px - 50, px, 1.0)
    _set_close(bars, 40, slope * 40 + intercept + 80)
    _set_close(bars, 92, 99_800)
    _set_close(bars, 93, 99_800)
    hit = _support_hit(early=40, slope=slope, intercept=intercept)
    ok, _note = evaluate_trendline_path(bars, 70, hit)
    assert ok is True
    png = render_pattern_chart(
        bars,
        hit,
        signal_index=hit.meta["entry_index"],
        forward_bars=12,
        outcome_success=ok,
    )
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
