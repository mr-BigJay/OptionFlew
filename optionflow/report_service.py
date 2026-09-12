from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

from optionflow.deribit_client import DeribitClient
from optionflow.flow_analyzer import analyze_trades
from optionflow.guide import build_guidance, format_simple_paragraph

from optionflow.tehran_time import (
    candle_window_4h,
    candle_window_daily,
    to_utc_ms,
)

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
    paragraph = format_simple_paragraph(analysis, guidance)
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
    )
