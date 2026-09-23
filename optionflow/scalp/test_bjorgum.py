from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar
from optionflow.scalp.bjorgum import (
    _crossover,
    _crossunder,
    bjorgum_stops_targets,
    detect_bjorgum,
)


def _bars_from_closes(closes: list[float]) -> list[OhlcBar]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out: list[OhlcBar] = []
    for i, c in enumerate(closes):
        out.append(
            OhlcBar(
                ts=t0 + timedelta(hours=i),
                open=c,
                high=c + 50,
                low=c - 50,
                close=c,
                volume=1.0,
            )
        )
    return out


def test_bjorgum_only_1h() -> None:
    scenario = {"scenario_id": "bjorgum", "title_fa": "BjorGum"}
    params = {}
    bars = _bars_from_closes([100.0] * 80)
    assert detect_bjorgum(bars, "5m", scenario, params) is None


def test_bjorgum_stops_targets_match_pine() -> None:
    close = 100.0
    atr_now = 2.0
    lowest, highest = 90.0, 110.0
    risk_m = 1.0
    tp_rr = 1.0
    _, stop_l, tp_l = bjorgum_stops_targets(
        direction="up",
        close=close,
        lowest_low=lowest,
        highest_high=highest,
        atr_now=atr_now,
        risk_m=risk_m,
        tp_rr=tp_rr,
        use_limit=True,
    )
    assert stop_l == 88.0  # 90 - 2*1
    assert tp_l == 112.0  # 100 + 1*(100-88)
    _, stop_s, tp_s = bjorgum_stops_targets(
        direction="down",
        close=close,
        lowest_low=lowest,
        highest_high=highest,
        atr_now=atr_now,
        risk_m=risk_m,
        tp_rr=tp_rr,
        use_limit=True,
    )
    assert stop_s == 112.0
    assert tp_s == 88.0


def test_bjorgum_crossover_helpers() -> None:
    ma1 = [None, 48.0, 51.0]
    ma2 = [None, 50.0, 50.5]
    assert _crossover(ma1, ma2, 2) is True
    assert _crossunder(ma1, ma2, 2) is False
    ma1s = [None, 52.0, 49.0]
    ma2s = [None, 50.0, 50.5]
    assert _crossunder(ma1s, ma2s, 2) is True
