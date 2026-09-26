from __future__ import annotations

import logging
import re
from typing import Any

from optionflow.report_service import ReportKind, ReportSnapshot
from optionflow.scenario_chart import render_btcusdt_scenario_chart
from optionflow.scenario_narrative import ScenarioPlan

logger = logging.getLogger("optionflow.report_chart")


def parse_scenario_from_paragraph(paragraph: str) -> tuple[float, int, int] | None:
    """B/C/Spot از متن prose-v3 (برای بازسازی چارت روی گزارش‌های قدیمی)."""
    if "حرکت اول" not in paragraph or "حرکت دوم" not in paragraph:
        return None
    m_spot = re.search(r"قیمت فعلی:\s*([\d,]+)", paragraph)
    m_b = re.search(
        r"\*\*حرکت اول\*\*\s*\nاز\s*[\d,]+\s*به\s*([\d,]+)",
        paragraph,
    )
    m_c = re.search(
        r"\*\*حرکت دوم\*\*\s*\nاز\s*[\d,]+\s*به\s*([\d,]+)",
        paragraph,
    )
    if not m_b or not m_c:
        return None
    spot = float(m_spot.group(1).replace(",", "")) if m_spot else 0.0
    b = int(m_b.group(1).replace(",", ""))
    c = int(m_c.group(1).replace(",", ""))
    if not spot:
        spot = float(b)
    return spot, b, c


def scenario_plan_from_snapshot(snapshot: ReportSnapshot) -> ScenarioPlan | None:
    if snapshot.scenario_b is not None:
        c = snapshot.scenario_c if snapshot.scenario_c is not None else int(snapshot.scenario_b)
        return ScenarioPlan(
            spot=float(snapshot.spot),
            b=int(snapshot.scenario_b),
            c=c,
            first_dir="up" if snapshot.scenario_b >= snapshot.spot else "down",
            second_dir="down",
            two_legs=False,
        )
    parsed = parse_scenario_from_paragraph(snapshot.paragraph)
    if not parsed:
        return None
    spot, b, c = parsed
    return ScenarioPlan(
        spot=spot,
        b=b,
        c=c,
        first_dir="up",
        second_dir="down",
        two_legs=True,
    )


def scenario_plan_from_row(report: dict[str, Any]) -> ScenarioPlan | None:
    spot = float(report.get("spot") or 0)
    zone = report.get("zone_mid")
    if zone and spot > 0 and abs(int(zone) - spot) / spot >= 0.0015:
        b = int(zone)
        return ScenarioPlan(
            spot=spot,
            b=b,
            c=b,
            first_dir="up" if b >= spot else "down",
            second_dir="down",
            two_legs=False,
        )
    parsed = parse_scenario_from_paragraph(report.get("paragraph") or "")
    if parsed:
        spot, b, c = parsed
        return ScenarioPlan(
            spot=spot,
            b=b,
            c=c,
            first_dir="up",
            second_dir="down",
            two_legs=True,
        )
    spot = float(report.get("spot") or 0)
    support = report.get("support_zone")
    target = report.get("target_zone")
    if spot > 0 and support and target:
        b = int(target)
        c = int(support)
        if b < c:
            b, c = c, b
        return ScenarioPlan(
            spot=spot,
            b=b,
            c=c,
            first_dir="up",
            second_dir="down",
            two_legs=True,
        )
    return None


def render_chart_png(
    plan: ScenarioPlan,
    report_kind: ReportKind | str,
) -> bytes | None:
    kind: ReportKind = report_kind if report_kind in ("4h", "daily") else "4h"
    return render_btcusdt_scenario_chart(plan, report_kind=kind)


def chart_png_for_snapshot(snapshot: ReportSnapshot) -> bytes | None:
    plan = scenario_plan_from_snapshot(snapshot)
    if not plan:
        logger.warning("No scenario plan for chart (missing B/C)")
        return None
    png = render_chart_png(plan, snapshot.report_kind)
    if not png:
        logger.warning("Chart render returned empty (matplotlib/Binance?)")
    return png


def chart_png_for_report_row(report: dict[str, Any]) -> bytes | None:
    plan = scenario_plan_from_row(report)
    if not plan:
        return None
    kind = report.get("report_kind") or "4h"
    return render_chart_png(plan, kind)
