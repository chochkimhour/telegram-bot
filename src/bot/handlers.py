import logging
import os
from urllib.parse import quote

import httpx
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)
ENGLISH = "🇬🇧 English"
KHMER = "🇰🇭 Khmer"
BOTH = "🌐 Both"


def language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(ENGLISH), KeyboardButton(KHMER), KeyboardButton(BOTH)]],
        resize_keyboard=True,
    )


async def translate_text(text: str, target: str = "both") -> str:
    try:
        logger.info("Translation requested: target=%s characters=%d", target, len(text))

        async def translate_to(language: str) -> str:
            configured_url = os.getenv("LINGVA_URL", "https://lingva.ml").rstrip("/")
            instances = [
                configured_url,
                "https://translate.igna.wtf",
                "https://lingva.lunar.icu",
                "https://translate.plausibility.cloud",
            ]
            async with httpx.AsyncClient(timeout=30) as client:
                last_error = "Translation failed"
                for base_url in dict.fromkeys(instances):
                    try:
                        response = await client.get(
                            f"{base_url}/api/v1/auto/{language}/{quote(text, safe='')}"
                        )
                        response.raise_for_status()
                        data = response.json()
                        if "translation" in data:
                            logger.info("Lingva instance used: %s", base_url)
                            return data["translation"]
                        last_error = data.get("error", last_error)
                    except Exception as error:
                        last_error = str(error)
                        logger.warning("Lingva instance unavailable: %s", base_url)
                try:
                    response = await client.get(
                        "https://translate.googleapis.com/translate_a/single",
                        params={
                            "client": "gtx",
                            "sl": "auto",
                            "tl": language,
                            "dt": "t",
                            "q": text,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    translation = "".join(part[0] for part in data[0] if part[0])
                    if translation:
                        logger.info("Direct Google Translate fallback used")
                        return translation
                except Exception as error:
                    last_error = str(error)
                raise RuntimeError(last_error)

        if target == "en":
            return f"✨ Translation complete\n\n🇬🇧 English\n{await translate_to('en')}"
        if target == "km":
            return f"✨ Translation complete\n\n🇰🇭 Khmer\n{await translate_to('km')}"
        english = await translate_to("en")
        khmer = await translate_to("km")
        return (
            "✨ Translation complete\n\n"
            f"🇬🇧 English\n{english}\n\n"
            f"🇰🇭 Khmer\n{khmer}"
        )
    except Exception:
        logger.exception("Translation request failed")
        return "Sorry, I could not translate that right now. Please try again."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hello! Send or forward any text, then choose English, Khmer, or Both.",
        reply_markup=language_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send any text to receive both English and Khmer translations.\n\n"
        "Choose English, Khmer, or Both before sending text.\n\n"
        "Commands:\n/start - Start the bot\n/help - Show this help message",
        reply_markup=language_keyboard(),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = update.message.text or update.message.caption
    if not text:
        return
    if text in (ENGLISH, KHMER, BOTH):
        target = {ENGLISH: "en", KHMER: "km", BOTH: "both"}[text]
        context.user_data["target"] = target
        logger.info("Translation option selected: target=%s", target)
        pending_text = context.user_data.pop("pending_text", None)
        if pending_text:
            await update.message.chat.send_action(ChatAction.TYPING)
            await update.message.reply_text(
                await translate_text(pending_text, target),
                reply_markup=language_keyboard(),
            )
            return
        await update.message.reply_text(
            f"✅ {text} selected.\n\nSend or forward your text, then choose a language button.",
            reply_markup=language_keyboard(),
        )
        return
    context.user_data["pending_text"] = text.strip()
    logger.info("Text received for translation: characters=%d", len(text.strip()))
    await update.message.reply_text(
        "📩 Text received.\n\nPlease choose a language below to translate it:",
        reply_markup=language_keyboard(),
    )
