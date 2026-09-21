from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from optionflow.patterns.chart import chart_forward_bars, render_pattern_chart
from optionflow.patterns.meaningful_behavior import (
    detect_meaningful_behavior,
    evaluate_behavior_path,
)
from optionflow.patterns.ohlc import load_btcusdt
from optionflow.patterns.types import PatternHit

logger = logging.getLogger("optionflow.patterns.behavior")

TIMEFRAMES = ("5m", "15m", "1h")
LIMITS = {"5m": 200, "15m": 200, "1h": 168}
CACHE_TTL = 90

_cache: dict = {"ts": 0.0, "hits": None}


def behavior_state_path(data_root: Path) -> Path:
    return data_root / "behavior_notify_state.json"


def _load_state(path: Path) -> dict[str, float]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        keys = raw.get("sent_keys") or {}
        return {str(k): float(v) for k, v in keys.items()}
    except Exception:
        return {}


def _save_state(path: Path, sent: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - 48 * 3600
    trimmed = {k: v for k, v in sent.items() if v >= cutoff}
    path.write_text(
        json.dumps({"sent_keys": trimmed}, ensure_ascii=False, indent=0),
        encoding="utf-8",
    )


def _render_hit_chart(bars, hit: PatternHit, chart_dir: Path) -> None:
    sig_ix = hit.meta.get("entry_index", len(bars) - 1)
    if not isinstance(sig_ix, int):
        sig_ix = len(bars) - 1
    fwd = chart_forward_bars(bars, hit, sig_ix)
    png = render_pattern_chart(
        bars, hit, signal_index=sig_ix, forward_bars=fwd
    )
    if not png:
        return
    fname = f"{hit.category}_{hit.timeframe}_{hit.pattern_id}.png"
    (chart_dir / fname).write_bytes(png)
    hit.chart_file = fname


def scan_meaningful_behavior(chart_dir: Path) -> dict[str, PatternHit | None]:
    out: dict[str, PatternHit | None] = {}
    for tf in TIMEFRAMES:
        try:
            hit = detect_meaningful_behavior(tf)
            if hit is None:
                out[tf] = None
                continue
            bars = load_btcusdt(tf, limit=LIMITS.get(tf, 200))
            if not bars:
                out[tf] = hit
                continue
            hit.meta["entry_index"] = len(bars) - 1
            hit.meta["early_index"] = len(bars) - 1
            hit.meta["confirm_index"] = len(bars) - 1
            evaluate_behavior_path(bars, hit)
            _render_hit_chart(bars, hit, chart_dir)
            out[tf] = hit
        except Exception as e:
            logger.warning("Behavior scan failed %s: %s", tf, e)
            out[tf] = None
    return out


def get_cached_behavior_scan(
    chart_dir: Path,
    *,
    data_root: Path | None = None,
    notify: bool = False,
) -> dict[str, PatternHit | None]:
    now = time.time()
    if _cache["hits"] is not None and now - _cache["ts"] < CACHE_TTL:
        data = _cache["hits"]
    else:
        data = scan_meaningful_behavior(chart_dir)
        _cache["ts"] = now
        _cache["hits"] = data
        try:
            from app.pattern_store import persist_scan_hits

            persist_scan_hits(data)
        except Exception:
            logger.exception("behavior pattern persist failed")
    if notify and data_root is not None:
        notify_new_behavior_hits(
            data,
            chart_dir=chart_dir,
            state_path=behavior_state_path(data_root),
        )
    return data


def invalidate_behavior_cache() -> None:
    _cache["ts"] = 0.0
    _cache["hits"] = None


def behavior_cache_timestamp() -> int:
    return int(_cache.get("ts") or 0)


def notify_new_behavior_hits(
    hits: dict[str, PatternHit | None],
    *,
    chart_dir: Path,
    state_path: Path,
) -> None:
    from app.auth_store import list_telegram_subscribers
    from app.telegram_notify import send_telegram_message, send_telegram_photo

    sent = _load_state(state_path)
    subs = list_telegram_subscribers(scheduled_only=False)
    if not subs:
        return

    for tf, hit in hits.items():
        if hit is None:
            continue
        key = str(hit.meta.get("alert_key") or "")
        if not key or key in sent:
            continue
        caption = (
            f"⚡ رفتار معنادار · {hit.title_fa}\n"
            f"تایم‌فریم: {tf}\n"
            f"{hit.summary_fa.replace('**', '')}\n"
            f"ورود ~{hit.meta.get('entry_px') or hit.meta.get('spot_at_signal'):,.0f} · "
            f"هدف TP ~{hit.meta.get('tp_px', 0):,.0f}\n"
            f"{hit.forecast_fa}"
        )
        png: bytes | None = None
        if hit.chart_file:
            p = chart_dir / hit.chart_file
            if p.is_file():
                png = p.read_bytes()
        delivered = False
        for sub in subs:
            if not sub.get("telegram_enabled"):
                continue
            token = sub.get("telegram_bot_token") or ""
            chat_id = sub.get("telegram_chat_id") or ""
            if not token or not chat_id:
                continue
            if png:
                ok, msg = send_telegram_photo(
                    png,
                    caption=caption[:1024],
                    token=token,
                    chat_id=chat_id,
                )
            else:
                ok, msg = send_telegram_message(
                    caption,
                    token=token,
                    chat_id=chat_id,
                )
            if ok:
                delivered = True
            else:
                logger.warning(
                    "Behavior telegram failed user=%s: %s",
                    sub.get("username"),
                    msg,
                )
        if delivered:
            sent[key] = time.time()
    _save_state(state_path, sent)


def run_behavior_scan_and_notify(chart_dir: Path, data_root: Path) -> None:
    invalidate_behavior_cache()
    hits = scan_meaningful_behavior(chart_dir)
    _cache["ts"] = time.time()
    _cache["hits"] = hits
    notify_new_behavior_hits(
        hits,
        chart_dir=chart_dir,
        state_path=behavior_state_path(data_root),
    )
