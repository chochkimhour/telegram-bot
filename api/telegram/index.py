import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler

from telegram import Update

from src.bot.main import build_application

logger = logging.getLogger(__name__)


async def _process_telegram_webhook(update_json: dict) -> None:
    application = build_application()
    update = Update.de_json(update_json, application.bot)

    # Ensure python-telegram-bot lifecycle is properly initialized for process_update().
    async with application:
        await application.process_update(update)


class handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Avoid noisy default HTTP logging in Vercel logs.
        return

    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send_json(200, {"ok": True, "service": "telegram-webhook"})

    def do_POST(self):
        try:
            content_length = self.headers.get("Content-Length")
            length = int(content_length) if content_length else 0
            raw = self.rfile.read(length) if length > 0 else b""

            if not raw:
                return self._send_json(400, {"ok": False, "error": "Empty body"})

            update_json = json.loads(raw.decode("utf-8"))

        except Exception as e:
            logger.exception("Failed to read/parse Telegram webhook body: %s", e)
            return self._send_json(400, {"ok": False, "error": "Invalid request body"})

        try:
            asyncio.run(_process_telegram_webhook(update_json))
            # Respond 200 so Telegram considers the update delivered.
            return self._send_json(200, {"ok": True})
        except Exception as e:
            logger.exception("Webhook processing failed: %s", e)
            # Returning 200 avoids Telegram retry storms; errors are logged for debugging.
            return self._send_json(200, {"ok": False, "error": str(e)})

