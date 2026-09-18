from datetime import datetime, timedelta, timezone

from optionflow.patterns.ohlc import OhlcBar
from optionflow.patterns.triangle import detect_triangle


def _bars(n: int, maker) -> list[OhlcBar]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        o, h, l, c = maker(i)
        out.append(
            OhlcBar(
                ts=t0 + timedelta(minutes=5 * i),
                open=o,
                high=h,
                low=l,
                close=c,
                volume=1.0,
            )
        )
    return out


def test_noise_range_is_not_a_triangle() -> None:
    def maker(i: int):
        base = 100_000 + (i % 5) * 40
        return base, base + 80, base - 80, base + 10

    hit = detect_triangle(_bars(120, maker), "5m")
    assert hit is None


def test_broken_out_is_not_a_triangle() -> None:
    def maker(i: int):
        # always well above any contracting range at the end
        c = 110_000 + i * 40
        return c, c + 50, c - 50, c

    hit = detect_triangle(_bars(120, maker), "5m")
    assert hit is None
