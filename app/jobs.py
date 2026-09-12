from __future__ import annotations

import logging

from app.storage import save_manual_report, save_scheduled_report
from app.telegram_notify import maybe_send_report
from optionflow.report_service import ReportKind, produce_report

logger = logging.getLogger("optionflow.jobs")


def _generate_scheduled(kind: ReportKind) -> None:
    snapshot = produce_report(report_kind=kind, use_candle_window=True)
    save_scheduled_report(snapshot)
    prefix = "【۴ ساعته】" if kind == "4h" else "【روزانه】"
    maybe_send_report(f"{prefix}\n{snapshot.paragraph}")
    logger.info("Scheduled report [%s] saved at %s", kind, snapshot.created_at)


def _generate_manual(kind: ReportKind) -> None:
    snapshot = produce_report(report_kind=kind, use_candle_window=True)
    rid = save_manual_report(snapshot)
    prefix = "【دستی · ۴ ساعته】" if kind == "4h" else "【دستی · روزانه】"
    maybe_send_report(f"{prefix}\n{snapshot.paragraph}")
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
