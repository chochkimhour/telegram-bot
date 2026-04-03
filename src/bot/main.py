import os
import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from src.bot.handlers import start, handle_message, show, reset, profile, clear, setup

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://your-domain.com
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(
    format='[%(levelname)s] %(asctime)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Suppress noisy HTTP library logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log all errors from the dispatcher."""
    logger.error("Exception while handling an update:", exc_info=context.error)


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .updater(None)          # Disable the built-in Updater — we drive updates manually
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setup", setup))
    app.add_handler(CommandHandler("show", show))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    return app


# ── Build the PTB application at module level so FastAPI can reference it ──
ptb_app = build_application()
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Register webhook on startup, remove it on shutdown."""
    await ptb_app.initialize()
    await ptb_app.start()

    if WEBHOOK_URL:
        full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}{WEBHOOK_PATH}"
        await ptb_app.bot.set_webhook(
            url=full_webhook_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        logger.info(f"Webhook registered at: {full_webhook_url}")
    else:
        logger.warning(
            "WEBHOOK_URL is not set in .env — webhook NOT registered with Telegram. "
            "Set WEBHOOK_URL to your public HTTPS URL."
        )

    yield  # ── server is running ──

    logger.info("Shutting down — removing webhook...")
    await ptb_app.bot.delete_webhook()
    await ptb_app.stop()
    await ptb_app.shutdown()


# ── FastAPI app ────────────────────────────────────────────────────────────
web = FastAPI(lifespan=lifespan)


@web.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Receive an update from Telegram and pass it to python-telegram-bot."""
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(content="ok", status_code=200)


@web.get("/health")
async def health():
    """Simple health-check endpoint for Docker / reverse-proxy."""
    return {"status": "healthy"}


def run():
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN provided!")
        return

    logger.info(f"Starting webhook server on 0.0.0.0:{PORT} ...")
    uvicorn.run(
        "src.bot.main:web",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=False,
    )
