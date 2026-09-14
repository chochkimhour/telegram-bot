import logging
import os
import base64
import asyncio

import httpx
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)
ENGLISH = "🇬🇧 English"
KHMER = "🇰🇭 Khmer"
BOTH = "🌐 Both"
TEXT_ONLY = "📝 Text"


def language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(ENGLISH), KeyboardButton(KHMER)],
            [KeyboardButton(BOTH), KeyboardButton(TEXT_ONLY)],
        ],
        resize_keyboard=True,
    )


async def translate_text(text: str, target: str = "both", image_data: bytes | None = None) -> str:
    try:
        logger.info("Translation requested: target=%s characters=%d", target, len(text))

        async def translate_to(language: str) -> str:
            api_key = os.getenv("GEMINI_API_KEY")
            model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is not configured")
            prompt = (
                (
                    "Extract only the readable text from the image. Do not translate, summarize, label, or explain. "
                    "Ignore QR codes, logos, stamps, signatures, decorative marks, and page numbers. "
                    "Preserve the original language, paragraph order, punctuation, and useful line breaks. "
                    "Return plain text only."
                    if language == "text"
                    else f"Translate the following text into {language}. Detect the source language automatically. "
                    "If an image is included, also read all visible text in the image. "
                    "Preserve meaning, names, numbers, emojis, and line breaks. Return only the translation."
                )
                + f"\n\nCaption or message text:\n{text or '(none; read the image)'}"
            )
            parts = [{"text": prompt}]
            if image_data:
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image_data).decode("ascii")}})
            payload = {
                "systemInstruction": {
                    "parts": [{"text": "You are a precise professional translator. Return only translated text."}]
                },
                "contents": [{"parts": parts}],
                "generationConfig": {"temperature": 0.1},
            }
            headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()

        if target == "text":
            extracted = await translate_to("text")
            logger.info("Image text extracted: characters=%d", len(extracted))
            return extracted
        if target == "en":
            return f"✨ Translation complete\n\n🇬🇧 English\n{await translate_to('en')}"
        if target == "km":
            return f"✨ Translation complete\n\n🇰🇭 Khmer\n{await translate_to('km')}"
        english, khmer = await asyncio.gather(
            translate_to("en"),
            translate_to("km"),
        )
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
    text = update.message.text or update.message.caption or ""
    image_data = None
    if update.message.photo:
        for attempt in range(2):
            try:
                photo_file = await update.message.photo[-1].get_file()
                image_data = bytes(await photo_file.download_as_bytearray())
                break
            except Exception:
                if attempt == 1:
                    raise
                logger.warning("Image download timed out; retrying")
    elif update.message.document and (update.message.document.mime_type or "").startswith("image/"):
        for attempt in range(2):
            try:
                image_file = await update.message.document.get_file()
                image_data = bytes(await image_file.download_as_bytearray())
                break
            except Exception:
                if attempt == 1:
                    raise
                logger.warning("Image file download timed out; retrying")
    if not text and not image_data:
        return
    if text in (ENGLISH, KHMER, BOTH, TEXT_ONLY):
        target = {ENGLISH: "en", KHMER: "km", BOTH: "both", TEXT_ONLY: "text"}[text]
        context.user_data["target"] = target
        logger.info("Translation option selected: target=%s", target)
        pending_text = context.user_data.pop("pending_text", "")
        pending_image = context.user_data.pop("pending_image", None)
        if pending_text or pending_image:
            if target == "text" and not pending_image:
                await update.message.reply_text(
                    "📝 The Text option works with an image. Please send or forward an image first.",
                    reply_markup=language_keyboard(),
                )
                return
            await update.message.chat.send_action(ChatAction.TYPING)
            await update.message.reply_text(
                await translate_text(pending_text, target, pending_image),
                reply_markup=language_keyboard(),
            )
            return
        await update.message.reply_text(
            f"✅ {text} selected.\n\nSend or forward text or an image, then choose a language button.",
            reply_markup=language_keyboard(),
        )
        return
    context.user_data["pending_text"] = text.strip()
    context.user_data["pending_image"] = image_data
    logger.info(
        "Content received for translation: characters=%d image=%s image_bytes=%d",
        len(text.strip()),
        bool(image_data),
        len(image_data) if image_data else 0,
    )
    await update.message.reply_text(
        "📩 Text received.\n\nPlease choose a language below to translate it:",
        reply_markup=language_keyboard(),
    )
