from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from optionflow.deribit_client import DeribitClient
from optionflow.flow_analyzer import analyze_trades
from optionflow.guide import build_guidance, format_simple_paragraph


@dataclass
class ReportSnapshot:
    created_at: str
    window_hours: float
    paragraph: str
    headline: str
    bias: str
    score: float
    confidence_pct: int
    support_zone: int
    target_zone: int
    spot: float
    trade_count: int

    def to_row(self) -> dict:
        return asdict(self)


def produce_report(*, window_hours: float = 2.0) -> ReportSnapshot:
    start, end = DeribitClient.window_ms(window_hours)
    window_label = f"{window_hours:g} ساعت اخیر"

    with DeribitClient() as client:
        trades = client.fetch_option_trades(start_ms=start, end_ms=end)
        try:
            spot = client.get_index_price()
        except Exception:
            spot = None

    analysis = analyze_trades(
        trades,
        spot=spot,
        window_label=window_label,
    )
    guidance = build_guidance(analysis)
    paragraph = format_simple_paragraph(analysis, guidance)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return ReportSnapshot(
        created_at=now,
        window_hours=window_hours,
        paragraph=paragraph,
        headline=guidance.headline_fa,
        bias=guidance.bias,
        score=guidance.score,
        confidence_pct=guidance.confidence_pct,
        support_zone=guidance.support_zone,
        target_zone=guidance.target_zone,
        spot=round(analysis.spot, 2),
        trade_count=analysis.trade_count,
    )
