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
    if "مقصد اول نامشخص" in paragraph:
        return None
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


def _levels_from_snapshot(snapshot: ReportSnapshot) -> dict[str, int | None]:
    return {
        "zone_low": snapshot.zone_low,
        "zone_high": snapshot.zone_high,
        "band_low": snapshot.band_low,
        "band_high": snapshot.band_high,
    }


def scenario_plan_from_snapshot(snapshot: ReportSnapshot) -> ScenarioPlan | None:
    levels = _levels_from_snapshot(snapshot)
    has_levels = any(levels.values())
    if snapshot.scenario_b is not None:
        two_legs = snapshot.scenario_c is not None
        return ScenarioPlan(
            spot=float(snapshot.spot),
            b=int(snapshot.scenario_b),
            c=int(snapshot.scenario_c if two_legs else snapshot.scenario_b),
            first_dir="up",
            second_dir="down",
            two_legs=two_legs,
            first_confident=True,
            **levels,
        )
    parsed = parse_scenario_from_paragraph(snapshot.paragraph)
    if parsed:
        spot, b, c = parsed
        return ScenarioPlan(
            spot=spot,
            b=b,
            c=c,
            first_dir="up",
            second_dir="down",
            two_legs=True,
            **levels,
        )
    if has_levels and snapshot.spot:
        return ScenarioPlan(
            spot=float(snapshot.spot),
            b=0,
            c=0,
            first_dir="down",
            second_dir="up",
            two_legs=False,
            first_confident=False,
            **levels,
        )
    return None


def _levels_from_row(report: dict[str, Any]) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for key in ("zone_low", "zone_high", "band_low", "band_high"):
        raw = report.get(key)
        out[key] = int(raw) if raw not in (None, "") else None
    return out


def scenario_plan_from_row(report: dict[str, Any]) -> ScenarioPlan | None:
    paragraph = report.get("paragraph") or ""
    levels = _levels_from_row(report)
    if "مقصد اول نامشخص" in paragraph and not any(levels.values()):
        return None
    parsed = None if "مقصد اول نامشخص" in paragraph else parse_scenario_from_paragraph(paragraph)
    if parsed:
        spot, b, c = parsed
        return ScenarioPlan(
            spot=spot,
            b=b,
            c=c,
            first_dir="up",
            second_dir="down",
            two_legs=True,
            **levels,
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
            **levels,
        )
    if spot > 0 and any(levels.values()):
        return ScenarioPlan(
            spot=spot,
            b=0,
            c=0,
            first_dir="down",
            second_dir="up",
            two_legs=False,
            first_confident=False,
            **levels,
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
