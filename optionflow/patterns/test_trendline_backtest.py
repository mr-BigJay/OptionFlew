from optionflow.patterns.backtest import evaluate_outcome
from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.test_trendline import _empty, _set_close, _support_hit


def test_trendline_backtest_target_profit_uses_path_not_open_end() -> None:
    slope, intercept = 0.0, 98_000.0
    bars = _empty(90, 98_500)
    for i in range(len(bars)):
        _set_close(bars, i, 98_500)
    _set_close(bars, 70, 98_500)
    _set_close(bars, 71, 97_500)
    _set_close(bars, 72, 97_500)
    hit = _support_hit(early=40, slope=slope, intercept=intercept)
    hit.meta["confirm_index"] = 70
    hit.meta["stage"] = "confirmed"
    ok, _note = evaluate_outcome(
        bars, 70, hit, "15m", target_profit_pct=0.6
    )
    assert ok is False
    assert hit.meta.get("exit_reason") == "شکست معتبر"
