from __future__ import annotations

from optionflow.patterns.backtest import _shift_hit_bar_indices, evaluate_outcome
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.trendline import evaluate_trendline_path
from optionflow.patterns.types import PatternHit


def _hit(**meta) -> PatternHit:
    base = {
        "kind": "trendline",
        "stage": "confirmed",
        "direction": "down",
        "side": "high",
        "upper_slope": -2.0,
        "upper_intercept": 200_000.0,
        "lower_slope": None,
        "lower_intercept": None,
        "start_i": 8,
        "end_i": 99,
        "window_offset": 18,
        "touch_highs": [12, 40, 88],
        "touch_lows": [],
        "early_index": 58,
        "confirm_index": 106,
    }
    base.update(meta)
    return PatternHit(
        category="trendline",
        timeframe="5m",
        pattern_id="trendline_high_confirmed",
        title_fa="ترندلاین مقاومت",
        status_fa="تأییدشده",
        summary_fa="",
        forecast_fa="",
        meta=base,
    )


def test_shift_trendline_keeps_local_structure_indices() -> None:
    hit = _hit()
    _shift_hit_bar_indices(hit, 500)
    assert hit.meta["window_offset"] == 518
    assert hit.meta["start_i"] == 8
    assert hit.meta["end_i"] == 99
    assert hit.meta["touch_highs"] == [12, 40, 88]
    assert hit.meta["confirm_index"] == 606


def test_evaluate_outcome_uses_path_not_blind_target_profit() -> None:
    """بکتست با target_profit_pct نباید تا آخر سری فقط TP بزند."""
    from optionflow.patterns.test_trendline import _empty, _set_close, _support_hit

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
    ok, _note = evaluate_outcome(bars, 70, hit, "15m", target_profit_pct=0.5)
    assert ok is True
    assert hit.meta["exit_reason"] == "بستن در سود ۰.۵٪"


def test_explicit_tp_sl_does_not_exit_on_a_small_line_break() -> None:
    """شکست خط با سود ۰.۲٪ نباید جای TP ۰.۶ و SL ۰.۳ را بگیرد."""
    from optionflow.patterns.test_trendline import _empty, _set_close, _support_hit

    bars = _empty(80, 100_000)
    for i, b in enumerate(bars):
        bars[i] = OhlcBar(b.ts, 100_000, 100_100, 99_900, 100_000, 1.0)
    hit = _support_hit(early=10, slope=0.0, intercept=100_000)
    _set_close(bars, 12, 99_850)
    _set_close(bars, 13, 99_850)
    b = bars[20]
    bars[20] = OhlcBar(b.ts, 100_000, 100_700, 99_950, 100_200, 1.0)
    ok, note = evaluate_outcome(
        bars, 30, hit, "5m", target_profit_pct=0.6, stop_loss_pct=0.3
    )
    assert ok is True
    assert hit.meta["exit_index"] == 20
    assert hit.meta["exit_reason"].startswith("بستن در سود")
    assert "0.6" in note
    assert abs(hit.meta["path_pct"] - 0.006) < 1e-6


def test_explicit_sl_is_not_a_flat_line_break() -> None:
    """کلوزِ تقریباً مساوی ورود شکست خط نیست؛ استاپ فقط روی ۰.۳٪ است."""
    bars = _empty_short()
    hit = _hit(
        upper_slope=0.0,
        upper_intercept=100_000.0,
        window_offset=0,
        early_index=10,
        confirm_index=10,
        stage="confirmed",
    )
    ok, note = evaluate_outcome(
        bars, 40, hit, "5m", target_profit_pct=0.6, stop_loss_pct=0.3
    )
    assert ok is True
    assert hit.meta["exit_reason"].startswith("بستن در سود")
    assert "شکست" not in hit.meta["exit_reason"]
    assert abs(hit.meta["path_pct"] - 0.006) < 1e-6
    assert "0.6" in note


def _empty_short() -> list[OhlcBar]:
    from optionflow.patterns.test_trendline import _empty, _set_close

    bars = _empty(80, 100_000)
    for i, b in enumerate(bars):
        bars[i] = OhlcBar(b.ts, 100_000, 100_100, 99_900, 100_000, 1.0)
    _set_close(bars, 12, 100_120)
    _set_close(bars, 13, 100_120)
    b = bars[24]
    bars[24] = OhlcBar(b.ts, 100_000, 100_050, 99_300, 99_500, 1.0)
    return bars


def test_early_checkbox_enters_on_the_second_touch_once() -> None:
    """تیک سیگنال اولیه: ورود روی برخورد دوم، حتی اگر خط بعداً تأیید شود. یک‌بار."""
    from optionflow.patterns.backtest import replay_category
    from optionflow.patterns.test_trendline import _empty, _set_swing

    bars = _empty(80, 99_780)
    _set_swing(bars, 24, 98_800, "low")
    _set_swing(bars, 48, 99_200, "low")
    _set_swing(bars, 72, 99_600, "low")
    _set_swing(bars, 36, 101_400, "high")
    _set_swing(bars, 60, 101_500, "high")
    early_hits = [
        (i, hit)
        for i, hit in replay_category(
            bars,
            category="trendline",
            timeframe="15m",
            scan_start=55,
            scan_end=79,
            stride=1,
            entry_on_early=True,
        )
        if hit.meta.get("side") == "low"
    ]
    assert len(early_hits) == 1
    _idx, hit = early_hits[0]
    assert hit.meta["early_index"] == 48

    final_hits = [
        (i, hit)
        for i, hit in replay_category(
            bars,
            category="trendline",
            timeframe="15m",
            scan_start=55,
            scan_end=79,
            stride=1,
            entry_on_early=False,
        )
        if hit.meta.get("side") == "low"
    ]
    assert len(final_hits) == 1
    _idx, hit = final_hits[0]
    assert hit.meta.get("stage") == "confirmed"
    assert hit.meta["confirm_index"] == 72


def test_two_touch_line_is_only_in_the_early_backtest() -> None:
    from optionflow.patterns.backtest import replay_category
    from optionflow.patterns.test_trendline import _empty, _set_swing

    bars = _empty(90, 100_200)
    _set_swing(bars, 28, 99_000, "low")
    _set_swing(bars, 52, 99_480, "low")
    _set_swing(bars, 36, 101_200, "high")
    _set_swing(bars, 66, 101_050, "high")
    early = replay_category(
        bars,
        category="trendline",
        timeframe="15m",
        scan_start=70,
        scan_end=89,
        stride=1,
        entry_on_early=True,
    )
    final = replay_category(
        bars,
        category="trendline",
        timeframe="15m",
        scan_start=70,
        scan_end=89,
        stride=1,
        entry_on_early=False,
    )
    assert any(h.meta.get("stage") == "early" for _, h in early)
    assert final == []


def test_four_touches_are_skipped_when_the_option_is_on() -> None:
    from optionflow.patterns.backtest import replay_category, trendline_touch_count
    from optionflow.patterns.test_trendline import _empty, _set_swing

    bars = _empty(96, 99_780)
    _set_swing(bars, 18, 98_600, "low")
    _set_swing(bars, 36, 98_900, "low")
    _set_swing(bars, 54, 99_200, "low")
    _set_swing(bars, 72, 99_500, "low")
    _set_swing(bars, 30, 101_400, "high")
    _set_swing(bars, 48, 101_500, "high")
    _set_swing(bars, 66, 101_450, "high")
    kept = [
        hit
        for _i, hit in replay_category(
            bars,
            category="trendline",
            timeframe="15m",
            scan_start=80,
            scan_end=95,
            stride=1,
            skip_four_touches=False,
        )
        if hit.meta.get("side") == "low"
    ]
    assert kept
    assert trendline_touch_count(kept[0]) >= 4
    skipped = [
        hit
        for _i, hit in replay_category(
            bars,
            category="trendline",
            timeframe="15m",
            scan_start=80,
            scan_end=95,
            stride=1,
            skip_four_touches=True,
        )
        if hit.meta.get("side") == "low"
    ]
    assert skipped == []


def test_path_timeout_counts_as_fail() -> None:
    from optionflow.patterns.test_trendline import _empty, _support_hit

    slope, intercept = 0.0, 100_000.0
    bars = _empty(200, 100_500)
    hit = _support_hit(early=50, slope=slope, intercept=intercept)
    hit.meta["window_offset"] = 0
    ok, note = evaluate_trendline_path(bars, 120, hit, timeframe="5m")
    assert ok is False
    assert "48 کندل" in note