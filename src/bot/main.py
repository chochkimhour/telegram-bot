import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import asyncio
from src.bot.handlers import start, handle_message, show, reset, profile, clear, setup

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format='[%(levelname)s] %(asctime)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Suppress HTTP libraries tracking every single request (like long polling)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

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
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    # Increase connection timeouts to prevent httpx.ConnectTimeout
    app = Application.builder().token(BOT_TOKEN).connect_timeout(30.0).read_timeout(30.0).build()

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
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN provided!")
        return

    app = build_application()

    logger.info("Starting dummy HTTP server for Render health checks...")
    threading.Thread(target=run_dummy_server, daemon=True).start()

    logger.info("Starting bot...")
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    # Add a poll_interval to give the CPU a rest between the requests
    # and reduce 100% CPU spikes common on free cloud tiers.
    app.run_polling(drop_pending_updates=False, poll_interval=2.0)
