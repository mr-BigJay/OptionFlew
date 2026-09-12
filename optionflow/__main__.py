from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from optionflow.deribit_client import DeribitClient
from optionflow.flow_analyzer import analyze_trades
from optionflow.guide import build_guidance, format_report, format_simple_paragraph
from optionflow.report_service import produce_report
from optionflow.tehran_time import candle_window, to_utc_ms


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
    parser.add_argument(
        "--simple",
        action="store_true",
        help="فقط یک پاراگراف روند و مسیر (متن ساده)",
    )
    parser.add_argument(
        "--rolling",
        action="store_true",
        help="پنجرهٔ rolling به‌جای کندل ۲ ساعته تهران (مثل داشبورد نیست)",
    )
    args = parser.parse_args(argv)

    if args.simple and not args.rolling and not args.pre_event_minutes:
        snap = produce_report(
            window_hours=args.hours,
            use_candle_window=True,
        )
        print(snap.paragraph)
        return 0

    if args.rolling:
        start, end = DeribitClient.window_ms(args.hours)
        window_label = f"{args.hours:g} ساعت اخیر"
    else:
        start_dt, end_dt, window_label = candle_window()
        start, end = to_utc_ms(start_dt), to_utc_ms(end_dt)

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
                    "paragraph": format_simple_paragraph(main_analysis, guidance),
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
    elif args.simple:
        print(format_simple_paragraph(main_analysis, guidance))
    else:
        print(format_report(main_analysis, guidance))

    return 0


if __name__ == "__main__":
    sys.exit(main())
