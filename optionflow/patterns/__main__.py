"""CLI: دانلود تاریخچه BTC و بکتست ریپلی الگوها."""

from __future__ import annotations

import argparse
import json
import sys

from app.storage import data_dir
from optionflow.patterns.backtest import (
    BACKTEST_TIMEFRAMES,
    CATEGORIES,
    parse_user_datetime,
    run_backtest,
)
from optionflow.patterns.history import BACKTEST_INTERVALS, download_and_cache, history_data_dir
from optionflow.patterns.seed_history import seed_btc_history
from optionflow.patterns.service import patterns_data_dir


def _cmd_download(args: argparse.Namespace) -> int:
    base = data_dir()
    hist = history_data_dir(base)
    start = parse_user_datetime(args.date_from)
    end = parse_user_datetime(args.date_to, end_of_day=True)
    intervals = args.interval or list(BACKTEST_INTERVALS)
    for iv in intervals:
        bars, path = download_and_cache(hist, iv, start, end)
        print(f"{iv}: {len(bars)} candles cached → {path}")
    return 0


def _cmd_seed(args: argparse.Namespace) -> int:
    counts = seed_btc_history(data_dir(), days=args.days)
    for iv, n in counts.items():
        print(f"{iv}: {n} bars")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    base = data_dir()
    chart_dir = patterns_data_dir(base)
    start = parse_user_datetime(args.date_from)
    end = parse_user_datetime(args.date_to, end_of_day=True)
    cat = args.category or "triangle"

    def on_progress(done: int, total: int) -> None:
        pct = int(done * 100 / total) if total else 0
        print(f"\rprogress {pct}%", end="", file=sys.stderr)

    result = run_backtest(
        data_base=base,
        chart_dir=chart_dir,
        category=cat,
        timeframe=args.timeframe,
        start=start,
        end=end,
        stride=args.stride,
        max_charts=args.max_charts,
        on_progress=on_progress,
    )
    print(file=sys.stderr)
    if result.error:
        print(result.error, file=sys.stderr)
    print(
        json.dumps(
            {
                "findings": len(result.findings),
                "success": result.success_count,
                "fail": result.fail_count,
                "bars_scanned": result.bars_scanned,
            },
            ensure_ascii=False,
        )
    )
    for f in result.findings[:20]:
        mark = "✓" if f.success else ("✗" if f.success is False else "?")
        print(f"{mark} {f.detected_at[:16]}Z | {f.title_fa}")
    return 0 if not result.error else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="دانلود تاریخچه BTCUSDT و بکتست ریپلی (مستقل از گزارش 4h/روزانه)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    seed = sub.add_parser("seed", help="پیش‌فرض نصب: ~۲ سال همه تایم‌فریم‌های بکتست")
    seed.add_argument("--days", type=int, default=730)
    seed.set_defaults(func=_cmd_seed)

    dl = sub.add_parser("download", help="دانلود کش در data/btc_history")
    dl.add_argument("--from", dest="date_from", required=True)
    dl.add_argument("--to", dest="date_to", required=True)
    dl.add_argument(
        "--interval",
        nargs="+",
        choices=list(BACKTEST_INTERVALS),
    )
    dl.set_defaults(func=_cmd_download)

    rp = sub.add_parser("replay", help="ریپلی یک الگو در بازه")
    rp.add_argument("--from", dest="date_from", required=True)
    rp.add_argument("--to", dest="date_to", required=True)
    rp.add_argument("--timeframe", "-t", default="1h", choices=list(BACKTEST_TIMEFRAMES))
    rp.add_argument("--category", "-c", choices=list(CATEGORIES))
    rp.add_argument("--stride", type=int, default=None)
    rp.add_argument("--max-charts", type=int, default=40)
    rp.set_defaults(func=_cmd_replay)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
