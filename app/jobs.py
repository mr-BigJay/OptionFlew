from __future__ import annotations

import logging
import os

from app.storage import get_report, save_manual_report, save_report_chart, save_scheduled_report
from app.telegram_notify import maybe_send_report
from optionflow.report_codes import scheduled_report_code
from optionflow.report_service import ReportKind, produce_report
from optionflow.scenario_chart import render_btcusdt_scenario_chart
from optionflow.scenario_narrative import ScenarioPlan

logger = logging.getLogger("optionflow.jobs")


def _scenario_chart_png(snapshot) -> bytes | None:
    if snapshot.scenario_b is None or snapshot.scenario_c is None:
        return None
    kind: ReportKind = snapshot.report_kind if snapshot.report_kind in ("4h", "daily") else "4h"
    plan = ScenarioPlan(
        spot=float(snapshot.spot),
        b=int(snapshot.scenario_b),
        c=int(snapshot.scenario_c),
        first_dir="up",
        second_dir="down",
        two_legs=True,
    )
    return render_btcusdt_scenario_chart(plan, report_kind=kind)


def _notify_report(snapshot, prefix: str) -> None:
    chart_png = _scenario_chart_png(snapshot)
    code = snapshot.report_code
    if chart_png and code:
        save_report_chart(code, chart_png)
    maybe_send_report(f"{prefix}\n{snapshot.paragraph}", chart_png=chart_png)


def _generate_scheduled(kind: ReportKind) -> None:
    enriched = os.environ.get("OPTIONFLOW_ENRICHED", "0") == "1"
    snapshot = produce_report(
        report_kind=kind,
        use_candle_window=True,
        enriched=enriched,
    )
    snapshot.report_code = scheduled_report_code(kind)
    save_scheduled_report(snapshot)
    prefix = "【۴ ساعته】" if kind == "4h" else "【روزانه】"
    _notify_report(snapshot, prefix)
    logger.info("Scheduled report [%s] saved at %s", kind, snapshot.created_at)


def _generate_manual(kind: ReportKind) -> None:
    enriched = os.environ.get("OPTIONFLOW_ENRICHED", "0") == "1"
    snapshot = produce_report(
        report_kind=kind,
        use_candle_window=True,
        enriched=enriched,
    )
    rid = save_manual_report(snapshot)
    saved = get_report(rid)
    if saved:
        snapshot.report_code = saved.get("report_code") or ""
    prefix = "【دستی · ۴ ساعته】" if kind == "4h" else "【دستی · روزانه】"
    _notify_report(snapshot, prefix)
    logger.info("Manual report [%s] id=%s at %s", kind, rid, snapshot.created_at)


def run_scheduled_4h_report() -> None:
    logger.info("Generating 4h candle report (Tehran)")
    _generate_scheduled("4h")


def run_scheduled_daily_report() -> None:
    logger.info("Generating daily report (Tehran calendar day)")
    _generate_scheduled("daily")


def run_manual_reports() -> None:
    """Admin «تولید الان»: temporary j-codes, expire after 24h."""
    _generate_manual("4h")
    _generate_manual("daily")


def run_scheduled_report() -> None:
    """Alias for manual button (legacy name)."""
    run_manual_reports()
