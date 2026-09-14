import logging
import os
import asyncio

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from src.bot.handlers import handle_message, help_command, start

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "9999"))
PUBLIC_URL = os.getenv("WEBHOOK_URL")
if not PUBLIC_URL and os.getenv("VERCEL_URL"):
    PUBLIC_URL = f"https://{os.getenv('VERCEL_URL')}"

logging.basicConfig(format="[%(levelname)s] %(asctime)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Telegram update failed", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Something went wrong while processing that message. "
                "Please try sending it again.",
            )
        except Exception:
            logger.exception("Could not send error response")


async def configure_bot_profile(application: Application) -> None:
    await application.bot.set_my_short_description(
        "Translate any language into English, Khmer, or both."
    )
    await application.bot.set_my_description(
        "Send or forward any text to this bot. Choose English, Khmer, or Both, "
        "and the bot will translate your text."
    )
    logger.info("Bot profile configured")


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(configure_bot_profile)
        .connect_timeout(30)
        .read_timeout(90)
        .write_timeout(90)
        .pool_timeout(30)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    message_filters = (filters.TEXT | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND
    application.add_handler(MessageHandler(message_filters, handle_message))
    application.add_error_handler(error_handler)
    return application


telegram_app = build_application()
WEBHOOK_PREFIX = "/api" if os.getenv("VERCEL") else ""
WEBHOOK_PATH = f"{WEBHOOK_PREFIX}/webhook/{BOT_TOKEN}"
web = FastAPI()


@web.on_event("startup")
async def startup() -> None:
    await telegram_app.initialize()
    await telegram_app.start()
    if PUBLIC_URL:
        await telegram_app.bot.set_webhook(
            url=f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}",
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        logger.info("Telegram webhook registered with public URL")


@web.on_event("shutdown")
async def shutdown() -> None:
    await telegram_app.bot.delete_webhook()
    await telegram_app.stop()
    await telegram_app.shutdown()


@web.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> Response:
    update = Update.de_json(await request.json(), telegram_app.bot)
    await telegram_app.process_update(update)
    return Response(content="ok")


@web.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def run() -> None:
    if PUBLIC_URL:
        logger.info("Starting webhook server on port %s", PORT)
        uvicorn.run("src.bot.main:web", host="0.0.0.0", port=PORT, log_level="info")
    else:
        logger.info("Starting local polling mode")
        asyncio.set_event_loop(asyncio.new_event_loop())
        telegram_app.run_polling(drop_pending_updates=True)
