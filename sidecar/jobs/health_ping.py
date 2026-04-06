"""
Health ping job (Unit 9).

Hourly ping of every external dependency. On failure, fires a Telegram
alert (rate-limited to 1/service/hour). Records last-success timestamps
in the ``settings`` table.

Never raises.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from .. import db as db_module
from ..config import settings_manager

logger = logging.getLogger(__name__)


# Rate-limit: service -> last alert datetime
_LAST_ALERT_AT: dict = {}
_ALERT_COOLDOWN = timedelta(hours=1)

SERVICES = ("postiz", "telegram", "gmail", "anthropic")


def _open_conn():
    s = settings_manager.settings
    if s is None:
        raise RuntimeError("settings not loaded")
    return db_module.connect(s.SIDECAR_DB_PATH)


def _now() -> datetime:
    return datetime.utcnow()


async def _alert(service: str, message: str, to_telegram: bool = True) -> None:
    """Fire an alert, rate-limited to 1/hour/service."""
    now = _now()
    last = _LAST_ALERT_AT.get(service)
    if last is not None and (now - last) < _ALERT_COOLDOWN:
        logger.info("health_ping: alert for %s suppressed (rate-limited)", service)
        return
    _LAST_ALERT_AT[service] = now
    if not to_telegram:
        logger.error("health_ping alert (no telegram): %s", message)
        return
    try:
        from sidecar.app import app as fastapi_app  # type: ignore

        bot_app = getattr(fastapi_app.state, "telegram_bot", None)
        s = settings_manager.settings
        chat_id = getattr(s, "TELEGRAM_CHAT_ID", "") if s else ""
        if bot_app is None or not chat_id:
            logger.error("health_ping alert (bot unavailable): %s", message)
            return
        await bot_app.bot.send_message(chat_id=chat_id, text=message)
    except Exception as exc:
        logger.warning("health_ping: telegram send failed: %s", exc)


def _record_success(service: str) -> None:
    try:
        conn = _open_conn()
        try:
            db_module.set_settings_value(
                conn,
                f"health_ping_last_success_{service}",
                _now().isoformat(timespec="seconds"),
            )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("health_ping: record_success(%s) failed: %s", service, exc)


def _last_success(service: str) -> str:
    try:
        conn = _open_conn()
        try:
            return db_module.get_settings_value(
                conn, f"health_ping_last_success_{service}", "never"
            )
        finally:
            conn.close()
    except Exception:
        return "unknown"


async def _ping_postiz() -> bool:
    try:
        import httpx

        s = settings_manager.settings
        base = getattr(s, "POSTIZ_BASE_URL", "") if s else ""
        key = getattr(s, "POSTIZ_API_KEY", "") if s else ""
        if not base:
            return False
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{base}/auth/me", headers=headers)
            return r.status_code == 200
    except Exception as exc:
        logger.warning("health_ping: postiz ping raised: %s", exc)
        return False


async def _ping_telegram() -> bool:
    try:
        from sidecar.app import app as fastapi_app  # type: ignore

        bot_app = getattr(fastapi_app.state, "telegram_bot", None)
        if bot_app is None:
            return False
        me = await bot_app.bot.get_me()
        return me is not None
    except Exception as exc:
        logger.warning("health_ping: telegram ping raised: %s", exc)
        return False


async def _ping_gmail() -> bool:
    try:
        from sidecar.gmail_client import GmailClient

        s = settings_manager.settings
        oauth_path = getattr(s, "GMAIL_OAUTH_PATH", "") if s else ""
        if not oauth_path:
            return False
        from pathlib import Path as _P

        if not _P(oauth_path).exists():
            return False
        oauth_json = _P(oauth_path).read_text()
        client = GmailClient(oauth_json)
        profile = client.get_profile()
        return profile is not None
    except Exception as exc:
        logger.warning("health_ping: gmail ping raised: %s", exc)
        return False


async def _ping_anthropic() -> bool:
    if os.environ.get("HEALTH_PING_ANTHROPIC", "") != "1":
        return True  # skipped, treat as success for reporting
    try:
        import httpx

        s = settings_manager.settings
        key = getattr(s, "ANTHROPIC_API_KEY", "") if s else ""
        if not key:
            return False
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": "claude-haiku-4-5",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "."}],
        }
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                "https://api.anthropic.com/v1/messages", json=body, headers=headers
            )
            return r.status_code < 500
    except Exception as exc:
        logger.warning("health_ping: anthropic ping raised: %s", exc)
        return False


async def run_health_pings() -> dict:
    """Ping every dependency. Never raises."""
    result: dict = {}
    try:
        # Postiz
        ok = await _ping_postiz()
        result["postiz"] = ok
        if ok:
            _record_success("postiz")
        else:
            await _alert(
                "postiz",
                f"service postiz unreachable (last_success: {_last_success('postiz')})",
                to_telegram=True,
            )

        # Telegram — cannot alert on Telegram via Telegram
        ok = await _ping_telegram()
        result["telegram"] = ok
        if ok:
            _record_success("telegram")
        else:
            await _alert(
                "telegram",
                f"service telegram unreachable (last_success: {_last_success('telegram')})",
                to_telegram=False,
            )

        # Gmail
        ok = await _ping_gmail()
        result["gmail"] = ok
        if ok:
            _record_success("gmail")
        else:
            await _alert(
                "gmail",
                f"service gmail unreachable (last_success: {_last_success('gmail')})",
                to_telegram=True,
            )

        # Anthropic (conditionally skipped)
        if os.environ.get("HEALTH_PING_ANTHROPIC", "") == "1":
            ok = await _ping_anthropic()
            result["anthropic"] = ok
            if ok:
                _record_success("anthropic")
            else:
                await _alert(
                    "anthropic",
                    f"service anthropic unreachable (last_success: {_last_success('anthropic')})",
                    to_telegram=True,
                )
        else:
            result["anthropic"] = "skipped"

        return result
    except Exception as exc:
        logger.error("health_ping: unexpected failure: %s", exc, exc_info=True)
        return {**result, "error": str(exc)}
