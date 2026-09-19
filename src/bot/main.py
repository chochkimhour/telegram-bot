import logging
import os
import asyncio

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from telegram import BotCommand, Update
from telegram.error import RetryAfter
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from src.bot.handlers import clear_command, handle_message, help_command, start, status_command

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "telegram-webhook")
if (os.getenv("VERCEL") or os.getenv("WEBHOOK_URL")) and not os.getenv("WEBHOOK_SECRET"):
    raise RuntimeError("WEBHOOK_SECRET environment variable is required on Vercel")
PORT = int(os.getenv("PORT", "9999"))
PUBLIC_URL = os.getenv("WEBHOOK_URL")
if not PUBLIC_URL:
    vercel_domain = (
        os.getenv("VERCEL_PROJECT_PRODUCTION_URL")
        or os.getenv("VERCEL_URL")
        or os.getenv("VERCEL_BRANCH_URL")
    )
    if vercel_domain:
        PUBLIC_URL = (
            vercel_domain
            if vercel_domain.startswith("http")
            else f"https://{vercel_domain}"
        )

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
                "មានបញ្ហាក្នុងការដំណើរការសារ។ "
                "សូមព្យាយាមផ្ញើម្តងទៀត។",
            )
        except Exception:
            logger.exception("Could not send error response")


async def configure_bot_profile(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "ចាប់ផ្តើមកម្មវិធីបកប្រែ"),
            BotCommand("help", "បង្ហាញការណែនាំ"),
            BotCommand("reset", "លុបទិន្នន័យដែលកំពុងរង់ចាំ"),
            BotCommand("status", "ពិនិត្យសំណើដែលកំពុងរង់ចាំ"),
        ]
    )
    await application.bot.set_my_short_description(
        "បកប្រែអត្ថបទ អានរូបភាព និងបង្កើតសារសំឡេងជាភាសាអង់គ្លេស ឬខ្មែរ។"
    )
    await application.bot.set_my_description(
        "សូមផ្ញើ ឬបញ្ជូនបន្តអត្ថបទជាភាសាណាមួយ ហើយជ្រើសរើស អង់គ្លេស + ខ្មែរ។\n\n"
        "សូមផ្ញើរូបភាព ឬឯកសារ ហើយជ្រើសរើស ទាញយកអត្ថបទ។\n\n"
        "សូមផ្ញើ ឬបញ្ចូលអត្ថបទ ហើយជ្រើសរើស អត្ថបទទៅជាសំឡេង។\n\n"
        "សូមជ្រើសរើស សំឡេងទៅជាអត្ថបទ មុនពេលផ្ញើសារសំឡេង។\n\n"
        "ប្រើ /status ដើម្បីពិនិត្យបូត និង /reset ដើម្បីលុបសំណើដែលជាប់គាំង។"
    )
    logger.info("Bot profile configured")


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(configure_bot_profile)
        .concurrent_updates(True)
        .connect_timeout(30)
        .read_timeout(90)
        .write_timeout(90)
        .pool_timeout(30)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", clear_command))
    application.add_handler(CommandHandler("status", status_command))
    message_filters = (
        filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL
    ) & ~filters.COMMAND
    application.add_handler(MessageHandler(message_filters, handle_message))
    application.add_error_handler(error_handler)
    return application


telegram_app = build_application()
IS_VERCEL = bool(os.getenv("VERCEL") or PUBLIC_URL)
WEBHOOK_PREFIX = "/api" if IS_VERCEL else ""
WEBHOOK_PATH = f"{WEBHOOK_PREFIX}/webhook/{WEBHOOK_SECRET}"
web = FastAPI()


@web.on_event("startup")
async def startup() -> None:
    await telegram_app.initialize()
    await configure_bot_profile(telegram_app)
    await telegram_app.start()
    if PUBLIC_URL:
        webhook_url = f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}"
        try:
            current_webhook = await telegram_app.bot.get_webhook_info()
            if current_webhook.url == webhook_url:
                logger.info("Telegram webhook already registered")
                return
        except Exception:
            logger.warning("Could not inspect current Telegram webhook; continuing")
        for attempt in range(3):
            try:
                await telegram_app.bot.set_webhook(
                    url=webhook_url,
                    secret_token=WEBHOOK_SECRET,
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                )
                logger.info("Telegram webhook registered with public URL")
                break
            except RetryAfter as error:
                if attempt == 2:
                    raise
                delay = max(int(error.retry_after), 1)
                logger.warning("Telegram webhook rate limited; retrying in %ss", delay)
                await asyncio.sleep(delay)


@web.on_event("shutdown")
async def shutdown() -> None:
    # Vercel recycles serverless instances frequently. Never delete the
    # production webhook during a normal serverless shutdown.
    if not IS_VERCEL:
        await telegram_app.bot.delete_webhook()
    await telegram_app.stop()
    await telegram_app.shutdown()


async def process_webhook(request: Request) -> Response:
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        logger.warning("Rejected webhook request: invalid secret")
        return Response(content="forbidden", status_code=403)
    try:
        payload = await request.json()
        update = Update.de_json(payload, telegram_app.bot)
        update_type = "unknown"
        if update.message:
            update_type = "message"
        elif update.callback_query:
            update_type = "callback_query"
        logger.info(
            "Webhook update received: type=%s update_id=%s",
            update_type,
            update.update_id,
        )
        await asyncio.wait_for(telegram_app.process_update(update), timeout=55)
        logger.info("Webhook update completed: update_id=%s", update.update_id)
    except asyncio.TimeoutError:
        logger.error("Webhook update timed out after 55 seconds")
    except Exception:
        logger.exception("Webhook update processing failed")
    # Always acknowledge Telegram so it does not retry the same stuck update.
    return Response(content="ok")


@web.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> Response:
    return await process_webhook(request)


@web.post("/api")
async def telegram_vercel_rewrite(request: Request) -> Response:
    return await process_webhook(request)


@web.post("/{path:path}")
async def telegram_vercel_fallback(path: str, request: Request) -> Response:
    return await process_webhook(request)


@web.get("/health")
async def health() -> dict[str, str]:
    if IS_VERCEL and PUBLIC_URL:
        webhook_url = f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}"
        try:
            webhook_info = await telegram_app.bot.get_webhook_info()
            if webhook_info.url != webhook_url:
                await telegram_app.bot.set_webhook(
                    url=webhook_url,
                    secret_token=WEBHOOK_SECRET,
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=False,
                )
                logger.info("Webhook repaired automatically from health check")
        except Exception:
            logger.exception("Automatic webhook repair failed")
    return {"status": "ok"}


@web.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "Telegram English-Khmer Translator"}


def run() -> None:
    if PUBLIC_URL:
        logger.info("Starting webhook server on port %s", PORT)
        uvicorn.run("src.bot.main:web", host="0.0.0.0", port=PORT, log_level="info")
    else:
        logger.info("Starting local polling mode")
        asyncio.set_event_loop(asyncio.new_event_loop())
        telegram_app.run_polling(drop_pending_updates=True)
