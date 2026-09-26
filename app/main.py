from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starlette.middleware.sessions import SessionMiddleware

from app.auth_middleware import (
    AuthMiddleware,
    channel_allowed,
    current_user,
    deployment_channel_label,
    login_session,
    logout_session,
)
from app.auth_store import (
    MIN_PASSWORD_LEN,
    admin_reset_user_password,
    authenticate,
    bootstrap_admin,
    clear_must_change,
    create_user,
    list_users,
    set_user_password,
    set_user_telegram,
)
from app.backtest_jobs import request_cancel_backtest, start_backtest_job
from app.backtest_store import get_backtest_run, list_backtest_runs
from app.scalp_backtest_jobs import (
    request_cancel_scalp_backtest,
    start_scalp_backtest_job,
)
from app.scalp_backtest_store import get_scalp_backtest_run, list_scalp_backtest_runs
from app.scalp_store import (
    get_scalp_event,
    get_scenario,
    list_scalp_events,
    list_scenarios,
    update_scenario_settings,
)
from app.history_jobs import history_download_state, start_history_download
from app.indicator_pine_inputs import parse_pine_inputs
from app.indicator_runtime import build_indicator_live_payload, tv_fields_json
from app.indicator_store import (
    delete_indicator,
    get_indicator,
    list_indicators,
    save_indicator,
    user_can_edit,
)
from app.nav_badges import compute_nav_badges, mark_nav_seen
from app.jobs import (
    run_scheduled_4h_report,
    run_scheduled_candle_sync,
    run_scheduled_daily_report,
    run_scheduled_report,
    run_scheduled_behavior_scan,
)
from app.pattern_store import get_pattern_event, list_all_pattern_events, list_pattern_events
from app.exchange_fee_profiles import fee_profile_summary_fa, list_fee_profiles
from app.paper_chart import render_paper_position_chart
from app.chart_live import (
    payload_from_scalp_event,
    json_for_template,
    payload_from_pattern_event,
    payload_from_pattern_hit,
    payload_from_position,
)
from app.paper_engine import (
    REPORT_FRESH_MINUTES,
    latest_btc_price,
    live_open_state,
    process_signals_for_user,
    unrealized_pnl,
)
from app.position_store import (
    PATTERN_CATEGORIES,
    PATTERN_EARLY_CATEGORIES,
    PATTERN_TIMEFRAMES,
    REPORT_KINDS,
    SCALP_SCENARIOS,
    pattern_timeframes_from_form,
    close_position,
    deposit,
    get_config,
    get_position,
    get_wallet,
    list_ledger,
    list_positions,
    locked_margin,
    save_config,
)
from app.storage import (
    data_dir,
    ensure_report_chart,
    get_latest_report,
    get_report,
    init_db,
    list_reports,
    report_has_chart,
)
from app.telegram_notify import send_telegram_message, send_telegram_photo
from optionflow.patterns.backtest import evaluate_target_profit
from optionflow.patterns.history import BACKTEST_INTERVALS, cache_status
from optionflow.patterns.behavior_service import (
    behavior_cache_timestamp,
    get_cached_behavior_scan,
    invalidate_behavior_cache,
    run_behavior_scan_and_notify,
)
from optionflow.patterns.service import (
    LIMITS,
    get_cached_scan,
    invalidate_pattern_cache,
    pattern_cache_timestamp,
    patterns_data_dir,
)
from optionflow.patterns.ohlc import OhlcBar, load_btcusdt
from optionflow.patterns.types import PatternHit
from optionflow.scalp.service import (
    get_cached_scalp_scan,
    invalidate_scalp_cache,
    scalp_cache_timestamp,
)
from optionflow.price_levels import fetch_price_levels
from optionflow.tehran_time import (
    CRON_4H_HOURS,
    CRON_DAILY_HOUR,
    CRON_DAILY_MINUTE,
    REPORT_MINUTE,
    TEHRAN,
    format_date_tehran,
    format_jalali_date_tehran,
    tehran_last_24h_bounds_utc,
    format_day_header_tehran,
    format_dt_tehran,
    format_time_tehran,
    tehran_date_key,
    tehran_day_bounds_utc,
    tehran_jalali_month_bounds_utc,
    tehran_month_bounds_utc,
    tehran_week_bounds_utc,
    tehran_week_sat_fri_bounds_utc,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("optionflow.web")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)


def _load_env_file() -> None:
    env_path = os.path.join(ROOT_DIR, ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, val)


_load_env_file()
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
scheduler = BackgroundScheduler()


def _fmt_dt(iso: str) -> str:
    return format_dt_tehran(iso)


def _fmt_time(iso: str) -> str:
    return format_time_tehran(iso)


def _fmt_day_header(iso: str) -> str:
    return format_day_header_tehran(iso)


def _bias_fa(bias: str) -> str:
    return {"bullish": "صعودی", "bearish": "نزولی", "neutral": "خنثی"}.get(
        bias, bias
    )


def _clean_paragraph(text: str) -> str:
    import re

    for phrase in (
        "این جمع‌بندی یک سناریو است، نه سیگنال قطعی.",
        "این جمع‌بندی سناریو است و جایگزین تحلیل قطعی نیست.",
    ):
        text = text.replace(phrase, "")
    text = re.sub(
        r"بر اساس معاملات آپشن بیت‌کوین در [^،]+،\s*",
        "بر اساس معاملات آپشن بیت‌کوین، ",
        text,
    )
    return text.strip()


def _report_body_html(body: str) -> str:
    """بدنهٔ بخش گزارش — بدون فاصلهٔ اضافه از newlineهای پشت‌سرهم."""
    import html as html_mod
    import re

    raw = re.sub(r"\n{3,}", "\n\n", (body or "").strip())
    if not raw:
        return ""
    paras = [p.strip() for p in re.split(r"\n\n+", raw) if p.strip()]
    chunks: list[str] = []
    for para in paras:
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        if len(lines) <= 1:
            chunks.append(
                f'<p class="report-section-body">{html_mod.escape(lines[0] if lines else para)}</p>'
            )
            continue
        for i, ln in enumerate(lines):
            cls = "report-section-body report-section-tight" if i else "report-section-body"
            chunks.append(f'<p class="{cls}">{html_mod.escape(ln)}</p>')
    return "\n".join(chunks)


def _format_prose_report_html(text: str) -> str:
    """prose-v3: **تیتر** → section؛ برای داشبورد (نه فقط چارت)."""
    import html as html_mod
    import re

    text = _clean_paragraph(text)
    if "حرکت اول" not in text and "**" not in text:
        return f'<p class="report-section-body">{html_mod.escape(text)}</p>'

    parts: list[str] = []
    for block in re.split(r"\n\n+", text.strip()):
        block = block.strip()
        if not block:
            continue
        m = re.match(r"^\*\*(.+?)\*\*\s*\n?(.*)$", block, re.DOTALL)
        if m:
            title = html_mod.escape(m.group(1).strip())
            parts.append(f'<section class="report-section"><h3 class="report-section-title">{title}</h3>')
            body_html = _report_body_html(m.group(2))
            if body_html:
                parts.append(body_html)
            parts.append("</section>")
        else:
            parts.append(_report_body_html(block) or f'<p class="report-section-body">{html_mod.escape(block)}</p>')
    return "\n".join(parts)


def _category_fa(category: str) -> str:
    return {
        "triangle": "مثلث فشرده",
        "flag": "الگوی پرچم",
        "divergence": "واگرایی RSI",
        "trendline": "ترندلاین",
        "channel": "کانال",
        "ema50": "EMA50",
        "meaningful_behavior": "رفتار معنادار",
        "three_rp": "3BRP",
    }.get(category, category)


def _pattern_signal_kind(row: dict[str, Any]) -> str:
    """neutral | confirmed | rejected | break_up | break_down — بچ وضعیت."""
    meta = row.get("meta") or {}
    status = str(row.get("status_fa") or "")
    stage = str(meta.get("stage") or "").lower()
    if meta.get("outcome_success") is False:
        return "rejected"
    if "رد شده" in status or status.strip() == "رد":
        return "rejected"
    if "شکست صعودی" in status:
        return "break_up"
    if "شکست نزولی" in status:
        return "break_down"
    if "در حال فشردگی" in status:
        return "neutral"
    if stage == "early" or "اولیه" in status:
        return "neutral"
    if stage == "confirmed" or "تأیید" in status:
        return "confirmed"
    return "neutral"


def _pattern_signal_label(row: dict[str, Any]) -> str:
    status = str(row.get("status_fa") or "").strip()
    kind = _pattern_signal_kind(row)
    if kind == "rejected":
        return status if status and "رد" in status else "رد شده"
    if kind == "early":
        return status if status else "سیگنال اولیه"
    if kind == "confirmed":
        return status if status else "تأییدشده"
    return status or "—"


def _position_status_fa(status: str) -> str:
    return {
        "open": "باز",
        "closed_tp": "بسته — TP",
        "closed_sl": "بسته — SL",
        "closed_manual": "بسته — دستی",
        "closed_liquidated": "لیکوئید",
    }.get(status, status)


def _position_source_fa(source_type: str) -> str:
    return {
        "pattern": "الگو",
        "report": "گزارش",
        "scalp": "استراتژی",
    }.get(source_type, source_type)


def _ledger_kind_fa(kind: str) -> str:
    return {
        "deposit": "واریز",
        "fee_open": "کارمزد باز",
        "fee_close": "کارمزد بست",
        "margin_lock": "قفل مارجین",
        "margin_release": "آزاد مارجین",
        "pnl": "سود/زیان",
    }.get(kind, kind)


BACKTEST_TABS = (
    "triangle",
    "flag",
    "divergence",
    "trendline",
    "channel",
    "ema50",
    "three_rp",
)
PATTERN_TABS = BACKTEST_TABS + ("meaningful_behavior",)

PATTERN_HINTS: dict[str, str] = {
    "triangle": "BTCUSDT · شکست مثلث · 5m / 15m / 1h",
    "flag": "BTCUSDT · پرچم صعودی/نزولی",
    "divergence": "BTCUSDT · RSI BigBeluga · ورود و TP",
    "trendline": "BTCUSDT · شکست ترند · 0.5٪",
    "channel": "BTCUSDT · کانال قیمت",
    "ema50": "BTCUSDT · کراس EMA50",
    "meaningful_behavior": "Deribit · surge کال/پوت · هشدار تلگرام",
    "three_rp": "BTCUSDT · LuxAlgo 3-Bar Reversal · فقط ۱h",
}


def _pattern_menu_items() -> list[dict[str, str]]:
    return [
        {
            "slug": slug,
            "label": _category_fa(slug),
            "hint": PATTERN_HINTS.get(slug, "BTCUSDT"),
        }
        for slug in PATTERN_TABS
    ]


PATTERN_TF_LABELS: dict[str, str] = {
    "5m": "۵ دقیقه",
    "15m": "۱۵ دقیقه",
    "1h": "۱ ساعت",
}


def _pattern_filter_qs(*, tf: str = "", min_profit: str = "") -> str:
    q: dict[str, str] = {}
    if tf:
        q["tf"] = tf
    mp = (min_profit or "").strip().replace(",", ".")
    if mp:
        q["min_profit"] = mp
    if not q:
        return ""
    return "&" + urlencode(q)


def _parse_min_profit_pct(raw: str) -> float | None:
    s = (raw or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if v < 0 or v > 10:
        return None
    return v


def _row_to_pattern_hit(row: dict[str, Any]) -> PatternHit:
    meta = row.get("meta") or {}
    return PatternHit(
        category=str(row["category"]),
        timeframe=str(row["timeframe"]),
        pattern_id=str(row["pattern_id"]),
        title_fa=str(row.get("title_fa") or ""),
        status_fa=str(row.get("status_fa") or ""),
        summary_fa=str(row.get("summary_fa") or ""),
        forecast_fa=str(row.get("forecast_fa") or ""),
        meta=dict(meta),
        chart_file=str(row.get("chart_file") or ""),
    )


def _signal_index_for_profit(hit: PatternHit) -> int | None:
    meta = hit.meta or {}
    for key in (
        "entry_index",
        "early_index",
        "confirm_index",
        "final_index",
    ):
        ix = meta.get(key)
        if isinstance(ix, int):
            return ix
    return None


def _row_meets_min_profit(
    row: dict[str, Any],
    min_profit_pct: float,
    bars_cache: dict[str, list[OhlcBar]],
) -> bool:
    meta = row.get("meta") or {}
    path = meta.get("path_pct")
    threshold = min_profit_pct / 100.0
    if isinstance(path, (int, float)):
        return abs(float(path)) >= threshold
    tf = str(row.get("timeframe") or "")
    if tf not in bars_cache:
        try:
            bars_cache[tf] = load_btcusdt(tf, limit=LIMITS.get(tf, 200))
        except Exception:
            logger.exception("load_btcusdt failed tf=%s", tf)
            bars_cache[tf] = []
    bars = bars_cache[tf]
    if not bars:
        return False
    hit = _row_to_pattern_hit(row)
    sig_ix = _signal_index_for_profit(hit)
    if sig_ix is None or sig_ix < 0 or sig_ix >= len(bars):
        return False
    ok, _note = evaluate_target_profit(bars, sig_ix, hit, min_profit_pct)
    return ok is True


def _filter_pattern_timeline(
    items: list[dict[str, Any]],
    *,
    timeframe: str,
    min_profit_pct: float | None,
) -> list[dict[str, Any]]:
    out = items
    if timeframe:
        out = [r for r in out if r.get("timeframe") == timeframe]
    if min_profit_pct is None or min_profit_pct <= 0:
        return out
    bars_cache: dict[str, list[OhlcBar]] = {}
    return [
        r
        for r in out
        if _row_meets_min_profit(r, min_profit_pct, bars_cache)
    ]


def _live_chart_ctx(
    payload: dict[str, Any] | None,
    *,
    dom_id: str,
    title: str = "",
    hint: str = "",
    poll_url: str = "",
) -> dict[str, Any]:
    if not payload or not payload.get("candles"):
        return {
            "chart_payload": None,
            "chart_payload_id": dom_id,
            "chart_payload_json": "{}",
            "chart_title": title,
            "chart_hint": hint,
            "chart_poll_url": poll_url,
            "chart_png_src": "",
            "chart_png_alt": "",
        }
    return {
        "chart_payload": payload,
        "chart_payload_id": dom_id,
        "chart_payload_json": json_for_template(payload),
        "chart_title": title,
        "chart_hint": hint,
        "chart_poll_url": poll_url,
        "chart_png_src": "",
        "chart_png_alt": "",
    }


def _first_live_hit_for_category(
    scan: dict[str, dict[str, Any]], category: str
):
    from optionflow.patterns.types import PatternHit

    tf_map = scan.get(category) or {}
    for tf in ("15m", "1h", "5m"):
        hit = tf_map.get(tf)
        if isinstance(hit, PatternHit):
            return hit
    return None


def _page_ctx(request: Request, **extra: Any) -> dict[str, Any]:
    user = current_user(request)
    active = extra.get("active")
    if isinstance(active, str) and active in ("patterns", "reports", "position"):
        mark_nav_seen(request, active)
    nav_badges = compute_nav_badges(
        request,
        active=active if isinstance(active, str) else None,
        scheduled_reports_only=_scheduled_only(request),
    )
    return _template_ctx(
        request=request,
        auth_user=user,
        is_admin=bool(user and user.get("is_admin")),
        channel_label=deployment_channel_label(),
        nav_badges=nav_badges,
        **extra,
    )


def _scheduled_only(request: Request) -> bool:
    user = current_user(request)
    return not (user and user.get("is_admin"))


def _template_ctx(**extra: Any) -> dict[str, Any]:
    return {
        "fmt_dt": _fmt_dt,
        "fmt_time": _fmt_time,
        "fmt_date_header": _fmt_day_header,
        "fmt_date": format_date_tehran,
        "fmt_jalali": format_jalali_date_tehran,
        "bias_fa": _bias_fa,
        "clean_paragraph": _clean_paragraph,
        "format_report_html": _format_prose_report_html,
        "category_fa": _category_fa,
        "pattern_signal_kind": _pattern_signal_kind,
        "pattern_signal_label": _pattern_signal_label,
        **extra,
    }


def _group_by_date(reports: list[dict[str, Any]]) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for r in reports:
        key = tehran_date_key(r["created_at"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)
    order.sort(reverse=True)
    return [(k, groups[k]) for k in order]


def _range_for_period(period: str, anchor: str | None) -> tuple[str, str]:
    anchor = anchor or None
    if period == "day":
        return tehran_day_bounds_utc(anchor)
    if period == "week":
        return tehran_week_bounds_utc(anchor)
    return tehran_month_bounds_utc(anchor)


def _range_for_pattern_period(period: str, anchor: str | None) -> tuple[str, str]:
    anchor = anchor or None
    if period == "day":
        return tehran_day_bounds_utc(anchor)
    if period == "week":
        return tehran_week_sat_fri_bounds_utc(anchor)
    if period == "month":
        return tehran_jalali_month_bounds_utc(anchor)
    return tehran_month_bounds_utc(anchor)


def _range_custom_tehran(from_date: str, to_date: str) -> tuple[str, str]:
    start_iso, _ = tehran_day_bounds_utc(from_date)
    base_end = datetime.fromisoformat(to_date + "T00:00:00").replace(tzinfo=TEHRAN)
    end_local = base_end + timedelta(days=1) - timedelta(seconds=1)
    end_iso = (
        end_local.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return start_iso, end_iso


@asynccontextmanager
async def lifespan(app: FastAPI):
    import optionflow.guide as guide_mod

    try:
        import subprocess

        git_head = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT_DIR,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        git_head = "unknown"
    logger.info(
        "OptionFlow web boot: git=%s guide=%s enriched=%s data=%s",
        git_head,
        guide_mod.__file__,
        os.environ.get("OPTIONFLOW_ENRICHED", "0"),
        os.environ.get("OPTIONFLOW_DATA", "data"),
    )
    init_db()
    bootstrap_admin()
    scheduler.add_job(
        run_scheduled_4h_report,
        trigger=CronTrigger(
            minute=REPORT_MINUTE,
            hour=CRON_4H_HOURS,
            timezone=TEHRAN,
        ),
        id="flow_report_4h",
        replace_existing=True,
        misfire_grace_time=900,
    )
    scheduler.add_job(
        run_scheduled_daily_report,
        trigger=CronTrigger(
            minute=CRON_DAILY_MINUTE,
            hour=CRON_DAILY_HOUR,
            timezone=TEHRAN,
        ),
        id="flow_report_daily",
        replace_existing=True,
        misfire_grace_time=900,
    )
    scheduler.add_job(
        run_scheduled_candle_sync,
        trigger=CronTrigger(hour=3, minute=30, timezone=TEHRAN),
        id="btc_candle_daily_sync",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    if os.environ.get("OPTIONFLOW_BEHAVIOR_SCAN", "1").strip() in ("1", "true", "yes"):
        scheduler.add_job(
            run_scheduled_behavior_scan,
            trigger=IntervalTrigger(minutes=2),
            id="meaningful_behavior_scan",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
        )
    else:
        logger.info("OPTIONFLOW_BEHAVIOR_SCAN=0 — behavior scan job disabled")
    scheduler.start()
    logger.info(
        "Scheduler: 4h at :%s (hours %s); daily at %s:%s; candles at 03:30 (Asia/Tehran)",
        REPORT_MINUTE,
        CRON_4H_HOURS,
        CRON_DAILY_HOUR,
        CRON_DAILY_MINUTE,
    )
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="OptionFlow Dashboard", lifespan=lifespan)
_session_secret = os.environ.get("OPTIONFLOW_SESSION_SECRET") or secrets.token_hex(32)
app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=_session_secret, same_site="lax")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
_charts_dir = data_dir() / "charts"
_charts_dir.mkdir(parents=True, exist_ok=True)
app.mount("/charts", StaticFiles(directory=str(_charts_dir)), name="charts")
_patterns_dir = patterns_data_dir(data_dir())
app.mount(
    "/pattern-charts",
    StaticFiles(directory=str(_patterns_dir)),
    name="pattern-charts",
)


def _ensure_price_levels(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    levels = fetch_price_levels()
    out = dict(report)
    if levels.pdh is not None:
        out["pdh"] = levels.pdh
    if levels.pdl is not None:
        out["pdl"] = levels.pdl
    if levels.pwh is not None:
        out["pwh"] = levels.pwh
    if levels.pwl is not None:
        out["pwl"] = levels.pwl
    return out


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", _page_ctx(request, active="home")
    )


@app.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
):
    user = authenticate(username, password)
    if user and user.get("is_admin"):
        return RedirectResponse("/login?err=admin", status_code=303)
    if not user:
        return RedirectResponse("/login?err=1", status_code=303)
    if not channel_allowed(user):
        return RedirectResponse("/login?err=channel", status_code=303)
    login_session(request, user, admin_panel=False)
    dest = next if next.startswith("/") and not next.startswith("//") else "/"
    return RedirectResponse(dest, status_code=303)


@app.get("/logout")
async def logout(request: Request):
    logout_session(request)
    return RedirectResponse("/login", status_code=303)


@app.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request, error: str = ""):
    return templates.TemplateResponse(
        request,
        "change_password.html",
        _page_ctx(request, error=error),
    )


@app.post("/change-password")
async def change_password_post(
    request: Request,
    password: str = Form(...),
    password2: str = Form(...),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if password != password2:
        return RedirectResponse("/change-password?error=mismatch", status_code=303)
    err = set_user_password(user["id"], password, force_change=False)
    if err:
        return templates.TemplateResponse(
            request,
            "change_password.html",
            _page_ctx(request, error=err),
        )
    clear_must_change(user["id"])
    return RedirectResponse("/", status_code=303)


@app.get("/bigjay_controller/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        _page_ctx(request, error=error),
    )


@app.post("/bigjay_controller/login")
async def admin_login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = authenticate(username, password)
    if not user or not user.get("is_admin"):
        return RedirectResponse(
            "/bigjay_controller/login?error=1", status_code=303
        )
    login_session(request, user, admin_panel=True)
    return RedirectResponse("/bigjay_controller", status_code=303)


@app.get("/bigjay_controller", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        _page_ctx(request, active="admin"),
    )


@app.get("/bigjay_controller/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, msg: str = "", error: str = ""):
    return templates.TemplateResponse(
        request,
        "admin/users.html",
        _page_ctx(request, users=list_users(), msg=msg, error=error),
    )


@app.post("/bigjay_controller/users/create")
async def admin_users_create(
    request: Request,
    username: str = Form(...),
    mobile: str = Form(""),
    allow_enrich: str = Form(""),
    allow_stable: str = Form(""),
):
    uid, err = create_user(
        username=username,
        mobile=mobile,
        allow_enrich=allow_enrich == "on",
        allow_stable=allow_stable == "on",
    )
    if err:
        return RedirectResponse(
            f"/bigjay_controller/users?error={quote(err)}", status_code=303
        )
    return RedirectResponse(
        "/bigjay_controller/users?msg=created", status_code=303
    )


@app.post("/bigjay_controller/users/{user_id}/reset-password")
async def admin_users_reset(user_id: int):
    admin_reset_user_password(user_id)
    return RedirectResponse("/bigjay_controller/users?msg=reset", status_code=303)


@app.post("/bigjay_controller/run-now")
async def admin_run_now():
    run_scheduled_report()
    return RedirectResponse("/bigjay_controller?msg=run", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    sched = _scheduled_only(request)
    report_4h = _ensure_price_levels(get_latest_report("4h", scheduled_only=sched))
    report_daily = _ensure_price_levels(
        get_latest_report("daily", scheduled_only=sched)
    )
    ensure_report_chart(report_4h)
    ensure_report_chart(report_daily)
    return templates.TemplateResponse(
        request,
        "home.html",
        _page_ctx(
            request,
            report_4h=report_4h,
            report_daily=report_daily,
            report_4h_has_chart=report_has_chart(
                report_4h.get("report_code") if report_4h else None
            ),
            report_daily_has_chart=report_has_chart(
                report_daily.get("report_code") if report_daily else None
            ),
            active="home",
        ),
    )


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    period: str = "day",
    date: str = "",
    from_date: str = "",
    to_date: str = "",
    msg: str = "",
    err: str = "",
):
    if period not in ("day", "week", "month", "range"):
        period = "day"

    sched = _scheduled_only(request)
    if period == "range" and from_date and to_date:
        start_iso, end_iso = _range_custom_tehran(from_date, to_date)
        items = list_reports(
            start_iso=start_iso, end_iso=end_iso, scheduled_only=sched
        )
    elif period == "range":
        items = []
    else:
        anchor = date or None
        start_iso, end_iso = _range_for_period(period, anchor)
        items = list_reports(
            start_iso=start_iso, end_iso=end_iso, scheduled_only=sched
        )

    grouped = _group_by_date(items)

    return templates.TemplateResponse(
        request,
        "reports.html",
        _page_ctx(
            request,
            active="reports",
            period=period,
            date=date,
            from_date=from_date,
            to_date=to_date,
            grouped=grouped,
            count=len(items),
            msg=msg,
            err=err,
        ),
    )


@app.get("/reports/backtest", response_class=HTMLResponse)
@app.post("/reports/backtest", response_class=HTMLResponse)
async def reports_backtest(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.get("is_admin"):
        return RedirectResponse("/reports?err=فقط+ادمین", status_code=303)

    from zoneinfo import ZoneInfo

    from optionflow.flow_backtest import run_flow_backtest
    from optionflow.tehran_time import TEHRAN

    default_as_of = (datetime.now(TEHRAN) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    as_of = default_as_of
    lookback = "2"
    forward = "4"
    err = ""
    result = None
    chart_b64 = ""
    if request.method == "POST":
        form = await request.form()
        as_of = str(form.get("as_of") or default_as_of)
        lookback = str(form.get("lookback") or "2")
        forward = str(form.get("forward") or "4")
        try:
            moment = datetime.fromisoformat(as_of)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=ZoneInfo("Asia/Tehran"))
            result = run_flow_backtest(
                moment,
                lookback_hours=float(lookback),
                forward_hours=float(forward),
            )
            if result.chart_png:
                import base64

                chart_b64 = base64.b64encode(result.chart_png).decode("ascii")
        except ValueError as exc:
            err = str(exc)
        except Exception:
            logger.exception("flow backtest failed")
            err = "خواندن دادهٔ گذشته ناموفق بود."
    return templates.TemplateResponse(
        request,
        "reports_backtest.html",
        _page_ctx(
            request,
            active="reports",
            as_of=as_of,
            lookback=lookback,
            forward=forward,
            err=err,
            result=result,
            chart_b64=chart_b64,
        ),
    )


@app.post("/reports/generate")
async def reports_generate(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.get("is_admin"):
        return RedirectResponse("/reports?err=فقط+ادمین", status_code=303)
    try:
        run_scheduled_report()
    except Exception:
        logger.exception("manual report generate failed")
        return RedirectResponse("/reports?err=تولید+گزارش+ناموفق+بود", status_code=303)
    return RedirectResponse("/reports?msg=گزارش+دستی+ساخته+شد", status_code=303)


@app.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_detail(request: Request, report_id: int):
    report = get_report(report_id)
    if not report:
        return RedirectResponse("/reports", status_code=302)
    if _scheduled_only(request) and report.get("is_manual"):
        return RedirectResponse("/reports", status_code=302)
    ensure_report_chart(report)
    return templates.TemplateResponse(
        request,
        "report_detail.html",
        _page_ctx(
            request,
            active="reports",
            report=report,
            has_chart=report_has_chart(report.get("report_code")),
        ),
    )


@app.get("/patterns", response_class=HTMLResponse)
async def patterns_menu(request: Request):
    try:
        get_cached_scan(_patterns_dir)
        get_cached_behavior_scan(_patterns_dir, data_root=data_dir(), notify=False)
    except Exception:
        logger.exception("patterns menu scan failed")

    start_iso = (
        datetime.now(timezone.utc) - timedelta(hours=24)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    recent = list_all_pattern_events(start_iso=start_iso, limit=300)
    grouped_recent = _group_by_date(recent)

    return templates.TemplateResponse(
        request,
        "patterns_menu.html",
        _page_ctx(
            request,
            active="patterns",
            menu_items=_pattern_menu_items(),
            grouped_recent=grouped_recent,
            recent_count=len(recent),
        ),
    )


@app.get("/patterns/event/{event_id}", response_class=HTMLResponse)
async def pattern_event_detail(request: Request, event_id: int):
    event = get_pattern_event(event_id)
    if not event:
        return RedirectResponse("/patterns", status_code=302)
    cache_ts = pattern_cache_timestamp()
    chart_payload = payload_from_pattern_event(event)
    png = ""
    if event.get("chart_file") and not chart_payload:
        png = f"/pattern-charts/{event['chart_file']}?v={cache_ts}"
    live_ctx = _live_chart_ctx(
        chart_payload,
        dom_id=f"live-ov-ev-{event_id}",
        poll_url=f"/api/chart/live/pattern/event/{event_id}",
    )
    live_ctx["chart_png_src"] = png
    live_ctx["chart_png_alt"] = f"چارت {event.get('title_fa', '')}"
    return templates.TemplateResponse(
        request,
        "pattern_event.html",
        _page_ctx(
            request,
            active="patterns",
            event=event,
            category_label=_category_fa(event["category"]),
            cache_ts=cache_ts,
            **live_ctx,
        ),
    )


@app.get("/patterns/{category}", response_class=HTMLResponse)
async def pattern_category_page(
    request: Request,
    category: str,
    period: str = "day",
    date: str = "",
    from_date: str = "",
    to_date: str = "",
    tf: str = "",
    min_profit: str = "",
):
    if category not in PATTERN_TABS:
        return RedirectResponse("/patterns", status_code=302)
    if period not in ("day", "week", "month", "range"):
        period = "day"
    tf = tf if tf in PATTERN_TF_LABELS else ""
    min_profit_raw = (min_profit or "").strip()
    min_profit_pct = _parse_min_profit_pct(min_profit_raw)
    filter_qs = _pattern_filter_qs(tf=tf, min_profit=min_profit_raw)

    if category == "meaningful_behavior":
        get_cached_behavior_scan(
            _patterns_dir, data_root=data_dir(), notify=True
        )
    else:
        get_cached_scan(_patterns_dir)

    if period == "range" and from_date and to_date:
        start_iso, end_iso = _range_custom_tehran(from_date, to_date)
        items = list_pattern_events(
            category, start_iso=start_iso, end_iso=end_iso
        )
    elif period == "range":
        items = []
    else:
        anchor = date or None
        start_iso, end_iso = _range_for_pattern_period(period, anchor)
        items = list_pattern_events(
            category, start_iso=start_iso, end_iso=end_iso
        )

    raw_count = len(items)
    items = _filter_pattern_timeline(
        items, timeframe=tf, min_profit_pct=min_profit_pct
    )
    grouped = _group_by_date(items)
    sub = (
        "Deribit · فلو · ۱h (burst 20m / baseline 4h)"
        if category == "meaningful_behavior"
        else "BTCUSDT · ۵m / ۱۵m / ۱h"
    )

    return templates.TemplateResponse(
        request,
        "pattern_timeline.html",
        _page_ctx(
            request,
            active="patterns",
            category=category,
            category_label=_category_fa(category),
            period=period,
            date=date,
            from_date=from_date,
            to_date=to_date,
            tf_filter=tf,
            min_profit=min_profit_raw,
            min_profit_pct=min_profit_pct,
            filter_qs=filter_qs,
            tf_labels=PATTERN_TF_LABELS,
            grouped=grouped,
            count=len(items),
            raw_count=raw_count,
            subheader=sub,
        ),
    )


@app.get("/backtest", response_class=HTMLResponse)
async def backtest_page(
    request: Request,
    tab: str = "triangle",
    run_id: int = 0,
):
    if tab not in BACKTEST_TABS:
        tab = "triangle"
    active_run = get_backtest_run(run_id) if run_id else None
    return templates.TemplateResponse(
        request,
        "backtest.html",
        _page_ctx(
            request,
            active="menu",
            tab=tab,
            run_id=run_id,
            active_run=active_run,
            category_labels={
                "triangle": "مثلث فشرده",
                "flag": "الگوی پرچم",
                "divergence": "واگرایی RSI",
                "trendline": "ترندلاین",
                "channel": "کانال",
                "ema50": "EMA50",
                "three_rp": "3BRP",
            },
            bt_tf_labels=(
                {"1h": "۱ ساعت"}
                if tab == "three_rp"
                else {
                    "1m": "۱ دقیقه",
                    "5m": "۵ دقیقه",
                    "15m": "۱۵ دقیقه",
                    "1h": "۱ ساعت",
                    "4h": "۴ ساعت",
                    "1d": "روزانه",
                }
            ),
        ),
    )


@app.get("/backtest/reports", response_class=HTMLResponse)
async def backtest_reports_page(request: Request):
    runs = list_backtest_runs(limit=80)
    labels = {
        "triangle": "مثلث فشرده",
        "flag": "الگوی پرچم",
        "divergence": "واگرایی RSI",
        "trendline": "ترندلاین",
        "channel": "کانال",
        "ema50": "EMA50",
        "three_rp": "3BRP",
    }
    return templates.TemplateResponse(
        request,
        "backtest_reports.html",
        _page_ctx(
            request,
            active="menu", runs=runs, category_labels=labels, bt_tf_labels={
                "1m": "۱ دقیقه",
                "5m": "۵ دقیقه",
                "15m": "۱۵ دقیقه",
                "1h": "۱ ساعت",
                "4h": "۴ ساعت",
                "1d": "روزانه",
            }),
    )


@app.get("/backtest/reports/{run_id}", response_class=HTMLResponse)
async def backtest_report_detail(request: Request, run_id: int):
    run = get_backtest_run(run_id)
    if not run:
        return RedirectResponse("/backtest/reports", status_code=302)
    labels = {
        "triangle": "مثلث فشرده",
        "flag": "الگوی پرچم",
        "divergence": "واگرایی RSI",
        "trendline": "ترندلاین",
        "channel": "کانال",
        "ema50": "EMA50",
        "three_rp": "3BRP",
    }
    return templates.TemplateResponse(
        request,
        "backtest_report_detail.html",
        _page_ctx(request, active="menu", run=run, category_labels=labels),
    )


@app.get("/backtest/api/run/{run_id}")
async def backtest_run_api(run_id: int):
    run = get_backtest_run(run_id)
    if not run:
        return JSONResponse({"error": "not_found"}, status_code=404)
    payload: dict[str, Any] = {
        "id": run["id"],
        "status": run["status"],
        "progress_pct": run["progress_pct"],
        "findings_count": run["findings_count"],
        "success_count": run["success_count"],
        "fail_count": run["fail_count"],
        "error_message": run.get("error_message") or "",
    }
    if run["status"] in ("done", "error"):
        payload["findings"] = run.get("findings") or []
    return JSONResponse(payload)


@app.get("/backtest/api/runs")
async def backtest_runs_api():
    """وضعیت خلاصهٔ همهٔ بکتست‌ها — برای به‌روزرسانی زندهٔ آرشیو."""
    runs = list_backtest_runs(limit=80)
    return JSONResponse(
        {
            "runs": [
                {
                    "id": r["id"],
                    "status": r["status"],
                    "progress_pct": r["progress_pct"],
                    "success_count": r["success_count"],
                    "fail_count": r["fail_count"],
                    "findings_count": r["findings_count"],
                    "error_message": r.get("error_message") or "",
                }
                for r in runs
            ]
        }
    )


@app.post("/backtest/api/run/{run_id}/cancel")
async def backtest_run_cancel(request: Request, run_id: int):
    request_cancel_backtest(run_id)
    referer = (request.headers.get("referer") or "").strip()
    if not referer or "/backtest" not in referer:
        referer = "/backtest/reports"
    return RedirectResponse(referer, status_code=303)


@app.get("/menu/candles", response_class=HTMLResponse)
async def menu_candles_page(request: Request):
    return templates.TemplateResponse(
        request,
        "menu_candles.html",
        _page_ctx(
            request,
            active="menu",
            cache_rows=cache_status(data_dir()),
            history_dl=history_download_state(),
        ),
    )


@app.get("/menu/candles/api/status")
async def menu_candles_api_status():
    return JSONResponse(
        {
            "download": history_download_state(),
            "cache": cache_status(data_dir()),
        }
    )


@app.post("/menu/candles/download")
async def menu_candles_download(interval: str = Form("all")):
    iv = None if interval in ("", "all") else interval
    if iv and iv not in BACKTEST_INTERVALS:
        iv = None
    started = start_history_download(interval=iv)
    q = "dl=busy" if not started else "dl=started"
    return RedirectResponse(f"/menu/candles?{q}", status_code=303)


@app.get("/menu/indicators", response_class=HTMLResponse)
async def menu_indicators_page(request: Request, msg: str = "", err: str = ""):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    uid = int(user["id"])
    items = list_indicators(
        user_id=uid, is_admin=bool(user.get("is_admin"))
    )
    return templates.TemplateResponse(
        request,
        "menu_indicators.html",
        _page_ctx(request, active="menu", items=items, msg=msg, err=err),
    )


@app.get("/menu/indicators/new", response_class=HTMLResponse)
async def menu_indicator_new(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "menu_indicator_form.html",
        _page_ctx(request, active="menu", indicator=None, err=""),
    )


@app.get("/menu/indicators/{indicator_id}", response_class=HTMLResponse)
async def menu_indicator_detail(request: Request, indicator_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    row = get_indicator(indicator_id)
    if not row:
        return RedirectResponse("/menu/indicators", status_code=302)
    if not user.get("is_admin") and int(row["user_id"]) != int(user["id"]):
        return RedirectResponse("/menu/indicators", status_code=302)
    return templates.TemplateResponse(
        request,
        "menu_indicator_detail.html",
        _page_ctx(
            request,
            active="menu",
            indicator=row,
            can_edit=user_can_edit(user, row),
            tv_fields_json=tv_fields_json(row),
            chart_tf="15m",
        ),
    )


@app.get("/api/indicators/{indicator_id}/tv-inputs")
async def api_indicator_tv_inputs(request: Request, indicator_id: int):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "auth"}, status_code=401)
    row = get_indicator(indicator_id)
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if not user.get("is_admin") and int(row["user_id"]) != int(user["id"]):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    lang = str(row.get("language") or "pine")
    fields = parse_pine_inputs(str(row.get("source_code") or "")) if lang == "pine" else []
    return JSONResponse({"language": lang, "fields": fields})


@app.post("/api/indicators/{indicator_id}/live-chart")
async def api_indicator_live_chart(request: Request, indicator_id: int):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "auth"}, status_code=401)
    row = get_indicator(indicator_id)
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if not user.get("is_admin") and int(row["user_id"]) != int(user["id"]):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    tf = str(body.get("timeframe") or body.get("tf") or "15m")
    settings = body.get("settings") if isinstance(body.get("settings"), dict) else {}
    payload = build_indicator_live_payload(
        language=str(row.get("language") or "pine"),
        source_code=str(row.get("source_code") or ""),
        settings=settings,
        timeframe=tf,
    )
    if not payload:
        return JSONResponse({"error": "no_data"}, status_code=503)
    return JSONResponse(payload)


@app.get("/menu/indicators/{indicator_id}/edit", response_class=HTMLResponse)
async def menu_indicator_edit(request: Request, indicator_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    row = get_indicator(indicator_id)
    if not row or not user_can_edit(user, row):
        return RedirectResponse("/menu/indicators", status_code=302)
    return templates.TemplateResponse(
        request,
        "menu_indicator_form.html",
        _page_ctx(request, active="menu", indicator=row, err=""),
    )


@app.post("/menu/indicators/save")
async def menu_indicator_save(
    request: Request,
    title_fa: str = Form(...),
    source_code: str = Form(...),
    slug: str = Form(""),
    description_fa: str = Form(""),
    language: str = Form("pine"),
    indicator_id: str = Form(""),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    uid = int(user["id"])
    iid: int | None = None
    raw_id = (indicator_id or "").strip()
    if raw_id.isdigit():
        iid = int(raw_id)
        row = get_indicator(iid)
        if not row or not user_can_edit(user, row):
            return RedirectResponse("/menu/indicators", status_code=303)
    new_id, err = save_indicator(
        user_id=uid,
        title_fa=title_fa,
        source_code=source_code,
        slug=slug,
        description_fa=description_fa,
        language=language,
        indicator_id=iid,
    )
    if err or new_id is None:
        return templates.TemplateResponse(
            request,
            "menu_indicator_form.html",
            _page_ctx(
                request,
                active="menu",
                indicator={
                    "id": iid,
                    "title_fa": title_fa,
                    "description_fa": description_fa,
                    "language": language,
                    "source_code": source_code,
                    "slug": slug,
                }
                if iid
                else {
                    "title_fa": title_fa,
                    "description_fa": description_fa,
                    "language": language,
                    "source_code": source_code,
                    "slug": slug,
                },
                err=err or "خطا",
            ),
            status_code=400,
        )
    return RedirectResponse("/menu/indicators?msg=ذخیره+شد", status_code=303)


@app.post("/menu/indicators/{indicator_id}/delete")
async def menu_indicator_delete(request: Request, indicator_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    row = get_indicator(indicator_id)
    if not row or not user_can_edit(user, row):
        return RedirectResponse("/menu/indicators", status_code=303)
    delete_indicator(indicator_id)
    return RedirectResponse("/menu/indicators?msg=حذف+شد", status_code=303)


def _parse_backtest_pct(raw: str) -> float | None:
    s = (raw or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if 0.1 <= v <= 2.0:
        return v
    return None


@app.post("/backtest/start")
async def backtest_start(
    tab: str = Form("triangle"),
    date_from: str = Form(...),
    date_to: str = Form(...),
    timeframe: str = Form("1h"),
    target_profit_pct: str = Form(""),
    stop_loss_pct: str = Form(""),
    entry_on_early: str = Form(""),
):
    if tab not in BACKTEST_TABS:
        tab = "triangle"
    if tab == "three_rp":
        timeframe = "1h"
    elif timeframe not in ("1m", "5m", "15m", "1h", "4h", "1d"):
        timeframe = "1h"
    tp = _parse_backtest_pct(target_profit_pct)
    sl = _parse_backtest_pct(stop_loss_pct)
    early_entry = (entry_on_early or "").strip().lower() in ("1", "on", "true", "yes")
    run_id = start_backtest_job(
        category=tab,
        timeframe=timeframe,
        date_from=date_from,
        date_to=date_to,
        target_profit_pct=tp,
        stop_loss_pct=sl,
        entry_on_early=early_entry,
    )
    return RedirectResponse(f"/backtest?tab={tab}&run_id={run_id}", status_code=303)


SCALP_BT_TF_LABELS = {
    "5m": "۵ دقیقه",
    "15m": "۱۵ دقیقه",
    "1h": "۱ ساعت",
    "4h": "۴ ساعت",
}


def _scalp_scenario_labels() -> dict[str, str]:
    return {s["scenario_id"]: s["title_fa"] for s in list_scenarios()}


@app.get("/scalp", response_class=HTMLResponse)
async def scalp_menu(request: Request):
    try:
        get_cached_scalp_scan(_patterns_dir, list_scenarios(enabled_only=True))
    except Exception:
        logger.exception("scalp menu scan failed")
    start_iso = (
        datetime.now(timezone.utc) - timedelta(hours=24)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    recent = list_scalp_events(start_iso=start_iso, limit=200)
    grouped_recent = _group_by_date(recent)
    return templates.TemplateResponse(
        request,
        "scalp_menu.html",
        _page_ctx(
            request,
            active="scalp",
            scenarios=list_scenarios(),
            grouped_recent=grouped_recent,
        ),
    )


@app.get("/scalp/scenario/{scenario_id}", response_class=HTMLResponse)
async def scalp_scenario_page(request: Request, scenario_id: str):
    scenario = get_scenario(scenario_id)
    if not scenario:
        return RedirectResponse("/scalp", status_code=302)
    items = list_scalp_events(scenario_id=scenario_id, limit=120)
    grouped = _group_by_date(items)
    return templates.TemplateResponse(
        request,
        "scalp_scenario.html",
        _page_ctx(
            request,
            active="scalp",
            scenario=scenario,
            grouped=grouped,
        ),
    )


@app.post("/scalp/scenario/{scenario_id}/settings")
async def scalp_scenario_settings(
    request: Request,
    scenario_id: str,
    enabled: str = Form(""),
    tp_rr: float = Form(1.5),
    stop_atr_mult: float = Form(0.4),
    max_hold_bars: int = Form(24),
):
    user = current_user(request)
    if not user or not user.get("is_admin"):
        return RedirectResponse("/scalp", status_code=303)
    sc = get_scenario(scenario_id)
    if not sc:
        return RedirectResponse("/scalp", status_code=303)
    params = dict(sc.get("params") or {})
    params["tp_rr"] = tp_rr
    params["stop_atr_mult"] = stop_atr_mult
    params["max_hold_bars"] = max_hold_bars
    update_scenario_settings(
        scenario_id, enabled=bool(enabled), params=params
    )
    invalidate_scalp_cache()
    return RedirectResponse(f"/scalp/scenario/{scenario_id}", status_code=303)


@app.get("/scalp/event/{event_id}", response_class=HTMLResponse)
async def scalp_event_detail(request: Request, event_id: int):
    event = get_scalp_event(event_id)
    if not event:
        return RedirectResponse("/scalp", status_code=302)
    cache_ts = scalp_cache_timestamp()
    chart_payload = payload_from_scalp_event(event)
    png = ""
    if event.get("chart_file") and not chart_payload:
        png = f"/pattern-charts/{event['chart_file']}?v={cache_ts}"
    live_ctx = _live_chart_ctx(
        chart_payload,
        dom_id=f"live-ov-scalp-{event_id}",
        poll_url=f"/api/chart/live/scalp/event/{event_id}",
    )
    live_ctx["chart_png_src"] = png
    live_ctx["chart_png_alt"] = f"چارت {event.get('title_fa', '')}"
    return templates.TemplateResponse(
        request,
        "scalp_event.html",
        _page_ctx(
            request,
            active="scalp",
            event=event,
            cache_ts=cache_ts,
            **live_ctx,
        ),
    )


@app.post("/scalp/refresh")
async def scalp_refresh():
    invalidate_scalp_cache()
    get_cached_scalp_scan(_patterns_dir, list_scenarios(enabled_only=True))
    return RedirectResponse("/scalp", status_code=303)


@app.get("/scalp/backtest", response_class=HTMLResponse)
async def scalp_backtest_page(
    request: Request,
    scenario_id: str = "range_break",
    run_id: int = 0,
):
    scenarios = list_scenarios()
    ids = {s["scenario_id"] for s in scenarios}
    if scenario_id not in ids:
        scenario_id = scenarios[0]["scenario_id"] if scenarios else "range_break"
    active_run = get_scalp_backtest_run(run_id) if run_id else None
    today = datetime.now(timezone.utc).date()
    default_to = today.isoformat()
    default_from = (today - timedelta(days=13)).isoformat()
    return templates.TemplateResponse(
        request,
        "scalp_backtest.html",
        _page_ctx(
            request,
            active="scalp",
            scenarios=scenarios,
            scenario_id=scenario_id,
            run_id=run_id,
            active_run=active_run,
            bt_tf_labels=SCALP_BT_TF_LABELS,
            default_date_from=default_from,
            default_date_to=default_to,
        ),
    )


@app.get("/scalp/backtest/reports", response_class=HTMLResponse)
async def scalp_backtest_reports(request: Request):
    runs = list_scalp_backtest_runs(limit=60)
    return templates.TemplateResponse(
        request,
        "scalp_backtest_reports.html",
        _page_ctx(
            request,
            active="scalp",
            runs=runs,
            scenario_labels=_scalp_scenario_labels(),
        ),
    )


@app.get("/scalp/backtest/reports/{run_id}", response_class=HTMLResponse)
async def scalp_backtest_report_detail(request: Request, run_id: int):
    run = get_scalp_backtest_run(run_id)
    if not run:
        return RedirectResponse("/scalp/backtest/reports", status_code=302)
    labels = _scalp_scenario_labels()
    return templates.TemplateResponse(
        request,
        "scalp_backtest_report_detail.html",
        _page_ctx(
            request,
            active="scalp",
            run=run,
            scenario_label=labels.get(run["scenario_id"], run["scenario_id"]),
        ),
    )


@app.get("/scalp/backtest/api/run/{run_id}")
async def scalp_backtest_run_api(run_id: int):
    run = get_scalp_backtest_run(run_id)
    if not run:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(
        {
            "id": run["id"],
            "status": run["status"],
            "progress_pct": run.get("progress_pct", 0),
            "success_count": run.get("success_count", 0),
            "fail_count": run.get("fail_count", 0),
            "findings_count": run.get("findings_count", 0),
            "error_message": run.get("error_message") or "",
        }
    )


@app.post("/scalp/backtest/api/run/{run_id}/cancel")
async def scalp_backtest_cancel(request: Request, run_id: int):
    request_cancel_scalp_backtest(run_id)
    referer = request.headers.get("referer") or "/scalp/backtest/reports"
    return RedirectResponse(referer, status_code=303)


@app.post("/scalp/backtest/start")
async def scalp_backtest_start(
    scenario_id: str = Form(...),
    timeframe: str = Form(...),
    date_from: str = Form(...),
    date_to: str = Form(...),
):
    if get_scenario(scenario_id) is None:
        return RedirectResponse("/scalp/backtest", status_code=303)
    run_id = start_scalp_backtest_job(
        scenario_id=scenario_id,
        timeframe=timeframe,
        date_from=date_from,
        date_to=date_to,
    )
    q = urlencode({"scenario_id": scenario_id, "run_id": run_id})
    return RedirectResponse(f"/scalp/backtest?{q}", status_code=303)


@app.post("/patterns/refresh")
async def patterns_refresh(category: str = Form("triangle")):
    if category not in PATTERN_TABS:
        category = "triangle"
    if category == "meaningful_behavior":
        invalidate_behavior_cache()
        run_behavior_scan_and_notify(_patterns_dir, data_dir())
    else:
        invalidate_pattern_cache()
        get_cached_scan(_patterns_dir)
    return RedirectResponse(f"/patterns/{category}", status_code=303)


def _position_report_bounds(
    period: str, from_date: str, to_date: str
) -> tuple[str, str]:
    if period == "week":
        return tehran_week_sat_fri_bounds_utc(None)
    if period == "month":
        return tehran_jalali_month_bounds_utc(None)
    if period == "range" and from_date and to_date:
        return _range_custom_tehran(from_date, to_date)
    return tehran_last_24h_bounds_utc()


@app.get("/position", response_class=HTMLResponse)
async def position_page(
    request: Request,
    tab: str = "wallet",
    msg: str = "",
    err: str = "",
    period: str = "day",
    from_date: str = "",
    to_date: str = "",
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    uid = int(user["id"])
    if tab not in ("wallet", "settings", "open", "report"):
        tab = "wallet"
    if period not in ("day", "week", "month", "range"):
        period = "day"
    process_signals_for_user(uid)
    wallet = get_wallet(uid)
    cfg = get_config(uid)
    mark = latest_btc_price()
    open_pos = list_positions(uid, status="open", limit=30)
    report_start, report_end = _position_report_bounds(period, from_date, to_date)
    closed = list_positions(
        uid,
        closed_only=True,
        opened_from=report_start,
        opened_to=report_end,
        limit=300,
    )
    ledger = list_ledger(uid, limit=40)
    return templates.TemplateResponse(
        request,
        "position.html",
        _page_ctx(
            request,
            active="position",
            tab=tab,
            msg=msg,
            err=err,
            wallet=wallet,
            config=cfg,
            locked_margin=locked_margin(uid),
            mark_price=mark,
            open_positions=open_pos,
            closed_positions=closed,
            period=period,
            from_date=from_date,
            to_date=to_date,
            ledger=ledger,
            pattern_categories=PATTERN_CATEGORIES,
            pattern_timeframes=PATTERN_TIMEFRAMES,
            pattern_early_categories=PATTERN_EARLY_CATEGORIES,
            tf_labels=PATTERN_TF_LABELS,
            scalp_scenarios=SCALP_SCENARIOS,
            report_kinds=REPORT_KINDS,
            fee_profiles=list_fee_profiles(),
            fee_profile_label=fee_profile_summary_fa(cfg.get("fee_profile_id")),
            category_fa=_category_fa,
            status_fa=_position_status_fa,
            source_fa=_position_source_fa,
            ledger_fa=_ledger_kind_fa,
            unrealized=unrealized_pnl,
            report_fresh_minutes=REPORT_FRESH_MINUTES,
        ),
    )


@app.post("/position/wallet/deposit")
async def position_deposit(request: Request, amount: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        val = float(amount.replace(",", "."))
        deposit(int(user["id"]), val)
        return RedirectResponse("/position?tab=wallet&msg=واریز+انجام+شد", status_code=303)
    except (ValueError, TypeError):
        return RedirectResponse("/position?tab=wallet&err=مبلغ+نامعتبر", status_code=303)


@app.post("/position/settings")
async def position_settings_save(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    uid = int(user["id"])
    try:
        save_config(
            uid,
            enabled=form.get("enabled") == "1",
            margin_usdt=float(form.get("margin_usdt") or 100),
            leverage=float(form.get("leverage") or 5),
            stop_loss_pct=float(form.get("stop_loss_pct") or 1),
            take_profit_pct=float(form.get("take_profit_pct") or 0.5),
            fee_profile_id=str(form.get("fee_profile_id") or "binance_usdt_vip0"),
            pattern_categories=form.getlist("pattern_categories"),
            pattern_timeframes=pattern_timeframes_from_form(
                [str(v) for v in form.getlist("pattern_timeframes")]
            ),
            pattern_early=[str(v) for v in form.getlist("pattern_early")],
            scalp_scenarios=form.getlist("scalp_scenarios"),
            report_kinds=form.getlist("report_kinds"),
        )
        return RedirectResponse("/position?tab=settings&msg=ذخیره+شد", status_code=303)
    except (ValueError, TypeError):
        return RedirectResponse("/position?tab=settings&err=ورودی+نامعتبر", status_code=303)


@app.post("/position/run")
async def position_run_scan(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    uid = int(user["id"])
    stats = process_signals_for_user(uid)
    msg = f"باز+{stats['opened']}+·+بسته+{stats['closed']}"
    return RedirectResponse(f"/position?tab=open&msg={msg}", status_code=303)


@app.post("/position/close/{position_id}")
async def position_close_manual(request: Request, position_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    uid = int(user["id"])
    cfg = get_config(uid)
    mark = latest_btc_price()
    if mark is None:
        return RedirectResponse("/position?tab=open&err=قیمت+نامشخص", status_code=303)
    ok = close_position(
        uid,
        position_id,
        exit_price=mark,
        status="closed_manual",
        fee_rate=float(cfg["fee_rate"]),
    )
    if not ok:
        return RedirectResponse("/position?tab=open&err=پوزیشن+پیدا+نشد", status_code=303)
    return RedirectResponse("/position?tab=report&msg=بسته+شد", status_code=303)


@app.get("/position/api/live")
async def position_live_api(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "auth"}, status_code=401)
    uid = int(user["id"])
    return JSONResponse(live_open_state(uid))


@app.get("/api/nav/badges")
async def api_nav_badges(request: Request):
    path = (request.headers.get("referer") or "").split("?")[0]
    active: str | None = None
    if "/patterns" in path:
        active = "patterns"
    elif "/reports" in path:
        active = "reports"
    elif "/position" in path:
        active = "position"
    return JSONResponse(
        compute_nav_badges(
            request,
            active=active,
            scheduled_reports_only=_scheduled_only(request),
        )
    )


@app.get("/api/chart/live/patterns/scan")
async def api_live_chart_patterns_scan(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "auth"}, status_code=401)
    scan_data = get_cached_scan(_patterns_dir)
    for cat in PATTERN_TABS:
        if cat == "meaningful_behavior":
            continue
        hit = _first_live_hit_for_category(scan_data, cat)
        if hit is not None:
            payload = payload_from_pattern_hit(hit)
            if payload:
                return JSONResponse(
                    {
                        "candles": payload["candles"],
                        "overlays": payload["overlays"],
                        "viewport": payload.get("viewport"),
                    }
                )
    return JSONResponse({"candles": [], "overlays": {}})


@app.get("/api/chart/live/history")
async def api_live_chart_history(request: Request, tf: str = "5m", before: int = 0):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "auth"}, status_code=401)
    if before <= 0 or tf not in ("5m", "15m", "1h", "4h", "1d"):
        return JSONResponse({"candles": []})
    from optionflow.patterns.chart_overlays import candles_payload
    from optionflow.patterns.ohlc import load_btcusdt_before

    try:
        bars = load_btcusdt_before(tf, before, limit=500)
    except Exception:
        logger.exception("chart history fetch failed")
        return JSONResponse({"candles": []}, status_code=503)
    return JSONResponse({"candles": candles_payload(bars)})


@app.get("/api/chart/live/scalp/event/{event_id}")
async def api_live_chart_scalp_event(request: Request, event_id: int):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "auth"}, status_code=401)
    event = get_scalp_event(event_id)
    if not event:
        return JSONResponse({"error": "not_found"}, status_code=404)
    payload = payload_from_scalp_event(event)
    if not payload:
        return JSONResponse({"error": "no_data"}, status_code=503)
    return JSONResponse(
        {
            "candles": payload["candles"],
            "overlays": payload["overlays"],
            "viewport": payload.get("viewport"),
        }
    )


@app.get("/api/chart/live/pattern/event/{event_id}")
async def api_live_chart_pattern_event(request: Request, event_id: int):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "auth"}, status_code=401)
    event = get_pattern_event(event_id)
    if not event:
        return JSONResponse({"error": "not_found"}, status_code=404)
    payload = payload_from_pattern_event(event)
    if not payload:
        return JSONResponse({"error": "no_data"}, status_code=503)
    return JSONResponse(
        {
            "candles": payload["candles"],
            "overlays": payload["overlays"],
            "viewport": payload.get("viewport"),
        }
    )


@app.get("/api/chart/live/pattern/category/{category}")
async def api_live_chart_pattern_category(request: Request, category: str):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "auth"}, status_code=401)
    if category not in PATTERN_TABS or category == "meaningful_behavior":
        return JSONResponse({"error": "bad_category"}, status_code=400)
    scan_data = get_cached_scan(_patterns_dir)
    hit = _first_live_hit_for_category(scan_data, category)
    if hit is None:
        return JSONResponse({"candles": [], "overlays": {}})
    payload = payload_from_pattern_hit(hit)
    if not payload:
        return JSONResponse({"error": "no_data"}, status_code=503)
    return JSONResponse(
        {
            "candles": payload["candles"],
            "overlays": payload["overlays"],
            "viewport": payload.get("viewport"),
        }
    )


@app.get("/api/chart/live/position/{position_id}")
async def api_live_chart_position(request: Request, position_id: int):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "auth"}, status_code=401)
    uid = int(user["id"])
    pos = get_position(uid, position_id)
    if not pos:
        return JSONResponse({"error": "not_found"}, status_code=404)
    mark = latest_btc_price()
    payload = payload_from_position(pos, mark=mark)
    if not payload:
        return JSONResponse({"error": "no_data"}, status_code=503)
    return JSONResponse(
        {
            "candles": payload["candles"],
            "overlays": payload["overlays"],
            "viewport": payload.get("viewport"),
            "mark": mark,
        }
    )


@app.get("/position/open/{position_id}", response_class=HTMLResponse)
async def position_open_detail(request: Request, position_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    uid = int(user["id"])
    pos = get_position(uid, position_id)
    if not pos:
        return RedirectResponse("/position?tab=open&err=پوزیشن+پیدا+نشد", status_code=303)
    mark = latest_btc_price()
    pnl = unrealized_pnl(pos, mark) if mark is not None and pos.get("status") == "open" else pos.get("pnl_usdt")
    chart_payload = payload_from_position(pos, mark=mark)
    live_ctx = _live_chart_ctx(
        chart_payload,
        dom_id=f"live-ov-pos-{position_id}",
        poll_url=f"/api/chart/live/position/{position_id}",
    )
    if not chart_payload:
        live_ctx["chart_png_src"] = (
            f"/position/open/{position_id}/chart.png?t={pos.get('opened_at', '')}"
        )
        live_ctx["chart_png_alt"] = str(pos.get("signal_title") or "چارت پوزیشن")
    return templates.TemplateResponse(
        request,
        "position_open.html",
        _page_ctx(
            request,
            active="position",
            pos=pos,
            mark_price=mark,
            pnl_usdt=pnl,
            chart_levels_only=True,
            source_fa=_position_source_fa,
            status_fa=_position_status_fa,
            **live_ctx,
        ),
    )


@app.get("/position/open/{position_id}/chart.png")
async def position_open_chart_png(request: Request, position_id: int):
    user = current_user(request)
    if not user:
        return Response(status_code=401)
    uid = int(user["id"])
    pos = get_position(uid, position_id)
    if not pos:
        return Response(status_code=404)
    mark = latest_btc_price()
    png = render_paper_position_chart(pos, mark=mark)
    if not png:
        return Response(status_code=503)
    return Response(content=png, media_type="image/png")


@app.get("/menu", response_class=HTMLResponse)
async def app_menu_page(request: Request):
    return templates.TemplateResponse(
        request,
        "menu.html",
        _page_ctx(request, active="menu"),
    )


@app.get("/backtest/api/history")
async def backtest_history_api_legacy():
    """سازگاری با نسخهٔ قدیم — همان API صفحهٔ کندل‌ها."""
    return JSONResponse(
        {
            "download": history_download_state(),
            "cache": cache_status(data_dir()),
        }
    )


@app.post("/backtest/history/download")
async def backtest_history_download_legacy(interval: str = Form("all")):
    return RedirectResponse("/menu/candles", status_code=302)


TV_CHART_MARKETS = {
    "perp": ("BITUNIX:BTCUSDT.P", "BTCUSDT Perpetual · Bitunix"),
    "spot": ("BITUNIX:BTCUSDT", "BTCUSDT Spot · Bitunix"),
}
TV_CHART_INTERVALS = (
    ("5", "۵m"),
    ("15", "۱۵m"),
    ("60", "۱h"),
    ("240", "۴h"),
    ("D", "روز"),
)


@app.get("/v2", response_class=HTMLResponse)
async def chart_v2_page(request: Request):
    """چارت زندهٔ v2. گزارش ۴ساعته و روزانه را عوض نمی‌کند."""
    from app.v2_view import v2_chart_payload, v2_payload_json

    payload = v2_chart_payload()
    return templates.TemplateResponse(
        request,
        "chart_v2.html",
        _page_ctx(
            request,
            active="v2",
            caption=payload["caption"],
            payload_json=v2_payload_json(payload),
        ),
    )


@app.get("/api/v2/chart")
async def api_v2_chart(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "auth"}, status_code=401)
    from app.v2_view import v2_chart_payload

    return JSONResponse(v2_chart_payload())


@app.get("/chart", response_class=HTMLResponse)
async def live_bitunix_chart(
    request: Request,
    market: str = "perp",
    interval: str = "15",
):
    """چارت زنده TradingView — BTCUSDT روی Bitunix (اسپات یا perpetual)."""
    m = market if market in TV_CHART_MARKETS else "perp"
    valid_iv = {iv for iv, _ in TV_CHART_INTERVALS}
    iv = interval if interval in valid_iv else "15"
    symbol, symbol_label = TV_CHART_MARKETS[m]
    interval_label = next(l for k, l in TV_CHART_INTERVALS if k == iv)
    slug = symbol.replace(":", "-")
    return templates.TemplateResponse(
        request,
        "live_chart.html",
        _page_ctx(
            request,
            active="menu",
            market=m,
            interval=iv,
            tv_symbol=symbol,
            tv_interval=iv,
            symbol_label=symbol_label,
            interval_label=interval_label,
            tv_symbol_slug=slug,
            interval_links=TV_CHART_INTERVALS,
        ),
    )


@app.get("/telegram", response_class=HTMLResponse)
async def telegram_page(request: Request, msg: str = "", ok: str = ""):
    user = current_user(request)
    return templates.TemplateResponse(
        request,
        "telegram.html",
        _page_ctx(
            request,
            active="menu",
            bot_token=(user or {}).get("telegram_bot_token") or "",
            chat_id=(user or {}).get("telegram_chat_id") or "",
            enabled=bool((user or {}).get("telegram_enabled")),
            on_schedule=bool((user or {}).get("telegram_on_schedule", True)),
            message=msg,
            success=ok == "1",
        ),
    )


@app.post("/telegram")
async def telegram_save(
    request: Request,
    bot_token: str = Form(""),
    chat_id: str = Form(""),
    enabled: str = Form(""),
    on_schedule: str = Form(""),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    set_user_telegram(
        user["id"],
        bot_token=bot_token,
        chat_id=chat_id,
        enabled=enabled == "on",
        on_schedule=on_schedule == "on",
    )
    return RedirectResponse("/telegram?ok=1", status_code=303)


@app.post("/telegram/test")
async def telegram_test(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    token = user.get("telegram_bot_token") or ""
    chat_id = user.get("telegram_chat_id") or ""
    latest = get_latest_report(scheduled_only=_scheduled_only(request))
    if latest:
        ensure_report_chart(latest)
    text = latest["paragraph"] if latest else "تست OptionFlow — اتصال تلگرام برقرار است."
    if latest and latest.get("report_code") and report_has_chart(latest["report_code"]):
        path = data_dir() / "charts" / f"{latest['report_code']}.png"
        send_telegram_photo(
            path.read_bytes(),
            caption="BTCUSDT — مسیر سناریو",
            token=token,
            chat_id=chat_id,
        )
    ok, msg = send_telegram_message(text, token=token, chat_id=chat_id)
    return RedirectResponse(
        f"/telegram?ok={'1' if ok else '0'}&msg={quote(msg)}",
        status_code=303,
    )
