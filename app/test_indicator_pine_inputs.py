from app.indicator_pine_inputs import parse_pine_inputs


def test_parse_pine_inputs_basic() -> None:
    src = """
//@version=6
indicator("RSI Test")
length = input.int(14, "RSI Length", minval=1)
showOB = input.bool(true, "Show OB/OS")
lineCol = input.color(#7E57C2, "Line")
"""
    fields = parse_pine_inputs(src)
    ids = [f["id"] for f in fields]
    assert ids == ["length", "showOB", "lineCol"]
    assert fields[0]["default"] == 14
    assert fields[0]["title"] == "RSI Length"
