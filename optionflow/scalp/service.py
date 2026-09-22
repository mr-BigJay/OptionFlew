from __future__ import annotations

import logging
import time
from pathlib import Path

from optionflow.patterns.chart import chart_forward_bars, render_pattern_chart
from optionflow.patterns.ohlc import load_btcusdt
from optionflow.patterns.types import PatternHit
from optionflow.scalp.detect import detect_scalp_scenario
from optionflow.scalp.evaluate import evaluate_scalp_path

logger = logging.getLogger("optionflow.scalp.service")

LIMITS = {"5m": 220, "15m": 200, "1h": 168}
_cache: dict = {"ts": 0.0, "hits": None}
CACHE_TTL = 120


def invalidate_scalp_cache() -> None:
    _cache["ts"] = 0.0
    _cache["hits"] = None


def scalp_cache_timestamp() -> int:
    ts = _cache.get("ts") or 0.0
    return int(ts) if ts else 0


def scan_scalp(
    chart_dir: Path,
    scenarios: list[dict],
) -> list[PatternHit]:
    hits: list[PatternHit] = []
    for sc in scenarios:
        if not sc.get("enabled"):
            continue
        tfs = sc.get("timeframes") or []
        params = sc.get("params") or {}
        for tf in tfs:
            if tf not in LIMITS:
                continue
            try:
                bars = load_btcusdt(tf, limit=LIMITS[tf])
                hit = detect_scalp_scenario(bars, tf, sc, params)
                if hit is None:
                    continue
                evaluate_scalp_path(bars, hit)
                sig_ix = hit.meta.get("confirm_index", len(bars) - 1)
                if not isinstance(sig_ix, int):
                    sig_ix = len(bars) - 1
                fwd = chart_forward_bars(bars, hit, sig_ix)
                png = render_pattern_chart(
                    bars, hit, signal_index=sig_ix, forward_bars=fwd
                )
                if png:
                    fname = f"scalp_{sc['scenario_id']}_{tf}.png"
                    (chart_dir / fname).write_bytes(png)
                    hit.chart_file = fname
                hits.append(hit)
            except Exception:
                logger.exception("scalp scan failed %s %s", sc.get("scenario_id"), tf)
    return hits


def get_cached_scalp_scan(chart_dir: Path, scenarios: list[dict]) -> list[PatternHit]:
    now = time.time()
    if _cache["hits"] is not None and now - _cache["ts"] < CACHE_TTL:
        return _cache["hits"]
    data = scan_scalp(chart_dir, scenarios)
    _cache["ts"] = now
    _cache["hits"] = data
    try:
        from app.scalp_store import save_scalp_hit

        for hit in data:
            save_scalp_hit(hit)
    except Exception:
        logger.exception("persist scalp hits failed")
    return data
