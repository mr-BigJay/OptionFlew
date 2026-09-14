from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from optionflow.deribit_client import DeribitClient
from optionflow.flow_analyzer import analyze_trades
from optionflow.guide import build_guidance, format_enriched_simple_paragraph, format_simple_paragraph
from optionflow.market_context import collect_market_context

from optionflow.tehran_time import candle_window, to_utc_ms


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
    window_label: str = ""

    def to_row(self) -> dict:
        return asdict(self)


def produce_report(
    *,
    window_hours: float = 2.0,
    use_candle_window: bool = True,
    enriched: bool = False,
) -> ReportSnapshot:
    if use_candle_window:
        start_dt, end_dt, window_label = candle_window()
        start_ms = to_utc_ms(start_dt)
        end_ms = to_utc_ms(end_dt)
        wh = max((end_ms - start_ms) / 3_600_000, 2.0)
    else:
        start_ms, end_ms = DeribitClient.window_ms(window_hours)
        window_label = f"{window_hours:g} ساعت اخیر"
        wh = window_hours

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
    if enriched:
        ctx = collect_market_context(analysis.spot)
        paragraph = format_enriched_simple_paragraph(analysis, guidance, ctx)
    else:
        paragraph = format_simple_paragraph(analysis, guidance)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return ReportSnapshot(
        created_at=now,
        window_hours=wh,
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
