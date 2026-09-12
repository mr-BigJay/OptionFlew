from __future__ import annotations

import logging

from app.storage import insert_report
from app.telegram_notify import maybe_send_report
from optionflow.report_service import ReportKind, produce_report

logger = logging.getLogger("optionflow.jobs")


def _generate(kind: ReportKind) -> None:
    snapshot = produce_report(report_kind=kind, use_candle_window=True)
    insert_report(snapshot)
    prefix = "【۴ ساعته】" if kind == "4h" else "【روزانه】"
    maybe_send_report(f"{prefix}\n{snapshot.paragraph}")
    logger.info("Report [%s] saved at %s", kind, snapshot.created_at)


def run_scheduled_4h_report() -> None:
    logger.info("Generating 4h candle report (Tehran)")
    _generate("4h")


def run_scheduled_daily_report() -> None:
    logger.info("Generating daily report (Tehran calendar day)")
    _generate("daily")


def run_scheduled_report() -> None:
    """Manual run: both 4h and daily snapshots."""
    run_scheduled_4h_report()
    run_scheduled_daily_report()
