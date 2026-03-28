import asyncio
import logging

logger = logging.getLogger(__name__)

APPROVE_CB = "approve"
REJECT_CB = "reject"
AUTO_REJECT_HOURS = 4


class TelegramApprovalBot:
    """
    Sends video previews to the owner via Telegram for approve/reject.

    Security:
    - bot_token is sourced from environment only — never logged or committed.
    - owner_user_id is a hardcoded integer allowlist — all other IDs are silently ignored.
    - Auto-rejects after AUTO_REJECT_HOURS with a follow-up notification.
    """

    def __init__(self, bot_token: str, owner_user_id: int):
        """
        bot_token: Telegram bot token from .env (BotFather).
        owner_user_id: Hardcoded integer Telegram user ID.
                       All other user IDs receive no response.
        """
        from telegram.ext import Application

        self.bot_token = bot_token
        self.owner_user_id = owner_user_id
        self._app = Application.builder().token(bot_token).build()
        self._pending: dict[str, asyncio.Future] = {}  # message_id -> Future[str]
        self._handler_registered = False

    async def request_approval(
        self,
        video_path: str,
        caption: str,
        topic: str,
        timeout_seconds: int = AUTO_REJECT_HOURS * 3600,
    ) -> str:
        """
        Send video to owner and wait for approve/reject callback.
        Returns "approve" or "reject".
        Auto-rejects after timeout_seconds with a follow-up notification to owner.
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Approve", callback_data=APPROVE_CB),
                    InlineKeyboardButton("Reject", callback_data=REJECT_CB),
                ]
            ]
        )

        with open(video_path, "rb") as f:
            msg = await self._app.bot.send_video(
                chat_id=self.owner_user_id,
                video=f,
                caption=f"[Review] {topic}\n\n{caption}",
                reply_markup=keyboard,
                supports_streaming=True,
            )

        loop = asyncio.get_event_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending[str(msg.message_id)] = fut

        self._register_callback_handler()
        await self._app.start()

        try:
            result = await asyncio.wait_for(fut, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning(
                "No response from owner within %d hours — auto-rejecting topic: %s",
                AUTO_REJECT_HOURS,
                topic,
            )
            await self._app.bot.send_message(
                chat_id=self.owner_user_id,
                text=f"Auto-rejected (no response in {AUTO_REJECT_HOURS}h): {topic}",
            )
            result = REJECT_CB
        finally:
            self._pending.pop(str(msg.message_id), None)
            await self._app.stop()

        return result

    def _register_callback_handler(self) -> None:
        if not self._handler_registered:
            from telegram.ext import CallbackQueryHandler
            self._app.add_handler(CallbackQueryHandler(self._handle_callback))
            self._handler_registered = True

    async def _handle_callback(self, update, context) -> None:
        """
        Process inline button callbacks.
        Silently ignores any callback not from owner_user_id.
        """
        query = update.callback_query
        if query.from_user.id != self.owner_user_id:
            logger.warning(
                "Ignoring callback from unauthorized user ID: %d",
                query.from_user.id,
            )
            return

        await query.answer()
        msg_id = str(query.message.message_id)
        fut = self._pending.get(msg_id)
        if fut and not fut.done():
            action = APPROVE_CB if query.data == APPROVE_CB else REJECT_CB
            fut.set_result(action)

    async def send_alert(self, message: str) -> None:
        """Send a plain-text alert to the owner (pipeline errors, low-topic warnings)."""
        await self._app.bot.send_message(
            chat_id=self.owner_user_id, text=message
        )
