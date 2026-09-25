from __future__ import annotations

from app.indicator_validate import validate_indicator_source


def test_python_valid() -> None:
    ok, err = validate_indicator_source("python", "def f():\n    return 1\n")
    assert ok and not err


def test_python_syntax_error() -> None:
    ok, err = validate_indicator_source("python", "def f(\n")
    assert not ok
    assert "Python" in err


def test_pine_requires_version() -> None:
    ok, err = validate_indicator_source("pine", "indicator('x')\n")
    assert not ok
    assert "version" in err.lower() or "@" in err


def test_pine_valid_minimal() -> None:
    code = """//@version=5
indicator("Test")
plot(close)
"""
    ok, err = validate_indicator_source("pine", code)
    assert ok and not err


def test_pine_unbalanced() -> None:
    code = """//@version=5
indicator("Test"
plot(close)
"""
    ok, err = validate_indicator_source("pine", code)
    assert not ok
