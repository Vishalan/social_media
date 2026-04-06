"""
Weekly cost summary job (Unit 9).

Every Monday at 09:00 local time, aggregates the last 7 days of cost_*
columns across pipeline_runs, formats a message, and sends to Telegram.

Never raises.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from .. import db as db_module
from ..config import settings_manager

logger = logging.getLogger(__name__)


def _open_conn():
    s = settings_manager.settings
    if s is None:
        raise RuntimeError("settings not loaded")
    return db_module.connect(s.SIDECAR_DB_PATH)


async def _send_telegram(text: str) -> None:
    try:
        from sidecar.app import app as fastapi_app  # type: ignore

        bot_app = getattr(fastapi_app.state, "telegram_bot", None)
        if bot_app is None:
            logger.info("cost_report telegram (no bot): %s", text)
            return
        s = settings_manager.settings
        chat_id = getattr(s, "TELEGRAM_CHAT_ID", "") if s else ""
        if not chat_id:
            return
        await bot_app.bot.send_message(chat_id=chat_id, text=text)
    except Exception as exc:
        logger.warning("cost_report: telegram send failed: %s", exc)


def _format_report(
    start_date: str, end_date: str, runs: list, days_with_posts: int
) -> tuple:
    total_sonnet = sum(float(r.get("cost_sonnet") or 0) for r in runs)
    total_haiku = sum(float(r.get("cost_haiku") or 0) for r in runs)
    total_elevenlabs = sum(float(r.get("cost_elevenlabs") or 0) for r in runs)
    total_veed = sum(float(r.get("cost_veed") or 0) for r in runs)
    total = total_sonnet + total_haiku + total_elevenlabs + total_veed
    projected_monthly = total * (30.0 / 7.0) if total > 0 else 0.0
    videos = len(runs)

    msg = (
        f"📊 Weekly cost report ({start_date} to {end_date})\n"
        f"Videos posted: {videos} / {days_with_posts} days\n"
        f"Total cost: ${total:.2f}\n"
        f"Projected monthly: ${projected_monthly:.0f}/month\n"
        f"Breakdown:\n"
        f"  Sonnet: ${total_sonnet:.2f}\n"
        f"  Haiku: ${total_haiku:.2f}\n"
        f"  ElevenLabs: ${total_elevenlabs:.2f}\n"
        f"  VEED: ${total_veed:.2f}"
    )
    return msg, {
        "total": total,
        "projected_monthly": projected_monthly,
        "sonnet": total_sonnet,
        "haiku": total_haiku,
        "elevenlabs": total_elevenlabs,
        "veed": total_veed,
        "videos": videos,
    }


async def send_weekly_cost_report() -> dict:
    """Sum last 7 days of costs, format, send to Telegram."""
    try:
        now = datetime.utcnow()
        start = (now - timedelta(days=7)).date().isoformat()
        end = now.date().isoformat()

        try:
            conn = _open_conn()
        except Exception as exc:
            logger.warning("cost_report: open db failed: %s", exc)
            return {"ok": False, "error": str(exc)}

        try:
            runs = db_module.get_runs_for_cost_report(conn, start, end)
        except Exception as exc:
            logger.warning("cost_report: query failed: %s", exc)
            try:
                conn.close()
            except Exception:
                pass
            return {"ok": False, "error": str(exc)}
        finally:
            try:
                conn.close()
            except Exception:
                pass

        days_with_posts = len({(r.get("created_at") or "")[:10] for r in runs if r.get("created_at")}) or 7
        msg, summary = _format_report(start, end, runs, days_with_posts)
        await _send_telegram(msg)
        return {"ok": True, "message": msg, "summary": summary}
    except Exception as exc:
        logger.error("cost_report: unexpected failure: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}
