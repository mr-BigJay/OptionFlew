from app.main import _format_prose_report_html


def test_report_prose_collapses_extra_newlines() -> None:
    text = """**سناریوی اصلی BTC**
تمایل کوتاه‌مدت — قیمت: 84,639

**حرکت اول**
از 84,639 به 82,576



قیمت در محدوده premium"""
    html = _format_prose_report_html(text)
    assert "report-section-title" in html
    assert html.count("report-section-body") >= 3
    assert "\n\n\n" not in html
