from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

from optionflow.deribit_client import DeribitClient
from optionflow.expiry_compass import PriorCompass, fetch_book, list_expiry_bands
from optionflow.path_v2 import _gamma_near, build_path_v2
from optionflow.price_levels import fetch_price_levels
from optionflow.report_path import (
    classify_level_shift,
    format_path_paragraph,
    headline_fa,
    path_quality,
)

from optionflow.tehran_time import (
    candle_window_daily,
    to_utc_ms,
)

logger = logging.getLogger("optionflow.report")

ReportKind = Literal["4h", "daily"]


@dataclass
class ReportSnapshot:
    created_at: str
    window_hours: float
    report_kind: str
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
    pdh: int | None = None
    pdl: int | None = None
    pwh: int | None = None
    pwl: int | None = None
    report_code: str = ""
    is_manual: int = 0
    expires_at: str | None = None
    scenario_b: int | None = None
    scenario_c: int | None = None
    band_low: int | None = None
    band_high: int | None = None
    zone_low: int | None = None
    zone_high: int | None = None
    zone_mid: int | None = None
    down_zone_mid: int | None = None
    up_zone_mid: int | None = None

    def to_row(self) -> dict:
        return asdict(self)


def _window_for_kind(kind: ReportKind) -> tuple[int, int, str, float]:
    if kind == "daily":
        start_dt, end_dt, label = candle_window_daily()
        return to_utc_ms(start_dt), to_utc_ms(end_dt), label, 24.0
    start_ms, end_ms = DeribitClient.window_ms(2.0)
    return start_ms, end_ms, "۲ ساعت اخیر", 2.0


def produce_report(
    *,
    report_kind: ReportKind = "4h",
    use_candle_window: bool = True,
    window_hours: float | None = None,
    enriched: bool = False,
    prior: PriorCompass | None = None,
) -> ReportSnapshot:
    del enriched  # مسیر از حق‌بیمه می‌آید؛ متن غنی‌شدهٔ قبلی مقصد را عوض نمی‌کند.
    if use_candle_window:
        start_ms, end_ms, window_label, wh = _window_for_kind(report_kind)
    else:
        wh = window_hours or (24.0 if report_kind == "daily" else 2.0)
        start_ms, end_ms = DeribitClient.window_ms(wh)
        window_label = f"{wh:g} ساعت اخیر"

    with DeribitClient() as client:
        trades = client.fetch_option_trades(start_ms=start_ms, end_ms=end_ms)
        try:
            spot = client.get_index_price()
        except Exception:
            spot = None
    if not spot and trades:
        try:
            spot = float(trades[0].get("index_price") or 0)
        except (TypeError, ValueError):
            spot = None
    spot_f = float(spot or 0)

    books: list = []
    try:
        books = fetch_book()
    except Exception:
        logger.warning("Option book unavailable; report will not invent a target")

    moment = datetime.now(timezone.utc)
    path = None
    if books and spot_f > 0:
        path = build_path_v2(books=books, trades=trades, spot=spot_f, now=moment)
        if path is not None:
            try:
                greeks = _gamma_near(books, spot_f, path.expiry)
            except Exception:
                greeks = {}
            if greeks:
                path = build_path_v2(
                    books=books,
                    trades=trades,
                    spot=spot_f,
                    now=moment,
                    greeks=greeks,
                ) or path
    bands = list_expiry_bands(books, spot_f, now=moment) if books and spot_f > 0 else []
    primary = bands[0] if bands else None
    down_mid = None if path is None else path.bps
    up_mid = None if path is None else path.scg
    shift = classify_level_shift(
        prior,
        spot=spot_f,
        band_low=None if primary is None else primary.band_low,
        down_mid=down_mid,
        up_mid=up_mid,
    )
    bias, score, confidence = path_quality(path)
    paragraph = format_path_paragraph(
        path=path,
        spot=spot_f,
        window_label=window_label,
        bands=bands,
        shift=shift,
    )
    levels = fetch_price_levels()
    now = moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    spot_i = int(round(spot_f)) if spot_f > 0 else 0
    support = down_mid or spot_i
    target = (path.target if path and path.side in ("up", "pin") and path.target else None) or up_mid or spot_i
    scenario_b = path.target if path and path.target else None

    return ReportSnapshot(
        created_at=now,
        window_hours=wh,
        report_kind=report_kind,
        paragraph=paragraph,
        headline=headline_fa(bias, score, confidence),
        bias=bias,
        score=score,
        confidence_pct=confidence,
        support_zone=int(support),
        target_zone=int(target),
        spot=round(spot_f, 2),
        trade_count=len(trades),
        window_label=window_label,
        pdh=levels.pdh,
        pdl=levels.pdl,
        pwh=levels.pwh,
        pwl=levels.pwl,
        scenario_b=scenario_b,
        scenario_c=None,
        band_low=None if primary is None else primary.band_low,
        band_high=None if primary is None else primary.band_high,
        zone_low=scenario_b,
        zone_high=scenario_b,
        zone_mid=scenario_b,
        down_zone_mid=down_mid,
        up_zone_mid=up_mid,
    )
