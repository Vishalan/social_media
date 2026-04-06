"""
Sidecar dashboard auth: signed cookie sessions.

Design notes:
- Single owner (no user table). Password lives in the same .env the dashboard
  edits, read via ``settings_manager``. Username field on the form is purely
  cosmetic — only the password matters.
- Cookies are signed with ``itsdangerous.TimestampSigner`` so we never trust
  client-side state. The session payload is just the literal string ``"admin"``
  joined with a timestamp by the signer; we treat any successfully unsigned
  value within the max-age window as authenticated.
- Session secret is generated once on first use and persisted next to the
  sidecar SQLite DB at ``<SIDECAR_DB_PATH parent>/session.key``. This survives
  container restarts but is local to the host volume — rotating it just
  invalidates outstanding cookies, which is fine.
- Failure isolation: if the secret file can't be written (read-only FS in
  tests), we fall back to an in-memory secret so the app still boots.
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from .config import settings_manager


logger = logging.getLogger("sidecar.auth")

COOKIE_NAME = "sidecar_session"
COOKIE_MAX_AGE = 60 * 60 * 24  # 24 hours

_SIGNER: Optional[TimestampSigner] = None


def _session_key_path() -> Path:
    s = settings_manager.settings
    if s is not None:
        return Path(s.SIDECAR_DB_PATH).parent / "session.key"
    return Path("/tmp/sidecar_session.key")


def _load_or_create_secret() -> str:
    path = _session_key_path()
    try:
        if path.exists():
            text = path.read_text().strip()
            if text:
                return text
    except OSError:
        pass
    secret = secrets.token_urlsafe(48)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secret)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        logger.warning("session.key not persisted (%s); using in-memory secret", exc)
    return secret


def get_signer() -> TimestampSigner:
    global _SIGNER
    if _SIGNER is None:
        _SIGNER = TimestampSigner(_load_or_create_secret(), salt="sidecar-session")
    return _SIGNER


def reset_signer_for_tests() -> None:
    """Test helper: forget the cached signer so a new key path is picked up."""
    global _SIGNER
    _SIGNER = None


def make_session_token() -> str:
    return get_signer().sign(b"admin").decode("utf-8")


def verify_session_token(token: str) -> bool:
    try:
        get_signer().unsign(token, max_age=COOKIE_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False
    except Exception:
        return False


def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    return verify_session_token(token)


def require_auth(request: Request):
    """FastAPI dependency: redirect to /login if the cookie is missing/bad."""
    if is_authenticated(request):
        return True
    raise _RedirectToLogin()


class _RedirectToLogin(Exception):
    pass


# --- Login/logout router --------------------------------------------------
router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return _templates.TemplateResponse(
        "login.html", {"request": request, "error": None}
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(default="admin"),
    password: str = Form(...),
):
    s = settings_manager.settings
    expected = s.SIDECAR_ADMIN_PASSWORD if s is not None else None
    if not expected or password != expected:
        # Return 401 with the login page rendered, so tests can assert status.
        body = _templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid credentials"},
            status_code=401,
        )
        return body
    token = make_session_token()
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        COOKIE_NAME, token,
        max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax",
    )
    return resp


@router.post("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


@router.get("/logout")
def logout_get():
    return logout()


def install_redirect_handler(app) -> None:
    from fastapi import FastAPI  # noqa

    @app.exception_handler(_RedirectToLogin)
    async def _redirect_handler(request: Request, exc: _RedirectToLogin):  # noqa
        return RedirectResponse(url="/login", status_code=303)
