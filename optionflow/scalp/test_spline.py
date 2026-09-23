from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar
from optionflow.scalp.scenarios import builtin_by_id
from optionflow.scalp.spline import detect_spline


def _bar(c: float, i: int, spread: float = 0.4) -> OhlcBar:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return OhlcBar(
        ts=t0 + timedelta(hours=i),
        open=c - spread * 0.2,
        high=c + spread,
        low=c - spread,
        close=c,
        volume=1.0,
    )


def test_spline_rejects_wrong_timeframe() -> None:
    sc = builtin_by_id("spline")
    assert sc is not None
    bars = [_bar(100, i) for i in range(120)]
    assert detect_spline(bars, "5m", sc, sc["params"]) is None


def test_spline_detects_long_at_lower_band(monkeypatch) -> None:
    sc = builtin_by_id("spline")
    assert sc is not None
    params = dict(sc["params"])
    params["lookback"] = 30

    def fake_bands(bars, end_i, p):
        return {
            "upper": 110.0,
            "mid": 105.0,
            "lower": 100.0,
            "mu": 105.0,
            "sigma": 1.0,
            "mid_forecast": 106.0,
        }

    def fake_bands_prev(bars, end_i, p):
        return {
            "upper": 109.0,
            "mid": 104.0,
            "lower": 99.0,
            "mu": 104.0,
            "sigma": 1.0,
            "mid_forecast": 105.0,
        }

    import optionflow.scalp.spline as spline_mod

    calls = {"n": 0}

    def bands_side(bars, end_i, p):
        calls["n"] += 1
        if calls["n"] == 1:
            return fake_bands(bars, end_i, p)
        return fake_bands_prev(bars, end_i, p)

    monkeypatch.setattr(spline_mod, "_bands", bands_side)
    bars = [_bar(100.0, i) for i in range(80)]
    bars[-1] = _bar(99.5, len(bars) - 1)
    hit = detect_spline(bars, "1h", sc, params)
    assert hit is not None
    assert hit.meta["direction"] == "up"
    assert hit.meta["tp_px"] == 105.0
