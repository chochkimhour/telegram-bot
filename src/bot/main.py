import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import asyncio
from src.bot.handlers import start, handle_message, show, reset, profile, clear, setup

load_dotenv()
TOKEN = os.getenv("TOKEN")

logging.basicConfig(
    format='[%(levelname)s] %(asctime)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot is running successfully on Render!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

def build_application() -> Application:
    if not TOKEN:
        raise RuntimeError("TOKEN environment variable is required")

    app = Application.builder().token(TOKEN).build()

    # Telegram handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setup", setup))
    app.add_handler(CommandHandler("show", show))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app

def run():
    if not TOKEN:
        logger.error("No TOKEN provided!")
        return

    app = build_application()

    logger.info("Starting dummy HTTP server for Render health checks...")
    threading.Thread(target=run_dummy_server, daemon=True).start()

    logger.info("Starting bot...")
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    # Don't drop pending updates on startup so Telegram messages aren't lost
    # during container restarts.
    app.run_polling(drop_pending_updates=False)
