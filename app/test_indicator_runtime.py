from app.indicator_runtime import build_indicator_live_payload


def test_pine_rsi_payload_shape(monkeypatch) -> None:
    from optionflow.patterns.ohlc import OhlcBar
    from datetime import datetime, timedelta, timezone

    def _bar(i: int) -> OhlcBar:
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        c = 90_000.0 + i
        return OhlcBar(
            ts=t0 + timedelta(minutes=15 * i),
            open=c,
            high=c + 5,
            low=c - 5,
            close=c,
            volume=1.0,
        )

    bars = [_bar(i) for i in range(120)]

    monkeypatch.setattr(
        "app.indicator_runtime._load_pattern_bars",
        lambda tf: bars,
    )
    src = """//@version=6
indicator("T")
length = input.int(14, "RSI Length")
plot(ta.rsi(close, length))
"""
    payload = build_indicator_live_payload(
        language="pine", source_code=src, settings={"length": 14}, timeframe="15m"
    )
    assert payload is not None
    assert len(payload["candles"]) == 120
    assert payload["panes"] and payload["panes"][0]["series"][0]["points"]
