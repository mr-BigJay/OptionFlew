"""CLI: دانلود تاریخچه BTC و ریپلی بکتست الگوها."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.storage import data_dir
from optionflow.patterns.backtest import (
    CATEGORIES,
    parse_user_datetime,
    run_backtest,
    save_backtest_report,
)
from optionflow.patterns.history import download_and_cache, history_data_dir
from optionflow.patterns.service import patterns_data_dir


def _cmd_download(args: argparse.Namespace) -> int:
    base = data_dir()
    hist = history_data_dir(base)
    start = parse_user_datetime(args.date_from)
    end = parse_user_datetime(args.date_to, end_of_day=True)
    intervals = args.interval or ["1h", "15m", "5m"]
    for iv in intervals:
        bars, path = download_and_cache(hist, iv, start, end)
        print(f"{iv}: {len(bars)} candles cached → {path}")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    base = data_dir()
    chart_dir = patterns_data_dir(base)
    start = parse_user_datetime(args.date_from)
    end = parse_user_datetime(args.date_to, end_of_day=True)
    cats = args.category if args.category else list(CATEGORIES)
    result = run_backtest(
        data_base=base,
        chart_dir=chart_dir,
        timeframe=args.timeframe,
        start=start,
        end=end,
        categories=cats,
        stride=args.stride,
        max_charts=args.max_charts,
        use_cache_only=args.cache_only,
    )
    save_backtest_report(base, result)
    if result.error:
        print(result.error, file=sys.stderr)
    print(
        json.dumps(
            {
                "findings": len(result.findings),
                "bars_scanned": result.bars_scanned,
                "stride": result.stride,
            },
            ensure_ascii=False,
        )
    )
    for f in result.findings[:20]:
        print(f"- {f.detected_at[:16]}Z | {f.title_fa} | {f.status_fa}")
    if len(result.findings) > 20:
        print(f"... و {len(result.findings) - 20} مورد دیگر")
    return 0 if not result.error else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="دانلود تاریخچه BTCUSDT و بکتست ریپلی الگوها (مستقل از گزارش 4h/روزانه)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    dl = sub.add_parser("download", help="دانلود و ذخیرهٔ کش روی سرور (gzip در data/btc_history)")
    dl.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    dl.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    dl.add_argument(
        "--interval",
        nargs="+",
        choices=["5m", "15m", "1h"],
        help="پیش‌فرض: 1h 15m 5m",
    )
    dl.set_defaults(func=_cmd_download)

    rp = sub.add_parser("replay", help="ریپلی اسکن الگو در بازهٔ تاریخ")
    rp.add_argument("--from", dest="date_from", required=True)
    rp.add_argument("--to", dest="date_to", required=True)
    rp.add_argument("--timeframe", "-t", default="1h", choices=["5m", "15m", "1h"])
    rp.add_argument(
        "--category",
        nargs="+",
        choices=list(CATEGORIES),
        help="پیش‌فرض: همه",
    )
    rp.add_argument("--stride", type=int, default=None, help="فاصلهٔ کندل بین هر اسکن")
    rp.add_argument("--max-charts", type=int, default=40)
    rp.add_argument(
        "--cache-only",
        action="store_true",
        help="فقط از کش محلی بخوان (بدون درخواست Binance)",
    )
    rp.set_defaults(func=_cmd_replay)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
