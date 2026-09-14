import logging
import os
import base64
import asyncio
import json

import httpx
import redis.asyncio as redis
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)
ENGLISH = "🇬🇧 English"
KHMER = "🇰🇭 Khmer"
BOTH = "🌐 Both"
TEXT_ONLY = "📝 Text"
IMAGE_SOURCE = "🖼 Image text"
MESSAGE_SOURCE = "💬 Message text"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
redis_client = redis.from_url(os.getenv("REDIS_URL")) if os.getenv("REDIS_URL") else None


async def save_pending(chat_id: int, text: str, image_data: bytes | None) -> None:
    if not redis_client:
        return
    data = {"text": text, "image": base64.b64encode(image_data).decode() if image_data else None}
    try:
        await asyncio.wait_for(
            redis_client.set(f"pending:{chat_id}", json.dumps(data), ex=600), timeout=5
        )
    except Exception as error:
        logger.warning("Redis save skipped: %s", error)


async def load_pending(chat_id: int) -> tuple[str, bytes | None]:
    if not redis_client:
        return "", None
    try:
        raw = await asyncio.wait_for(redis_client.get(f"pending:{chat_id}"), timeout=5)
        await asyncio.wait_for(redis_client.delete(f"pending:{chat_id}"), timeout=5)
    except Exception as error:
        logger.warning("Redis load skipped: %s", error)
        return "", None
    if not raw:
        return "", None
    data = json.loads(raw)
    return data.get("text", ""), base64.b64decode(data["image"]) if data.get("image") else None


async def delete_pending(chat_id: int) -> None:
    if not redis_client:
        return
    try:
        await asyncio.wait_for(redis_client.delete(f"pending:{chat_id}"), timeout=5)
    except Exception as error:
        logger.warning("Redis cleanup skipped: %s", error)


def language_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(ENGLISH), KeyboardButton(KHMER)],
            [KeyboardButton(BOTH), KeyboardButton(TEXT_ONLY)],
        ],
        resize_keyboard=True,
    )


def source_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(IMAGE_SOURCE), KeyboardButton(MESSAGE_SOURCE)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def translate_text(text: str, target: str = "both", image_data: bytes | None = None) -> str:
    try:
        logger.info(
            "Translation requested: target=%s caption_characters=%d image_bytes=%d",
            target,
            len(text),
            len(image_data) if image_data else 0,
        )

        async def translate_to(language: str) -> str:
            api_key = os.getenv("GEMINI_API_KEY")
            model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is not configured")
            prompt = (
                (
                    "Read the image as an OCR document. Extract only text that is visibly readable. "
                    "Read from the top of the page to the bottom. Within each row, read from left to right. "
                    "For multi-column layouts, finish the left column from top to bottom before the next column. "
                    "Keep headings, paragraphs, lists, dates, numbers, and meaningful line breaks in their visual order. "
                    "Do not guess unclear characters; omit unreadable fragments rather than inventing text. "
                    "Do not translate, summarize, label, or explain. Ignore QR codes, logos, stamps, signatures, "
                    "decorative marks, watermarks, and isolated page numbers. Return plain text only."
                    if language == "text"
                    else f"Translate the following text into {language}. Detect the source language automatically. "
                    "If an image is included, first read visible text from top to bottom and left to right; "
                    "for columns, finish the left column before the next column. "
                    "Preserve meaning, names, numbers, emojis, paragraph order, and useful line breaks. "
                    "Do not invent missing or unreadable content. Return only the translation."
                )
                + f"\n\nCaption or message text:\n{text or '(none; read the image)'}"
            )
            parts = [{"text": prompt}]
            if image_data:
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image_data).decode("ascii")}})
            payload = {
                "systemInstruction": {
                    "parts": [{
                        "text": (
                            "You are a precise document OCR and translation assistant. "
                            "Use only visible source content. Never hallucinate missing words. "
                            "Return only the requested plain text or translation, without commentary."
                        )
                    }]
                },
                "contents": [{"parts": parts}],
                "generationConfig": {"temperature": 0.1},
            }
            headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=30) as client:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                for attempt in range(3):
                    try:
                        response = await client.post(url, headers=headers, json=payload)
                        response.raise_for_status()
                        data = response.json()
                        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    except httpx.HTTPStatusError as error:
                        status = error.response.status_code
                        if status not in (429, 500, 503, 504) or attempt == 2:
                            raise
                        delay = 2 ** attempt
                        logger.warning("Gemini returned %s; retrying in %ss", status, delay)
                        await asyncio.sleep(delay)

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
        "Commands:\n"
        "/start - Start the translator\n"
        "/help - Show these instructions\n"
        "/reset - Clear stuck pending data\n"
        "/status - Check pending request",
        reply_markup=language_keyboard(),
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("pending_text", None)
    context.user_data.pop("pending_image", None)
    context.user_data.pop("pending_source", None)
    if redis_client:
        try:
            await asyncio.wait_for(
                redis_client.delete(f"pending:{update.effective_chat.id}"), timeout=5
            )
        except Exception as error:
            logger.warning("Redis clear skipped: %s", error)
    await update.message.reply_text(
        "🧹 Pending text and image data cleared.",
        reply_markup=language_keyboard(),
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending_text = context.user_data.get("pending_text", "")
    pending_image = context.user_data.get("pending_image")
    has_pending = bool(pending_text or pending_image)
    if not has_pending and redis_client:
        try:
            has_pending = bool(
                await asyncio.wait_for(
                    redis_client.exists(f"pending:{update.effective_chat.id}"), timeout=5
                )
            )
        except Exception as error:
            logger.warning("Redis status check skipped: %s", error)
    if has_pending:
        await update.message.reply_text(
            "✅ Bot is online and working.\n\n"
            "⏳ You have a pending request. Choose English, Khmer, Both, or Text to continue.\n\n"
            "Use /reset if it is stuck.",
            reply_markup=language_keyboard(),
        )
        return
    await update.message.reply_text(
        "✅ Bot is online and working.\n\n"
        "✅ No pending request. Send or forward text or an image to begin.",
        reply_markup=language_keyboard(),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = update.message.text or update.message.caption or ""
    image_data = None
    image_received = bool(
        update.message.photo
        or (
            update.message.document
            and (update.message.document.mime_type or "").startswith("image/")
        )
    )
    if image_received:
        # Acknowledge immediately so the user is not left waiting while Telegram
        # downloads the file and Gemini processes it.
        await update.message.reply_text(
            "📷 Image received. Preparing it now…\n\nChoose a button when processing is ready.",
            reply_markup=language_keyboard(),
        )
    try:
        if update.message.photo:
            for attempt in range(2):
                try:
                    photo_file = await update.message.photo[-1].get_file()
                    image_data = bytes(await photo_file.download_as_bytearray())
                    if len(image_data) > MAX_IMAGE_BYTES:
                        raise ValueError("image is too large")
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
                    if len(image_data) > MAX_IMAGE_BYTES:
                        raise ValueError("image is too large")
                    break
                except Exception:
                    if attempt == 1:
                        raise
                    logger.warning("Image file download timed out; retrying")
    except Exception:
        logger.exception("Could not download image")
        await update.message.reply_text(
            "⚠️ I could not read that image. Please send a smaller image or try again.",
            reply_markup=language_keyboard(),
        )
        return
    if not text and not image_data:
        return
    if text in (ENGLISH, KHMER, BOTH, TEXT_ONLY):
        target = {ENGLISH: "en", KHMER: "km", BOTH: "both", TEXT_ONLY: "text"}[text]
        context.user_data["target"] = target
        logger.info("Translation option selected: target=%s", target)
        pending_text = context.user_data.pop("pending_text", "")
        pending_image = context.user_data.pop("pending_image", None)
        pending_source = context.user_data.pop("pending_source", "both")
        if not pending_text and not pending_image:
            pending_text, pending_image = await load_pending(update.effective_chat.id)
        else:
            await delete_pending(update.effective_chat.id)
        if pending_source == "image":
            pending_text = ""
        elif pending_source == "message":
            pending_image = None
        if pending_text or pending_image:
            if target == "text" and not pending_image:
                await update.message.reply_text(
                    "📝 The Text option works with an image. Please send or forward an image first.",
                    reply_markup=language_keyboard(),
                )
                return
            await update.message.chat.send_action(ChatAction.TYPING)
            try:
                result = await asyncio.wait_for(
                    translate_text(pending_text, target, pending_image),
                    timeout=60,
                )
            except asyncio.TimeoutError:
                context.user_data.pop("pending_text", None)
                context.user_data.pop("pending_image", None)
                context.user_data.pop("pending_source", None)
                await delete_pending(update.effective_chat.id)
                logger.warning("Translation timed out and was removed: target=%s", target)
                await update.message.reply_text(
                    "⏱️ This request took too long and was removed. Please try again with a smaller image or shorter text.",
                    reply_markup=language_keyboard(),
                )
                return
            except Exception:
                context.user_data.pop("pending_text", None)
                context.user_data.pop("pending_image", None)
                context.user_data.pop("pending_source", None)
                await delete_pending(update.effective_chat.id)
                logger.exception("Translation failed and pending data was removed")
                await update.message.reply_text(
                    "⚠️ I could not process that request, so it was removed. Please try again with a smaller image or shorter text.",
                    reply_markup=language_keyboard(),
                )
                return
            await update.message.reply_text(result, reply_markup=language_keyboard())
            return
        await update.message.reply_text(
            f"✅ {text} selected.\n\nSend or forward text or an image, then choose a language button.",
            reply_markup=language_keyboard(),
        )
        return
    if text in (IMAGE_SOURCE, MESSAGE_SOURCE):
        context.user_data["pending_source"] = "image" if text == IMAGE_SOURCE else "message"
        await update.message.reply_text(
            f"✅ {text} selected.\n\nNow choose English, Khmer, or Both:",
            reply_markup=language_keyboard(),
        )
        return
    old_text = context.user_data.get("pending_text", "")
    old_image = context.user_data.get("pending_image")
    had_pending = bool(old_text or old_image)
    combined_text = "\n".join(part for part in (old_text, text.strip()) if part)
    combined_image = image_data or old_image
    context.user_data["pending_text"] = combined_text
    context.user_data["pending_image"] = combined_image
    await save_pending(update.effective_chat.id, combined_text, combined_image)
    logger.info(
        "Content received for translation: caption_characters=%d image=%s image_bytes=%d",
        len(combined_text),
        bool(combined_image),
        len(combined_image) if combined_image else 0,
    )
    if had_pending:
        return
    if combined_text and combined_image:
        await update.message.reply_text(
            "📦 This message contains an image and separate text.\n\nWhat should I process?",
            reply_markup=source_keyboard(),
        )
        return
    if image_received:
        # The immediate acknowledgement above is enough for image-only input.
        # Keep the keyboard visible without sending a duplicate "Text received" prompt.
        return
    await update.message.reply_text(
        "📩 Text received.\n\nPlease choose a language below to translate it:",
        reply_markup=language_keyboard(),
    )
