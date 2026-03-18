"""Telegram notification delivery with inline keyboard buttons."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
)

logger = logging.getLogger("trading_bot")


class TelegramNotifier:
    """Sends alert messages via Telegram bot with inline action buttons."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._app: Optional[Application] = None

    async def initialize(self):
        """Initialize the Telegram bot application."""
        if not self.bot_token or not self.chat_id:
            logger.warning(
                "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
            )
            return

        self._app = Application.builder().token(self.bot_token).build()
        self._app.add_handler(CallbackQueryHandler(self._button_callback))
        await self._app.initialize()
        await self._app.start()
        logger.info("Telegram bot initialized (chat_id: %s)", self.chat_id)

    async def send_alert(self, message: str, alert_id: str = "") -> bool:
        """Send an alert message with inline buttons.

        Args:
            message: Telegram Markdown formatted message
            alert_id: Unique ID for this alert (for callback tracking)

        Returns:
            True if sent successfully
        """
        if not self._app:
            logger.warning("Telegram bot not initialized, skipping send")
            return False

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("\u2705 Taken", callback_data=f"taken:{alert_id}"),
                InlineKeyboardButton("\u274c Skipped", callback_data=f"skipped:{alert_id}"),
                InlineKeyboardButton("\U0001f4ca Details", callback_data=f"details:{alert_id}"),
            ]
        ])

        for attempt in range(3):
            try:
                await self._app.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
                logger.info("Telegram alert sent: %s", alert_id or "no-id")
                return True
            except Exception as e:
                wait = 2 ** (attempt + 1)
                logger.error(
                    "Telegram send failed (attempt %d/3): %s. Retrying in %ds...",
                    attempt + 1, e, wait,
                )
                if attempt < 2:
                    await asyncio.sleep(wait)

        logger.error("Telegram send failed after 3 attempts for alert %s", alert_id)
        return False

    @staticmethod
    async def _button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard button presses."""
        query = update.callback_query
        if query is None:
            return

        await query.answer()
        data = query.data or ""
        parts = data.split(":", 1)
        action = parts[0] if parts else ""
        alert_id = parts[1] if len(parts) > 1 else ""

        if action == "taken":
            response = f"\u2705 Alert {alert_id} marked as TAKEN"
        elif action == "skipped":
            response = f"\u274c Alert {alert_id} marked as SKIPPED"
        elif action == "details":
            response = f"\U0001f4ca Detailed analysis for {alert_id} — feature coming soon"
        else:
            response = "Unknown action"

        logger.info("User response: %s for alert %s", action, alert_id)

        try:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(response)
        except Exception as e:
            logger.error("Button callback error: %s", e)

    async def send_test_message(self) -> bool:
        """Send a test message to verify configuration."""
        msg = (
            "\U0001f916 *Trading Alert Bot — Test Message*\n\n"
            "Your Telegram integration is working correctly!\n"
            "You will receive trading alerts in this chat."
        )
        return await self.send_alert(msg, alert_id="TEST")

    async def shutdown(self):
        """Shutdown the bot."""
        if self._app:
            try:
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:
                logger.error("Telegram shutdown error: %s", e)
            logger.info("Telegram bot shut down")
