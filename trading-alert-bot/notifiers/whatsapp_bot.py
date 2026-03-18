"""WhatsApp notification delivery via Twilio."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("trading_bot")


class WhatsAppNotifier:
    """Sends alert messages via Twilio WhatsApp API."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        to_number: str,
    ):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.to_number = to_number
        self._client = None

    async def initialize(self):
        """Initialize the Twilio client."""
        if not all([self.account_sid, self.auth_token, self.from_number, self.to_number]):
            logger.warning(
                "WhatsApp not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
                "TWILIO_WHATSAPP_FROM, and TWILIO_WHATSAPP_TO in .env"
            )
            return

        try:
            from twilio.rest import Client
            self._client = Client(self.account_sid, self.auth_token)
            logger.info("WhatsApp (Twilio) client initialized")
        except ImportError:
            logger.error("twilio package not installed. Run: pip install twilio")
        except Exception as e:
            logger.error("Twilio initialization failed: %s", e)

    async def send_alert(self, message: str, alert_id: str = "") -> bool:
        """Send a WhatsApp message.

        Args:
            message: Plain text message (no Markdown)
            alert_id: Unique alert identifier for logging

        Returns:
            True if sent successfully
        """
        if not self._client:
            logger.warning("WhatsApp client not initialized, skipping send")
            return False

        for attempt in range(3):
            try:
                msg = await asyncio.to_thread(
                    self._client.messages.create,
                    body=message,
                    from_=self.from_number,
                    to=self.to_number,
                )
                logger.info(
                    "WhatsApp alert sent: %s (SID: %s)",
                    alert_id or "no-id", msg.sid,
                )
                return True
            except Exception as e:
                wait = 2 ** (attempt + 1)
                logger.error(
                    "WhatsApp send failed (attempt %d/3): %s. Retrying in %ds...",
                    attempt + 1, e, wait,
                )
                if attempt < 2:
                    await asyncio.sleep(wait)

        logger.error("WhatsApp send failed after 3 attempts for alert %s", alert_id)
        return False

    async def send_test_message(self) -> bool:
        """Send a test message to verify configuration."""
        msg = (
            "Trading Alert Bot -- Test Message\n\n"
            "Your WhatsApp integration is working correctly!\n"
            "You will receive trading alerts on this number."
        )
        return await self.send_alert(msg, alert_id="TEST")

    async def shutdown(self):
        """Cleanup."""
        self._client = None
        logger.info("WhatsApp notifier shut down")
