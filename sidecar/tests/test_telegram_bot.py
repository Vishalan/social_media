"""
Unit 6 — telegram_bot tests.

We mock the python-telegram-bot SDK at the call sites so the tests pass even
on hosts where it isn't installed. The bot module imports `telegram` and
`telegram.ext` symbols lazily inside functions, so monkeypatching
`sidecar.telegram_bot.<symbol>` works without touching sys.modules.

External boundaries mocked:
- ffmpeg subprocess (`subprocess.run`)
- DB (real in-memory sqlite where useful, MagicMock where DB errors are tested)
- Telegram bot/Application (AsyncMock everywhere)
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Stub the `telegram` package so the module imports cleanly even without
# python-telegram-bot installed. We register minimal classes that record
# their construction args.
# ---------------------------------------------------------------------------

def _install_fake_telegram_modules() -> None:
    if "telegram" in sys.modules and getattr(
        sys.modules["telegram"], "_sidecar_fake", False
    ):
        return

    telegram_mod = types.ModuleType("telegram")
    telegram_mod._sidecar_fake = True  # type: ignore[attr-defined]

    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None, **kw):
            self.text = text
            self.callback_data = callback_data

    class InlineKeyboardMarkup:
        def __init__(self, rows):
            self.inline_keyboard = rows

    class ForceReply:
        def __init__(self, selective=False):
            self.selective = selective

    telegram_mod.InlineKeyboardButton = InlineKeyboardButton
    telegram_mod.InlineKeyboardMarkup = InlineKeyboardMarkup
    telegram_mod.ForceReply = ForceReply

    ext_mod = types.ModuleType("telegram.ext")

    class Application:
        @classmethod
        def builder(cls):
            return ApplicationBuilder()

    class ApplicationBuilder:
        def token(self, t):
            self._token = t
            return self

        def build(self):
            inst = MagicMock()
            inst.handlers_added = []
            inst.add_handler = lambda h: inst.handlers_added.append(h)
            inst._token = self._token
            return inst

    class CallbackQueryHandler:
        def __init__(self, callback, pattern=None, **kw):
            self.callback = callback
            self.pattern = pattern
            self.kind = "callback_query"

    class MessageHandler:
        def __init__(self, filt, callback, **kw):
            self.filt = filt
            self.callback = callback
            self.kind = "message"

    class _Filter:
        def __and__(self, other):
            return self

        def __invert__(self):
            return self

    class _Filters:
        REPLY = _Filter()
        COMMAND = _Filter()

    ext_mod.Application = Application
    ext_mod.ApplicationBuilder = ApplicationBuilder
    ext_mod.CallbackQueryHandler = CallbackQueryHandler
    ext_mod.MessageHandler = MessageHandler
    ext_mod.filters = _Filters()

    sys.modules["telegram"] = telegram_mod
    sys.modules["telegram.ext"] = ext_mod


_install_fake_telegram_modules()

from sidecar import db as db_module  # noqa: E402
from sidecar import telegram_bot as tb  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    p = str(tmp_path / "sidecar.sqlite3")
    db_module.init_db(p)
    return p


@pytest.fixture
def patched_settings(db_path, monkeypatch):
    fake = types.SimpleNamespace(
        SIDECAR_DB_PATH=db_path,
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_CHAT_ID="12345",
    )
    monkeypatch.setattr(tb.config_module.settings_manager, "_settings", fake, raising=False)
    # Ensure .settings property returns our fake
    monkeypatch.setattr(
        type(tb.config_module.settings_manager),
        "settings",
        property(lambda self: fake),
    )
    return fake


@pytest.fixture
def seeded_run(db_path, patched_settings, tmp_path):
    conn = db_module.connect(db_path)
    try:
        run_id = db_module.insert_pipeline_run(
            conn,
            topic_title="Test Headline",
            topic_url="https://example.com",
            topic_score=0.9,
            selection_rationale="why",
            source_newsletter_date="2026-04-06",
            status="awaiting_approval",
        )
        thumb = tmp_path / "thumb.png"
        thumb.write_bytes(b"\x89PNG\r\n")
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fakevideo")
        db_module.update_pipeline_run_generation_result(
            conn,
            run_id,
            status="awaiting_approval",
            video_path=str(video),
            thumbnail_path=str(thumb),
            audio_path=None,
            cost_sonnet=0.0,
            cost_haiku=0.0,
            cost_elevenlabs=0.0,
            cost_veed=0.0,
            error_log=None,
            started_at=None,
            finished_at=None,
        )
        captions = {
            "instagram": {
                "caption": "Original caption",
                "hashtags": ["#ai", "#news"],
            },
            "youtube": {
                "title": "yt title",
                "description": "yt desc",
                "hashtags": ["#shorts"],
            },
        }
        db_module.set_captions(conn, run_id, captions)
    finally:
        conn.close()
    return run_id


# ---------------------------------------------------------------------------
# build_application
# ---------------------------------------------------------------------------

def test_build_application_registers_all_handlers():
    settings = types.SimpleNamespace(TELEGRAM_BOT_TOKEN="test-token")
    app = tb.build_application(settings)
    handlers = app.handlers_added
    # 5 callback handlers + 1 message handler = 6
    assert len(handlers) == 6
    cb_handlers = [h for h in handlers if h.kind == "callback_query"]
    msg_handlers = [h for h in handlers if h.kind == "message"]
    assert len(cb_handlers) == 5
    assert len(msg_handlers) == 1
    patterns = {h.pattern for h in cb_handlers}
    assert r"^approve:" in patterns
    assert r"^reject:" in patterns
    assert r"^reschedule:" in patterns
    assert r"^reschedule_pick:" in patterns
    assert r"^edit_caption:" in patterns


# ---------------------------------------------------------------------------
# send_approval_preview
# ---------------------------------------------------------------------------

def _make_app_with_bot():
    bot = MagicMock()
    bot.send_photo = AsyncMock(return_value=MagicMock(message_id=999))
    bot.send_video = AsyncMock(return_value=MagicMock(message_id=1000))
    app = MagicMock()
    app.bot = bot
    return app, bot


def test_send_approval_preview_writes_approval_row(seeded_run, db_path, patched_settings, monkeypatch):
    app, bot = _make_app_with_bot()
    monkeypatch.setattr(tb.subprocess, "run", MagicMock())

    msg_id = asyncio.get_event_loop().run_until_complete(
        tb.send_approval_preview(app, seeded_run)
    )
    assert msg_id == 999
    bot.send_photo.assert_awaited_once()

    conn = db_module.connect(db_path)
    try:
        row = db_module.get_approval_by_run_id(conn, seeded_run)
    finally:
        conn.close()
    assert row is not None
    assert row["status"] == "pending"
    assert row["pipeline_run_id"] == seeded_run
    assert row["telegram_message_id"] == 999


def test_send_approval_preview_builds_correct_inline_keyboard(seeded_run, patched_settings, monkeypatch):
    app, bot = _make_app_with_bot()
    monkeypatch.setattr(tb.subprocess, "run", MagicMock())

    asyncio.get_event_loop().run_until_complete(
        tb.send_approval_preview(app, seeded_run)
    )
    kwargs = bot.send_photo.call_args.kwargs
    kb = kwargs["reply_markup"]
    flat = [b for row in kb.inline_keyboard for b in row]
    assert len(flat) == 4
    cb = {b.callback_data for b in flat}
    assert f"approve:{seeded_run}" in cb
    assert f"reject:{seeded_run}" in cb
    assert f"reschedule:{seeded_run}" in cb
    assert f"edit_caption:{seeded_run}" in cb


# ---------------------------------------------------------------------------
# Callback handler helpers
# ---------------------------------------------------------------------------

def _make_callback_update(data: str):
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message = MagicMock()
    query.message.reply_text = AsyncMock(
        return_value=MagicMock(message_id=555, chat=MagicMock(id=12345))
    )
    update = MagicMock()
    update.callback_query = query
    return update, query


def _seed_approval(db_path, run_id):
    conn = db_module.connect(db_path)
    try:
        return db_module.create_approval(conn, run_id, telegram_message_id=999)
    finally:
        conn.close()


def test_handle_approve_updates_status(seeded_run, db_path, patched_settings):
    _seed_approval(db_path, seeded_run)
    update, query = _make_callback_update(f"approve:{seeded_run}")

    asyncio.get_event_loop().run_until_complete(tb.handle_approve(update, None))

    conn = db_module.connect(db_path)
    try:
        row = db_module.get_approval_by_run_id(conn, seeded_run)
    finally:
        conn.close()
    assert row["status"] == "approved"
    assert row["owner_action_at"] is not None


def test_handle_reject_updates_status(seeded_run, db_path, patched_settings):
    _seed_approval(db_path, seeded_run)
    update, query = _make_callback_update(f"reject:{seeded_run}")

    asyncio.get_event_loop().run_until_complete(tb.handle_reject(update, None))

    conn = db_module.connect(db_path)
    try:
        row = db_module.get_approval_by_run_id(conn, seeded_run)
    finally:
        conn.close()
    assert row["status"] == "rejected"


def test_handle_reschedule_shows_slot_picker(seeded_run, patched_settings):
    update, query = _make_callback_update(f"reschedule:{seeded_run}")

    asyncio.get_event_loop().run_until_complete(tb.handle_reschedule(update, None))

    query.message.reply_text.assert_awaited_once()
    kb = query.message.reply_text.call_args.kwargs["reply_markup"]
    flat = [b for row in kb.inline_keyboard for b in row]
    assert len(flat) == 6
    for b in flat:
        assert b.callback_data.startswith(f"reschedule_pick:{seeded_run}:")


def test_handle_reschedule_pick_updates_proposed_time(seeded_run, db_path, patched_settings):
    _seed_approval(db_path, seeded_run)
    iso = "2026-04-07T19:00:00"
    update, query = _make_callback_update(f"reschedule_pick:{seeded_run}:{iso}")

    asyncio.get_event_loop().run_until_complete(
        tb.handle_reschedule_pick(update, None)
    )

    conn = db_module.connect(db_path)
    try:
        row = db_module.get_approval_by_run_id(conn, seeded_run)
    finally:
        conn.close()
    assert row["proposed_time"] == iso
    assert row["status"] == "rescheduled"


def test_handle_edit_caption_sends_force_reply(seeded_run, patched_settings):
    tb.edit_caption_pending.clear()
    update, query = _make_callback_update(f"edit_caption:{seeded_run}")

    asyncio.get_event_loop().run_until_complete(
        tb.handle_edit_caption(update, None)
    )

    query.message.reply_text.assert_awaited_once()
    kwargs = query.message.reply_text.call_args.kwargs
    assert "reply_markup" in kwargs
    # Pending dict should have one entry for the prompt message id (555)
    assert 555 in tb.edit_caption_pending
    assert tb.edit_caption_pending[555]["run_id"] == seeded_run


def test_handle_caption_edit_reply_updates_captions_json(seeded_run, db_path, patched_settings):
    tb.edit_caption_pending.clear()
    tb.edit_caption_pending[777] = {"run_id": seeded_run, "chat_id": 12345}

    msg = MagicMock()
    msg.text = "Brand new caption"
    msg.reply_to_message = MagicMock(message_id=777)
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.message = msg

    asyncio.get_event_loop().run_until_complete(
        tb.handle_caption_edit_reply(update, None)
    )

    conn = db_module.connect(db_path)
    try:
        run = db_module.get_pipeline_run(conn, seeded_run)
    finally:
        conn.close()
    captions = json.loads(run["captions_json"])
    assert captions["instagram"]["caption"] == "Brand new caption"
    # hashtags untouched
    assert captions["instagram"]["hashtags"] == ["#ai", "#news"]
    # popped
    assert 777 not in tb.edit_caption_pending


def test_handle_caption_edit_reply_ignored_if_not_in_pending_dict(seeded_run, db_path, patched_settings):
    tb.edit_caption_pending.clear()

    msg = MagicMock()
    msg.text = "Should be ignored"
    msg.reply_to_message = MagicMock(message_id=99999)
    msg.reply_text = AsyncMock()
    update = MagicMock()
    update.message = msg

    asyncio.get_event_loop().run_until_complete(
        tb.handle_caption_edit_reply(update, None)
    )

    conn = db_module.connect(db_path)
    try:
        run = db_module.get_pipeline_run(conn, seeded_run)
    finally:
        conn.close()
    captions = json.loads(run["captions_json"])
    assert captions["instagram"]["caption"] == "Original caption"
    msg.reply_text.assert_not_awaited()


def test_approve_handler_never_crashes_on_db_error(seeded_run, patched_settings, monkeypatch):
    update, query = _make_callback_update(f"approve:{seeded_run}")

    def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(tb.db_module, "get_approval_by_run_id", boom)

    # Must NOT raise.
    asyncio.get_event_loop().run_until_complete(tb.handle_approve(update, None))
    # Error message reported to user via reply_text
    query.message.reply_text.assert_awaited()


def test_approve_handler_gracefully_skips_publish_when_unit_7_not_wired(
    seeded_run, db_path, patched_settings
):
    _seed_approval(db_path, seeded_run)
    update, query = _make_callback_update(f"approve:{seeded_run}")

    # Force the lazy `from sidecar.jobs.publish import schedule_publish` to
    # raise ImportError. We block the submodule via a real import hook.
    sys.modules.pop("sidecar.jobs.publish", None)

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sidecar.jobs.publish":
            raise ImportError("publish job not wired")
        return real_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=fake_import):
        asyncio.get_event_loop().run_until_complete(tb.handle_approve(update, None))

    # Approval still recorded as approved
    conn = db_module.connect(db_path)
    try:
        row = db_module.get_approval_by_run_id(conn, seeded_run)
    finally:
        conn.close()
    assert row["status"] == "approved"
