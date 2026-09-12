from __future__ import annotations

import logging
import os

from app.storage import insert_report
from app.telegram_notify import maybe_send_report
from optionflow.report_service import produce_report

logger = logging.getLogger("optionflow.jobs")


def run_scheduled_report() -> None:
    window = float(os.environ.get("OPTIONFLOW_WINDOW_HOURS", "2"))
    logger.info("Generating scheduled report (window=%sh)", window)
    snapshot = produce_report(window_hours=window)
    insert_report(snapshot)
    maybe_send_report(snapshot.paragraph)
    logger.info("Report saved at %s", snapshot.created_at)
