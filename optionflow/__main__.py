from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from optionflow.deribit_client import DeribitClient
from optionflow.flow_analyzer import analyze_trades
from optionflow.guide import build_guidance, format_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="راهنمای فارسی بر اساس option flow واقعی Deribit (BTC)",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=2.0,
        help="پنجرهٔ اصلی تحلیل (پیش‌فرض: 2 ساعت)",
    )
    parser.add_argument(
        "--pre-event-minutes",
        type=int,
        default=0,
        help="اگر >0 باشد، پنجرهٔ جداگانه N دقیقه قبل از --event-at را هم تحلیل می‌کند",
    )
    parser.add_argument(
        "--event-at",
        type=str,
        default="",
        help="زمان رویداد/خبر ISO8601 UTC (مثال: 2026-09-11T12:30:00Z)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="خروجی JSON خلاصه (برای ربات)",
    )
    args = parser.parse_args(argv)

    start, end = DeribitClient.window_ms(args.hours)
    window_label = f"{args.hours:g} ساعت اخیر"

    with DeribitClient() as client:
        trades = client.fetch_option_trades(start_ms=start, end_ms=end)
        try:
            spot = client.get_index_price()
        except Exception:
            spot = None

    main_analysis = analyze_trades(
        trades,
        spot=spot,
        window_label=window_label,
    )

    pre_analysis = None
    if args.pre_event_minutes > 0 and args.event_at:
        event = datetime.fromisoformat(args.event_at.replace("Z", "+00:00"))
        if event.tzinfo is None:
            event = event.replace(tzinfo=timezone.utc)
        end_ms = int(event.timestamp() * 1000)
        start_ms = end_ms - args.pre_event_minutes * 60 * 1000
        with DeribitClient() as client:
            pre_trades = client.fetch_option_trades(start_ms=start_ms, end_ms=end_ms)
        pre_analysis = analyze_trades(
            pre_trades,
            spot=main_analysis.spot,
            window_label=f"{args.pre_event_minutes} دقیقه قبل از رویداد",
        )

    guidance = build_guidance(main_analysis, pre_event=pre_analysis)

    if args.json:
        import json

        print(
            json.dumps(
                {
                    "headline": guidance.headline_fa,
                    "bias": guidance.bias,
                    "score": guidance.score,
                    "confidence_pct": guidance.confidence_pct,
                    "support_zone": guidance.support_zone,
                    "target_zone": guidance.target_zone,
                    "spot": round(main_analysis.spot, 2),
                    "trade_count": main_analysis.trade_count,
                    "metrics": guidance.metrics,
                    "path": {
                        "primary": {
                            "id": guidance.path_primary.id,
                            "title": guidance.path_primary.title_fa,
                            "diagram": guidance.path_primary.diagram(),
                            "narrative": guidance.path_primary.narrative_fa,
                            "legs": [
                                {
                                    "direction": leg.direction,
                                    "from": leg.from_level,
                                    "to": leg.to_level,
                                }
                                for leg in (guidance.path_primary.legs if guidance.path_primary else ())
                            ],
                        },
                        "alternate": (
                            None
                            if guidance.path_alternate is None
                            else {
                                "id": guidance.path_alternate.id,
                                "title": guidance.path_alternate.title_fa,
                                "diagram": guidance.path_alternate.diagram(),
                                "narrative": guidance.path_alternate.narrative_fa,
                            }
                        ),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_report(main_analysis, guidance))

    return 0


if __name__ == "__main__":
    sys.exit(main())
