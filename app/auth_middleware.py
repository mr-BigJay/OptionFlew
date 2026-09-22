from __future__ import annotations

import os
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth_store import get_user

SESSION_USER_KEY = "user_id"
SESSION_ADMIN_PANEL_KEY = "admin_panel"


def is_enrich_deployment() -> bool:
    return os.environ.get("OPTIONFLOW_ENRICHED", "0").strip() == "1"


def deployment_channel_label() -> str:
    return "enrich" if is_enrich_deployment() else "stable"


def channel_allowed(user: dict) -> bool:
    if user.get("is_admin"):
        return True
    if is_enrich_deployment():
        return bool(user.get("allow_enrich"))
    return bool(user.get("allow_stable"))


def current_user(request: Request) -> dict | None:
    uid = request.session.get(SESSION_USER_KEY)
    if not uid:
        return None
    return get_user(int(uid))


def login_session(request: Request, user: dict, *, admin_panel: bool) -> None:
    request.session[SESSION_USER_KEY] = user["id"]
    request.session[SESSION_ADMIN_PANEL_KEY] = 1 if admin_panel else 0


def logout_session(request: Request) -> None:
    request.session.clear()


def _is_public(path: str) -> bool:
    if path.startswith("/static"):
        return True
    return path in (
        "/login",
        "/bigjay_controller/login",
    )


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if _is_public(path):
            return await call_next(request)

        user = current_user(request)
        admin_panel = bool(request.session.get(SESSION_ADMIN_PANEL_KEY))

        if path.startswith("/bigjay_controller"):
            if path in ("/bigjay_controller/login",):
                return await call_next(request)
            if not user or not user.get("is_admin"):
                return RedirectResponse("/bigjay_controller/login", status_code=303)
            return await call_next(request)

        if not user:
            return RedirectResponse(f"/login?next={quote(path)}", status_code=303)

        if not channel_allowed(user):
            logout_session(request)
            return RedirectResponse("/login?err=channel", status_code=303)

        if user.get("must_change_password") and path not in (
            "/change-password",
            "/logout",
        ):
            return RedirectResponse("/change-password", status_code=303)

        if not user.get("is_admin"):
            if (
                path.startswith("/backtest")
                or path.startswith("/scalp/backtest")
                or path == "/admin/run-now"
            ):
                return RedirectResponse("/", status_code=303)

        return await call_next(request)
