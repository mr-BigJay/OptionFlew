from __future__ import annotations

from app.indicator_store import normalize_slug, validate_slug


def test_normalize_slug() -> None:
    assert normalize_slug("My RSI v2") == "my-rsi-v2"
    assert validate_slug("my-rsi_v2") is True
    assert validate_slug("") is False
