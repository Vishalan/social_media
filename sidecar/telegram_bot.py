"""
Telegram approval bot for the CommonCreed pipeline (Unit 6).

Implements the owner-facing approval loop:
- send_approval_preview: pushes thumbnail + 10s clip + headline + caption with
  inline buttons (Approve / Reject / Reschedule / Edit Caption).
- handle_approve / handle_reject / handle_reschedule / handle_reschedule_pick:
  callback handlers that update the approvals row and (lazily) trigger publish.
- handle_edit_caption + handle_caption_edit_reply: ForceReply edit-caption flow
  that merges the new caption back into pipeline_runs.captions_json.

Failure isolation: every handler catches its own exceptions and tries to send
an error message back to the user. The bot must NEVER crash on a bad payload,
DB hiccup, or missing publish job (Unit 7 wires that up later).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional

from . import config as config_module
from . import db as db_module

logger = logging.getLogger(__name__)


# Module-level pending dict for the Edit Caption ForceReply flow.
# Keyed by the prompt message_id we send (the message the user replies TO).
# Value: {"run_id": int, "chat_id": int}
edit_caption_pending: Dict[int, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _open_conn():
    s = config_module.settings_manager.settings
    if s is None:
        raise RuntimeError("settings not loaded")
    return db_module.connect(s.SIDECAR_DB_PATH)


def _build_inline_keyboard(run_id: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve ✓", callback_data=f"approve:{run_id}"),
                InlineKeyboardButton("Reject ✗", callback_data=f"reject:{run_id}"),
            ],
            [
                InlineKeyboardButton(
                    "Reschedule ⏰", callback_data=f"reschedule:{run_id}"
                ),
                InlineKeyboardButton(
                    "Edit Caption ✏", callback_data=f"edit_caption:{run_id}"
                ),
            ],
        ]
    )


def _next_six_slots(now: Optional[datetime] = None) -> list[datetime]:
    """Return today 19:00, tomorrow 09:00, 19:00, day-after 09:00, 19:00,
    day-after-day 09:00. Skips slots already in the past."""
    base = now or datetime.now()
    today = base.date()
    candidates = [
        datetime.combine(today, time(19, 0)),
        datetime.combine(today + timedelta(days=1), time(9, 0)),
        datetime.combine(today + timedelta(days=1), time(19, 0)),
        datetime.combine(today + timedelta(days=2), time(9, 0)),
        datetime.combine(today + timedelta(days=2), time(19, 0)),
        datetime.combine(today + timedelta(days=3), time(9, 0)),
    ]
    future = [c for c in candidates if c > base]
    # Top up if some slots are in the past — extend with later 09/19 slots.
    i = 4
    while len(future) < 6:
        d = today + timedelta(days=i)
        future.append(datetime.combine(d, time(9, 0)))
        if len(future) < 6:
            future.append(datetime.combine(d, time(19, 0)))
        i += 1
    return future[:6]


def _slot_keyboard(run_id: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for slot in _next_six_slots():
        label = slot.strftime("%a %m-%d %H:%M")
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"reschedule_pick:{run_id}:{slot.isoformat()}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def _extract_preview_clip(video_path: str, run_id: int) -> str:
    """Extract a 10-second preview MP4 to /tmp via ffmpeg.

    The caller is responsible for any cleanup; the file lives in /tmp and
    will be reaped by the OS. We use stream copy (``-c copy``) so the call is
    fast and CPU-light.
    """
    out_path = f"/tmp/preview_{run_id}.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        "0",
        "-t",
        "10",
        "-i",
        video_path,
        "-c",
        "copy",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


# ---------------------------------------------------------------------------
# send_approval_preview
# ---------------------------------------------------------------------------

async def send_approval_preview(app, pipeline_run_id: int) -> int:
    """Send the approval preview to the configured Telegram chat.

    Returns the message_id of the photo message (the "anchor" for the
    approval row). On any failure, raises — callers should be wrapped in
    their own try/except since this is invoked from the pipeline runner,
    not from a user interaction.
    """
    conn = _open_conn()
    try:
        run = db_module.get_pipeline_run(conn, pipeline_run_id)
    finally:
        conn.close()
    if run is None:
        raise ValueError(f"pipeline_run {pipeline_run_id} not found")

    captions_raw = run.get("captions_json") or "{}"
    try:
        captions = json.loads(captions_raw)
    except (TypeError, ValueError):
        captions = {}

    headline = run.get("topic_title") or "Untitled"
    ig = captions.get("instagram") or {}
    caption_text = ig.get("caption") or ""
    hashtags = ig.get("hashtags") or []
    hashtag_str = " ".join(hashtags) if hashtags else ""
    body = f"*{headline}*\n\n{caption_text}\n\n{hashtag_str}".strip()

    settings = config_module.settings_manager.settings
    chat_id = settings.TELEGRAM_CHAT_ID if settings else ""
    keyboard = _build_inline_keyboard(pipeline_run_id)

    # Send thumbnail (anchor message — its id is what we persist).
    thumb_path = run.get("thumbnail_path")
    bot = app.bot
    photo_msg = await bot.send_photo(
        chat_id=chat_id,
        photo=thumb_path,
        caption=body[:1024],
        reply_markup=keyboard,
    )
    message_id = int(getattr(photo_msg, "message_id", 0))

    # Try to attach a 10-second preview clip from the final video. Failure
    # here must NOT block the approval — log + continue.
    video_path = run.get("video_path")
    if video_path:
        try:
            clip_path = _extract_preview_clip(video_path, pipeline_run_id)
            await bot.send_video(chat_id=chat_id, video=clip_path)
        except Exception as exc:
            logger.warning("preview clip extraction failed: %s", exc)

    # Persist the approval row.
    conn = _open_conn()
    try:
        db_module.create_approval(conn, pipeline_run_id, message_id)
    finally:
        conn.close()

    return message_id


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------

def _parse_callback(data: str) -> tuple[str, list[str]]:
    parts = (data or "").split(":")
    return parts[0], parts[1:]


async def _safe_answer(query) -> None:
    try:
        await query.answer()
    except Exception:
        pass


async def _send_error(query, msg: str) -> None:
    try:
        await query.message.reply_text(f"⚠ {msg}")
    except Exception:
        logger.exception("failed to deliver error message to user")


async def handle_approve(update, context) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    query = update.callback_query
    await _safe_answer(query)
    try:
        _, args = _parse_callback(query.data)
        run_id = int(args[0])

        conn = _open_conn()
        try:
            row = db_module.get_approval_by_run_id(conn, run_id)
            if row is None:
                raise RuntimeError(f"no approval row for run {run_id}")
            db_module.update_approval_status(
                conn, row["id"], "approved", _now_iso()
            )
        finally:
            conn.close()

        stamp = datetime.now().strftime("%H:%M")
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"Approved at {stamp}", callback_data="noop")]]
        )
        try:
            await query.edit_message_reply_markup(reply_markup=kb)
        except Exception:
            pass

        # Lazily import the Unit 7 publish job — gracefully degrade if absent.
        try:
            from sidecar.jobs.publish import schedule_publish  # type: ignore

            schedule_publish(run_id)
        except ImportError:
            logger.warning("publish job not yet wired — Unit 7")
        except Exception as exc:
            logger.warning("schedule_publish failed: %s", exc)
    except Exception as exc:
        logger.exception("handle_approve failed")
        await _send_error(query, f"approve failed: {exc}")


async def handle_reject(update, context) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    query = update.callback_query
    await _safe_answer(query)
    try:
        _, args = _parse_callback(query.data)
        run_id = int(args[0])

        conn = _open_conn()
        try:
            row = db_module.get_approval_by_run_id(conn, run_id)
            if row is None:
                raise RuntimeError(f"no approval row for run {run_id}")
            db_module.update_approval_status(
                conn, row["id"], "rejected", _now_iso()
            )
        finally:
            conn.close()

        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Rejected", callback_data="noop")]]
        )
        try:
            await query.edit_message_reply_markup(reply_markup=kb)
        except Exception:
            pass
    except Exception as exc:
        logger.exception("handle_reject failed")
        await _send_error(query, f"reject failed: {exc}")


async def handle_reschedule(update, context) -> None:
    query = update.callback_query
    await _safe_answer(query)
    try:
        _, args = _parse_callback(query.data)
        run_id = int(args[0])
        kb = _slot_keyboard(run_id)
        await query.message.reply_text("Pick a new slot:", reply_markup=kb)
    except Exception as exc:
        logger.exception("handle_reschedule failed")
        await _send_error(query, f"reschedule failed: {exc}")


async def handle_reschedule_pick(update, context) -> None:
    query = update.callback_query
    await _safe_answer(query)
    try:
        _, args = _parse_callback(query.data)
        run_id = int(args[0])
        # iso timestamp may itself contain ":" — rejoin remaining parts.
        iso_ts = ":".join(args[1:])

        conn = _open_conn()
        try:
            row = db_module.get_approval_by_run_id(conn, run_id)
            if row is None:
                raise RuntimeError(f"no approval row for run {run_id}")
            db_module.update_approval_status(
                conn,
                row["id"],
                "rescheduled",
                _now_iso(),
                proposed_time=iso_ts,
            )
        finally:
            conn.close()

        await query.message.reply_text(f"Rescheduled to {iso_ts}")
    except Exception as exc:
        logger.exception("handle_reschedule_pick failed")
        await _send_error(query, f"reschedule_pick failed: {exc}")


async def handle_edit_caption(update, context) -> None:
    from telegram import ForceReply

    query = update.callback_query
    await _safe_answer(query)
    try:
        _, args = _parse_callback(query.data)
        run_id = int(args[0])
        prompt = await query.message.reply_text(
            "Reply to this message with the new caption.",
            reply_markup=ForceReply(selective=True),
        )
        prompt_id = int(getattr(prompt, "message_id", 0))
        chat_id = int(getattr(getattr(prompt, "chat", None), "id", 0) or 0)
        edit_caption_pending[prompt_id] = {"run_id": run_id, "chat_id": chat_id}
    except Exception as exc:
        logger.exception("handle_edit_caption failed")
        await _send_error(query, f"edit_caption failed: {exc}")


async def handle_caption_edit_reply(update, context) -> None:
    """Handles a user's reply to the ForceReply edit-caption prompt."""
    try:
        msg = update.message
        if msg is None or msg.reply_to_message is None:
            return
        replied_id = int(getattr(msg.reply_to_message, "message_id", 0))
        if replied_id not in edit_caption_pending:
            return  # not for us — ignore silently

        meta = edit_caption_pending.pop(replied_id)
        run_id = int(meta["run_id"])
        new_caption = (msg.text or "").strip()

        conn = _open_conn()
        try:
            run = db_module.get_pipeline_run(conn, run_id)
            captions = {}
            if run and run.get("captions_json"):
                try:
                    captions = json.loads(run["captions_json"])
                except (TypeError, ValueError):
                    captions = {}
            ig = captions.get("instagram") or {}
            ig["caption"] = new_caption
            captions["instagram"] = ig
            db_module.set_captions(conn, run_id, captions)
        finally:
            conn.close()

        await msg.reply_text(f"Caption updated:\n\n{new_caption}")
    except Exception as exc:
        logger.exception("handle_caption_edit_reply failed")
        try:
            await update.message.reply_text(f"⚠ caption update failed: {exc}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Application builder
# ---------------------------------------------------------------------------

def build_application(settings):
    """Build a python-telegram-bot Application with all handlers registered.

    Does NOT start polling — the caller (sidecar.app lifespan) is responsible
    for that. Importing python-telegram-bot is done inside the function so
    test environments can monkey-patch sys.modules first.
    """
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        MessageHandler,
        filters,
    )

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or ""
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is empty")

    app = Application.builder().token(token).build()

    app.add_handler(CallbackQueryHandler(handle_approve, pattern=r"^approve:"))
    app.add_handler(CallbackQueryHandler(handle_reject, pattern=r"^reject:"))
    app.add_handler(
        CallbackQueryHandler(handle_reschedule_pick, pattern=r"^reschedule_pick:")
    )
    app.add_handler(CallbackQueryHandler(handle_reschedule, pattern=r"^reschedule:"))
    app.add_handler(
        CallbackQueryHandler(handle_edit_caption, pattern=r"^edit_caption:")
    )
    app.add_handler(
        MessageHandler(filters.REPLY & ~filters.COMMAND, handle_caption_edit_reply)
    )

    return app
