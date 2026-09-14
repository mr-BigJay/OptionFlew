from __future__ import annotations

import logging
import os

from app.storage import insert_report
from app.telegram_notify import maybe_send_report
from optionflow.report_service import produce_report

logger = logging.getLogger("optionflow.jobs")


def run_scheduled_report() -> None:
    enriched = os.environ.get("OPTIONFLOW_ENRICHED", "0") == "1"
    logger.info(
        "Generating scheduled report (Tehran candle, enriched=%s)",
        enriched,
    )
    snapshot = produce_report(use_candle_window=True, enriched=enriched)
    insert_report(snapshot)
    preview = snapshot.paragraph.replace("\n", " ")[:100]
    logger.info("Report saved at %s; preview=%s…", snapshot.created_at, preview)
    maybe_send_report(snapshot.paragraph)
