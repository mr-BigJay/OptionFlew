from app.pattern_settings import get_pattern_setting, save_pattern_setting, signal_allowed


def test_unchecked_timeframe_and_disabled_pattern_block_signals(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.storage.DEFAULT_DATA_DIR", tmp_path)
    assert signal_allowed("trendline", "15m") is True
    save_pattern_setting("trendline", timeframes=["5m", "1h"])
    assert signal_allowed("trendline", "15m") is False
    assert signal_allowed("trendline", "5m") is True
    save_pattern_setting("trendline", enabled=False)
    assert signal_allowed("trendline", "5m") is False
    again = get_pattern_setting("trendline")
    assert again["enabled"] is False
    assert again["timeframes"] == ["5m", "1h"]
