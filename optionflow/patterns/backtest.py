from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from optionflow.patterns.chart import render_pattern_chart
from optionflow.patterns.divergence import detect_rsi_divergence
from optionflow.patterns.flag import detect_flag
from optionflow.patterns.history import (
    download_and_cache,
    history_data_dir,
    load_cached_bars,
    slice_with_warmup,
    INTERVAL_MS,
)
from optionflow.patterns.triangle import detect_triangle
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.patterns.backtest")

CATEGORIES = ("triangle", "flag", "divergence")
STRIDE_BY_TF = {"5m": 6, "15m": 2, "1h": 1}
DEDUPE_BARS = {"5m": 36, "15m": 12, "1h": 8}
MAX_CHARTS_DEFAULT = 40


@dataclass
class BacktestFinding:
    category: str
    pattern_id: str
    timeframe: str
    detected_at: str
    title_fa: str
    status_fa: str
    summary_fa: str
    forecast_fa: str
    bar_index: int
    chart_file: str = ""

    @staticmethod
    def from_hit(hit: PatternHit, bar_index: int, ts: datetime) -> BacktestFinding:
        return BacktestFinding(
            category=hit.category,
            pattern_id=hit.pattern_id,
            timeframe=hit.timeframe,
            detected_at=ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            title_fa=hit.title_fa,
            status_fa=hit.status_fa,
            summary_fa=hit.summary_fa,
            forecast_fa=hit.forecast_fa,
            bar_index=bar_index,
            chart_file=hit.chart_file,
        )


@dataclass
class BacktestResult:
    timeframe: str
    from_iso: str
    to_iso: str
    categories: list[str]
    bars_total: int
    bars_scanned: int
    stride: int
    findings: list[BacktestFinding] = field(default_factory=list)
    cache_path: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "timeframe": self.timeframe,
            "from_iso": self.from_iso,
            "to_iso": self.to_iso,
            "categories": self.categories,
            "bars_total": self.bars_total,
            "bars_scanned": self.bars_scanned,
            "stride": self.stride,
            "findings": [asdict(f) for f in self.findings],
            "cache_path": self.cache_path,
            "error": self.error,
        }


def _detectors(categories: list[str]):
    mapping = {
        "triangle": detect_triangle,
        "flag": detect_flag,
        "divergence": detect_rsi_divergence,
    }
    return [(c, mapping[c]) for c in categories if c in mapping]


def replay_on_bars(
    bars: list[OhlcBar],
    *,
    timeframe: str,
    scan_start: int,
    scan_end: int,
    categories: list[str],
    stride: int | None = None,
) -> list[tuple[int, PatternHit]]:
    stride = stride or STRIDE_BY_TF.get(timeframe, 1)
    dedupe = DEDUPE_BARS.get(timeframe, 12)
    last_key: dict[tuple[str, str], int] = {}
    out: list[tuple[int, PatternHit]] = []

    for i in range(scan_start, scan_end + 1, stride):
        window = bars[: i + 1]
        for cat, fn in _detectors(categories):
            hit = fn(window, timeframe)
            if hit is None:
                continue
            key = (cat, hit.pattern_id)
            prev = last_key.get(key)
            if prev is not None and i - prev < dedupe:
                continue
            last_key[key] = i
            out.append((i, hit))
    return out


def run_backtest(
    *,
    data_base: Path,
    chart_dir: Path,
    timeframe: str,
    start: datetime,
    end: datetime,
    categories: list[str] | None = None,
    stride: int | None = None,
    max_charts: int = MAX_CHARTS_DEFAULT,
    use_cache_only: bool = False,
) -> BacktestResult:
    cats = list(categories or CATEGORIES)
    for c in cats:
        if c not in CATEGORIES:
            raise ValueError(f"unknown category: {c}")

    hist_dir = history_data_dir(data_base)
    warmup = 160
    step = INTERVAL_MS.get(timeframe, 3_600_000)
    fetch_start = start - timedelta(seconds=(warmup * step) / 1000)
    if use_cache_only:
        bars = load_cached_bars(hist_dir, timeframe)
        cache_path = str(hist_dir / f"btcusdt_{timeframe}.json.gz")
    else:
        bars, cache_path = download_and_cache(hist_dir, timeframe, fetch_start, end)
        cache_path = str(cache_path)

    full, scan_start, scan_end = slice_with_warmup(bars, start, end)
    result = BacktestResult(
        timeframe=timeframe,
        from_iso=start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        to_iso=end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        categories=cats,
        bars_total=len(full),
        bars_scanned=max(0, scan_end - scan_start + 1) if scan_end >= scan_start else 0,
        stride=stride or STRIDE_BY_TF.get(timeframe, 1),
        cache_path=cache_path,
    )

    if scan_end < scan_start or not full:
        result.error = "دادهٔ کافی در بازه نیست — اول تاریخچه را دانلود کنید یا بازه را عوض کنید."
        return result

    raw_hits = replay_on_bars(
        full,
        timeframe=timeframe,
        scan_start=scan_start,
        scan_end=scan_end,
        categories=cats,
        stride=stride,
    )

    chart_dir.mkdir(parents=True, exist_ok=True)
    findings: list[BacktestFinding] = []
    for n, (idx, hit) in enumerate(raw_hits):
        ts = full[idx].ts
        finding = BacktestFinding.from_hit(hit, idx, ts)
        if n < max_charts:
            png = render_pattern_chart(full[: idx + 1], hit)
            if png:
                fname = f"bt_{hit.category}_{timeframe}_{idx}_{hit.pattern_id}.png"
                (chart_dir / fname).write_bytes(png)
                finding.chart_file = fname
        findings.append(finding)

    result.findings = findings
    return result


def save_backtest_report(data_dir: Path, result: BacktestResult) -> Path:
    out_dir = data_dir / "patterns"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "backtest_latest.json"
    path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_backtest_report(data_dir: Path) -> BacktestResult | None:
    path = data_dir / "patterns" / "backtest_latest.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        findings = [BacktestFinding(**f) for f in raw.get("findings", [])]
        return BacktestResult(
            timeframe=raw.get("timeframe", "1h"),
            from_iso=raw.get("from_iso", ""),
            to_iso=raw.get("to_iso", ""),
            categories=raw.get("categories", []),
            bars_total=int(raw.get("bars_total", 0)),
            bars_scanned=int(raw.get("bars_scanned", 0)),
            stride=int(raw.get("stride", 1)),
            findings=findings,
            cache_path=raw.get("cache_path", ""),
            error=raw.get("error", ""),
        )
    except Exception as e:
        logger.warning("backtest report load failed: %s", e)
        return None


def parse_user_datetime(s: str, end_of_day: bool = False) -> datetime:
    s = s.strip()
    if "T" in s:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    dt = datetime.fromisoformat(s + "T00:00:00").replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt
