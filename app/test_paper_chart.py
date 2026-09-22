from app.paper_chart import _trendline_slice


def test_trendline_slice_one_third_before() -> None:
    meta = {"start_i": 60, "end_i": 119}
    start, end = _trendline_slice(120, meta)
    assert end == 120
    assert start == 60 - 20  # pad = 60//3 = 20
