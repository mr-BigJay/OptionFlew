from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PatternHit:
    category: str  # triangle | flag | divergence | trendline | channel | ema50 | three_rp | meaningful_behavior
    timeframe: str
    pattern_id: str
    title_fa: str
    status_fa: str
    summary_fa: str
    forecast_fa: str
    chart_file: str = ""
    meta: dict = field(default_factory=dict)
