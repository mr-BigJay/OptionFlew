from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.jobs import (
    run_scheduled_4h_report,
    run_scheduled_daily_report,
    run_scheduled_report,
)
from app.storage import (
    data_dir,
    ensure_report_chart,
    get_latest_report,
    get_report,
    get_setting,
    init_db,
    list_reports,
    report_has_chart,
    set_setting,
)
from app.telegram_notify import send_telegram_message, send_telegram_photo, telegram_enabled
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
    tehran_month_bounds_utc,
    tehran_week_bounds_utc,
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


def _template_ctx(**extra: Any) -> dict[str, Any]:
    return {
        "fmt_dt": _fmt_dt,
        "fmt_time": _fmt_time,
        "fmt_date_header": _fmt_day_header,
        "fmt_date": format_date_tehran,
        "bias_fa": _bias_fa,
        "clean_paragraph": _clean_paragraph,
        "format_report_html": _format_prose_report_html,
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
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
_charts_dir = data_dir() / "charts"
_charts_dir.mkdir(parents=True, exist_ok=True)
app.mount("/charts", StaticFiles(directory=str(_charts_dir)), name="charts")


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


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    report_4h = _ensure_price_levels(get_latest_report("4h"))
    report_daily = _ensure_price_levels(get_latest_report("daily"))
    ensure_report_chart(report_4h)
    ensure_report_chart(report_daily)
    return templates.TemplateResponse(
        request,
        "home.html",
        _template_ctx(
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

    if period == "range" and from_date and to_date:
        start_iso, end_iso = _range_custom_tehran(from_date, to_date)
        items = list_reports(start_iso=start_iso, end_iso=end_iso)
    elif period == "range":
        items = []
    else:
        anchor = date or None
        start_iso, end_iso = _range_for_period(period, anchor)
        items = list_reports(start_iso=start_iso, end_iso=end_iso)

    grouped = _group_by_date(items)

    return templates.TemplateResponse(
        request,
        "reports.html",
        _template_ctx(
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
    ensure_report_chart(report)
    return templates.TemplateResponse(
        request,
        "report_detail.html",
        _template_ctx(
            active="reports",
            report=report,
            has_chart=report_has_chart(report.get("report_code")),
        ),
    )


@app.get("/telegram", response_class=HTMLResponse)
async def telegram_page(request: Request, msg: str = "", ok: str = ""):
    return templates.TemplateResponse(
        request,
        "telegram.html",
        _template_ctx(
            active="telegram",
            bot_token=get_setting("telegram_bot_token", ""),
            chat_id=get_setting("telegram_chat_id", ""),
            enabled=telegram_enabled(),
            on_schedule=get_setting("telegram_on_schedule", "1") == "1",
            message=msg,
            success=ok == "1",
        ),
    )


@app.post("/telegram")
async def telegram_save(
    bot_token: str = Form(""),
    chat_id: str = Form(""),
    enabled: str = Form(""),
    on_schedule: str = Form(""),
):
    set_setting("telegram_bot_token", bot_token.strip())
    set_setting("telegram_chat_id", chat_id.strip())
    set_setting("telegram_enabled", "1" if enabled == "on" else "0")
    set_setting("telegram_on_schedule", "1" if on_schedule == "on" else "0")
    return RedirectResponse("/telegram?ok=1", status_code=303)


@app.post("/telegram/test")
async def telegram_test():
    latest = get_latest_report()
    if latest:
        ensure_report_chart(latest)
    text = latest["paragraph"] if latest else "تست OptionFlow — اتصال تلگرام برقرار است."
    if latest and latest.get("report_code") and report_has_chart(latest["report_code"]):
        path = data_dir() / "charts" / f"{latest['report_code']}.png"
        send_telegram_photo(path.read_bytes(), caption="BTCUSDT — مسیر سناریو")
    ok, msg = send_telegram_message(text)
    return RedirectResponse(
        f"/telegram?ok={'1' if ok else '0'}&msg={quote(msg)}",
        status_code=303,
    )


@app.post("/admin/run-now")
async def run_now():
    run_scheduled_report()
    return RedirectResponse("/", status_code=303)
