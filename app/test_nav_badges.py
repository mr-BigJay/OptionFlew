from __future__ import annotations

from app.nav_badges import _cap, _since


def test_cap_limits() -> None:
    assert _cap(-1) == 0
    assert _cap(3) == 3
    assert _cap(150) == 99


def test_since_default() -> None:
    assert _since({}, "missing") == "1970-01-01T00:00:00Z"
    assert _since({"missing": " 2026-01-01T00:00:00Z "}, "missing") == "2026-01-01T00:00:00Z"
