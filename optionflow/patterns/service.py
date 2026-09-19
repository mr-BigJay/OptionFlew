from __future__ import annotations

import logging
import time
from pathlib import Path

from optionflow.patterns.chart import render_pattern_chart
from optionflow.patterns.divergence import detect_rsi_divergence
from optionflow.patterns.flag import detect_flag
from optionflow.patterns.ohlc import load_btcusdt
from optionflow.patterns.trendline import detect_trendline
from optionflow.patterns.triangle import detect_triangle
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.patterns")

TIMEFRAMES = ("5m", "15m", "1h")
LIMITS = {"5m": 200, "15m": 200, "1h": 168}

_cache: dict = {"ts": 0.0, "hits": None}
CACHE_TTL = 180


def patterns_data_dir(base: Path) -> Path:
    d = base / "patterns"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scan_tf(tf: str, chart_dir: Path) -> dict[str, PatternHit | None]:
    bars = load_btcusdt(tf, limit=LIMITS.get(tf, 200))
    tri = detect_triangle(bars, tf)
    flg = detect_flag(bars, tf)
    div = detect_rsi_divergence(bars, tf)
    trl = detect_trendline(bars, tf)
    out: dict[str, PatternHit | None] = {
        "triangle": tri,
        "flag": flg,
        "divergence": div,
        "trendline": trl,
    }
    for hit in (tri, flg, div, trl):
        if hit is None:
            continue
        png = render_pattern_chart(bars, hit)
        if not png:
            continue
        fname = f"{hit.category}_{hit.timeframe}_{hit.pattern_id}.png"
        path = chart_dir / fname
        path.write_bytes(png)
        hit.chart_file = fname
    return out


def scan_all_patterns(chart_dir: Path) -> dict[str, dict[str, PatternHit | None]]:
    """category -> timeframe -> hit or None"""
    result: dict[str, dict[str, PatternHit | None]] = {
        "triangle": {},
        "flag": {},
        "divergence": {},
        "trendline": {},
    }
    for tf in TIMEFRAMES:
        try:
            per = _scan_tf(tf, chart_dir)
            for cat in result:
                result[cat][tf] = per.get(cat)
        except Exception as e:
            logger.warning("Pattern scan failed %s: %s", tf, e)
            for cat in result:
                result[cat][tf] = None
    return result


def get_cached_scan(chart_dir: Path) -> dict[str, dict[str, PatternHit | None]]:
    now = time.time()
    if _cache["hits"] is not None and now - _cache["ts"] < CACHE_TTL:
        return _cache["hits"]
    data = scan_all_patterns(chart_dir)
    _cache["ts"] = now
    _cache["hits"] = data
    return data


def invalidate_pattern_cache() -> None:
    _cache["ts"] = 0.0
    _cache["hits"] = None


def pattern_cache_timestamp() -> int:
    return int(_cache.get("ts") or 0)
