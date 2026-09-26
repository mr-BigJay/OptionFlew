from app.main import _pattern_signal_kind


def test_triangle_breakout_badge_kinds() -> None:
    assert (
        _pattern_signal_kind({"status_fa": "شکست صعودی", "meta": {}})
        == "break_up"
    )
    assert (
        _pattern_signal_kind({"status_fa": "شکست نزولی", "meta": {}})
        == "break_down"
    )
    assert (
        _pattern_signal_kind({"status_fa": "در حال فشردگی", "meta": {}})
        == "neutral"
    )
    assert (
        _pattern_signal_kind({"status_fa": "فیک‌اوت صعودی", "meta": {"stage": "fakeout"}})
        == "fakeout"
    )
    assert (
        _pattern_signal_kind({"status_fa": "سیگنال اولیه", "meta": {"stage": "early"}})
        == "neutral"
    )
