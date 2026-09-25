from optionflow.flow_backtest import _matched, flow_direction


def test_effective_flow_direction() -> None:
    assert flow_direction(12_000, 8_000) == "up"
    assert flow_direction(8_000, 12_000) == "down"
    assert flow_direction(10_000, 10_000) == "flat"


def test_match_follows_the_close() -> None:
    assert _matched("up", 80_000, 81_000) is True
    assert _matched("up", 80_000, 79_000) is False
    assert _matched("down", 80_000, 79_000) is True
    assert _matched("flat", 80_000, 81_000) is None
