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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
from app.backtest_jobs import start_backtest_job
from app.backtest_store import get_backtest_run, list_backtest_runs
from app.history_jobs import history_download_state, start_history_download
from app.jobs import (
    run_scheduled_4h_report,
    run_scheduled_daily_report,
    run_scheduled_report,
    run_scheduled_behavior_scan,
)
from app.pattern_store import get_pattern_event, list_all_pattern_events, list_pattern_events
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
from optionflow.patterns.history import cache_status
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
from optionflow.price_levels import fetch_price_levels
from optionflow.tehran_time import (
    CRON_4H_HOURS,
    CRON_DAILY_HOUR,
    CRON_DAILY_MINUTE,
    REPORT_MINUTE,
    TEHRAN,
    format_date_tehran,
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
            body = html_mod.escape(m.group(2).strip())
            parts.append(f'<section class="report-section"><h3 class="report-section-title">{title}</h3>')
            if body:
                parts.append(f'<p class="report-section-body">{body}</p>')
            parts.append("</section>")
        else:
            parts.append(
                f'<p class="report-section-body">{html_mod.escape(block)}</p>'
            )
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
    }.get(category, category)


BACKTEST_TABS = ("triangle", "flag", "divergence", "trendline", "channel", "ema50")
PATTERN_TABS = BACKTEST_TABS + ("meaningful_behavior",)

PATTERN_HINTS: dict[str, str] = {
    "triangle": "BTCUSDT · شکست مثلث · 5m / 15m / 1h",
    "flag": "BTCUSDT · پرچم صعودی/نزولی",
    "divergence": "BTCUSDT · RSI BigBeluga · ورود و TP",
    "trendline": "BTCUSDT · شکست ترند · 0.5٪",
    "channel": "BTCUSDT · کانال قیمت",
    "ema50": "BTCUSDT · کراس EMA50",
    "meaningful_behavior": "Deribit · surge کال/پوت · هشدار تلگرام",
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


def _page_ctx(request: Request, **extra: Any) -> dict[str, Any]:
    user = current_user(request)
    return _template_ctx(
        request=request,
        auth_user=user,
        is_admin=bool(user and user.get("is_admin")),
        channel_label=deployment_channel_label(),
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
        "bias_fa": _bias_fa,
        "clean_paragraph": _clean_paragraph,
        "format_report_html": _format_prose_report_html,
        "category_fa": _category_fa,
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
        "Scheduler: 4h at :%s (hours %s); daily at %s:%s (Asia/Tehran)",
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
        ),
    )


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
    return templates.TemplateResponse(
        request,
        "pattern_event.html",
        _page_ctx(
            request,
            active="patterns",
            event=event,
            category_label=_category_fa(event["category"]),
            cache_ts=cache_ts,
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
        "Deribit · فلو آپشن"
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
            active="backtest",
            tab=tab,
            cache_rows=cache_status(data_dir()),
            run_id=run_id,
            active_run=active_run,
            history_dl=history_download_state(),
            category_labels={
                "triangle": "مثلث فشرده",
                "flag": "الگوی پرچم",
                "divergence": "واگرایی RSI",
                "trendline": "ترندلاین",
                "channel": "کانال",
                "ema50": "EMA50",
            },
            bt_tf_labels={
                "5m": "۵ دقیقه",
                "15m": "۱۵ دقیقه",
                "1h": "۱ ساعت",
                "4h": "۴ ساعت",
                "1d": "روزانه",
            },
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
    }
    return templates.TemplateResponse(
        request,
        "backtest_reports.html",
        _page_ctx(
            request,
            active="backtest", runs=runs, category_labels=labels, bt_tf_labels={
                "5m": "۵ دقیقه", "15m": "۱۵ دقیقه", "1h": "۱ ساعت", "4h": "۴ ساعت", "1d": "روزانه",
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
    }
    return templates.TemplateResponse(
        request,
        "backtest_report_detail.html",
        _page_ctx(request, active="backtest", run=run, category_labels=labels),
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


@app.get("/backtest/api/history")
async def backtest_history_api():
    return JSONResponse(
        {
            "download": history_download_state(),
            "cache": cache_status(data_dir()),
        }
    )


@app.post("/backtest/history/download")
async def backtest_history_download(
    interval: str = Form("all"),
):
    iv = None if interval in ("", "all") else interval
    if iv and iv not in ("5m", "15m", "1h", "4h", "1d"):
        iv = None
    started = start_history_download(interval=iv)
    q = "dl=busy" if not started else "dl=started"
    return RedirectResponse(f"/backtest?{q}", status_code=303)


@app.post("/backtest/start")
async def backtest_start(
    tab: str = Form("triangle"),
    date_from: str = Form(...),
    date_to: str = Form(...),
    timeframe: str = Form("1h"),
    target_profit_pct: str = Form(""),
):
    if tab not in BACKTEST_TABS:
        tab = "triangle"
    if timeframe not in ("5m", "15m", "1h", "4h", "1d"):
        timeframe = "1h"
    tp: float | None = None
    raw = (target_profit_pct or "").strip().replace(",", ".")
    if raw:
        try:
            v = float(raw)
            if 0.1 <= v <= 2.0:
                tp = v
        except ValueError:
            tp = None
    run_id = start_backtest_job(
        category=tab,
        timeframe=timeframe,
        date_from=date_from,
        date_to=date_to,
        target_profit_pct=tp,
    )
    return RedirectResponse(f"/backtest?tab={tab}&run_id={run_id}", status_code=303)


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


@app.get("/telegram", response_class=HTMLResponse)
async def telegram_page(request: Request, msg: str = "", ok: str = ""):
    user = current_user(request)
    return templates.TemplateResponse(
        request,
        "telegram.html",
        _page_ctx(
            request,
            active="telegram",
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
