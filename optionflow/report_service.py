from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

from optionflow.deribit_client import DeribitClient
from optionflow.flow_analyzer import analyze_trades
from optionflow.guide import build_guidance, format_enriched_simple_paragraph, format_simple_paragraph
from optionflow.market_context import collect_market_context
from optionflow.price_levels import fetch_price_levels
from optionflow.scenario_narrative import resolve_scenario_plan

from optionflow.tehran_time import (
    candle_window_4h,
    candle_window_daily,
    to_utc_ms,
)

logger = logging.getLogger("optionflow.report")

ReportKind = Literal["4h", "daily"]


@dataclass
class ReportSnapshot:
    created_at: str
    window_hours: float
    report_kind: str
    paragraph: str
    headline: str
    bias: str
    score: float
    confidence_pct: int
    support_zone: int
    target_zone: int
    spot: float
    trade_count: int
    window_label: str = ""
    pdh: int | None = None
    pdl: int | None = None
    pwh: int | None = None
    pwl: int | None = None
    report_code: str = ""
    is_manual: int = 0
    expires_at: str | None = None
    scenario_b: int | None = None
    scenario_c: int | None = None

    def to_row(self) -> dict:
        return asdict(self)


def _window_for_kind(kind: ReportKind) -> tuple[int, int, str, float]:
    if kind == "daily":
        start_dt, end_dt, label = candle_window_daily()
        return to_utc_ms(start_dt), to_utc_ms(end_dt), label, 24.0
    start_dt, end_dt, label = candle_window_4h()
    return to_utc_ms(start_dt), to_utc_ms(end_dt), label, 4.0


def produce_report(
    *,
    report_kind: ReportKind = "4h",
    use_candle_window: bool = True,
    window_hours: float | None = None,
    enriched: bool = False,
) -> ReportSnapshot:
    if use_candle_window:
        start_ms, end_ms, window_label, wh = _window_for_kind(report_kind)
    else:
        wh = window_hours or (24.0 if report_kind == "daily" else 4.0)
        start_ms, end_ms = DeribitClient.window_ms(wh)
        window_label = f"{wh:g} ساعت اخیر"

    with DeribitClient() as client:
        trades = client.fetch_option_trades(start_ms=start_ms, end_ms=end_ms)
        try:
            spot = client.get_index_price()
        except Exception:
            spot = None

    analysis = analyze_trades(
        trades,
        spot=spot,
        window_label=window_label,
        window_hours=wh,
    )
    guidance = build_guidance(analysis)
    plan = resolve_scenario_plan(
        analysis,
        support=guidance.support_zone,
        target=guidance.target_zone,
        path_primary=guidance.path_primary,
        path_alternate=guidance.path_alternate,
    )
    if enriched:
        ctx = collect_market_context(analysis.spot)
        paragraph = format_enriched_simple_paragraph(analysis, guidance, ctx)
    else:
        paragraph = format_simple_paragraph(analysis, guidance)
    if enriched and ("جمع‌بندی" not in paragraph and "نتیجه‌گیری" not in paragraph):
        logger.error(
            "Enriched report missing prose narrative; check deployment."
        )
    levels = fetch_price_levels()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return ReportSnapshot(
        created_at=now,
        window_hours=wh,
        report_kind=report_kind,
        paragraph=paragraph,
        headline=guidance.headline_fa,
        bias=guidance.bias,
        score=guidance.score,
        confidence_pct=guidance.confidence_pct,
        support_zone=guidance.support_zone,
        target_zone=guidance.target_zone,
        spot=round(analysis.spot, 2),
        trade_count=analysis.trade_count,
        window_label=window_label,
        pdh=levels.pdh,
        pdl=levels.pdl,
        pwh=levels.pwh,
        pwl=levels.pwl,
        scenario_b=plan.b if plan and plan.first_confident else None,
        scenario_c=plan.c if plan and plan.first_confident else None,
    )
