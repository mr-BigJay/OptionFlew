from __future__ import annotations

import logging
import os

from app.storage import (
    get_report,
    latest_compass_prior,
    save_manual_report,
    save_report_chart,
    save_scheduled_report,
)
from optionflow.expiry_compass import PriorCompass
from app.telegram_notify import maybe_send_report
from optionflow.report_chart import chart_png_for_snapshot
from optionflow.report_codes import scheduled_report_code
from optionflow.report_service import ReportKind, produce_report

logger = logging.getLogger("optionflow.jobs")


def _notify_report(snapshot, prefix: str) -> None:
    chart_png = chart_png_for_snapshot(snapshot)
    code = snapshot.report_code
    if chart_png and code:
        save_report_chart(code, chart_png)
    maybe_send_report(f"{prefix}\n{snapshot.paragraph}", chart_png=chart_png)


def _prior_for(kind: ReportKind) -> PriorCompass | None:
    raw = latest_compass_prior(kind)
    if not raw:
        return None
    return PriorCompass(
        band_low=raw.get("band_low"),
        down_zone_mid=raw.get("down_zone_mid"),
        up_zone_mid=raw.get("up_zone_mid"),
    )


def _generate_scheduled(kind: ReportKind) -> None:
    enriched = os.environ.get("OPTIONFLOW_ENRICHED", "0") == "1"
    snapshot = produce_report(
        report_kind=kind,
        use_candle_window=True,
        enriched=enriched,
        prior=_prior_for(kind),
    )
    snapshot.report_code = scheduled_report_code(kind)
    save_scheduled_report(snapshot)
    prefix = "【۴ ساعته】" if kind == "4h" else "【روزانه】"
    _notify_report(snapshot, prefix)
    logger.info("Scheduled report [%s] saved at %s", kind, snapshot.created_at)


def _generate_manual(kind: ReportKind, compass=None, prior: PriorCompass | None = None) -> None:
    enriched = os.environ.get("OPTIONFLOW_ENRICHED", "0") == "1"
    snapshot = produce_report(
        report_kind=kind,
        use_candle_window=True,
        enriched=enriched,
        prior=prior if prior is not None else _prior_for(kind),
        compass=compass,
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
    """Admin «تولید الان»: هر دو نوع با یک قطب‌نما، تا دو سناریوی متفاوت ساخته نشود."""
    from optionflow.deribit_client import DeribitClient
    from optionflow.expiry_compass import live_compass

    shared = None
    try:
        with DeribitClient() as client:
            shared = live_compass(client.get_index_price())
    except Exception:
        logger.warning("Shared compass fetch failed; each report will fetch its own")
    prior = _prior_for("daily") or _prior_for("4h")
    _generate_manual("4h", shared, prior)
    _generate_manual("daily", shared, prior)


def run_scheduled_report() -> None:
    """Alias for manual button (legacy name)."""
    run_manual_reports()


def run_scheduled_candle_sync() -> None:
    """۰۳:۳۰ تهران — پس از پایان روز UTC، کندل‌های روز قبل را incremental می‌گیرد."""
    try:
        from app.storage import data_dir
        from optionflow.patterns.seed_history import run_daily_candle_sync

        run_daily_candle_sync(data_dir())
        logger.info("Scheduled BTC candle sync completed")
    except Exception:
        logger.exception("Scheduled BTC candle sync failed (service keeps running)")


def run_scheduled_behavior_scan() -> None:
    if os.environ.get("OPTIONFLOW_BEHAVIOR_SCAN", "1").strip() not in ("1", "true", "yes"):
        return
    try:
        from app.storage import data_dir
        from optionflow.patterns.behavior_service import run_behavior_scan_and_notify
        from optionflow.patterns.service import patterns_data_dir

        chart_dir = patterns_data_dir(data_dir())
        run_behavior_scan_and_notify(chart_dir, data_dir())
        logger.info("Meaningful behavior scan + notify completed")
    except Exception:
        logger.exception("Meaningful behavior scan failed (service keeps running)")