import logging
import os
import base64
import asyncio
import contextlib
import json
import time
import subprocess
import tempfile
from io import BytesIO

import httpx
import redis.asyncio as redis
from gtts import gTTS
from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)
ENGLISH = "🇬🇧 English"
KHMER = "🇰🇭 Khmer"
BOTH = "🌐 EN + KM"
TEXT_ONLY = "📝 Extract Text"
VOICE = "🔊 Text to Voice"
VOICE_TO_TEXT = "🎙️ Voice to Text"
IMAGE_SOURCE = "🖼 Image text"
MESSAGE_SOURCE = "💬 Message text"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
redis_client = redis.from_url(os.getenv("REDIS_URL")) if os.getenv("REDIS_URL") else None
active_tasks: dict[int, asyncio.Task] = {}


def clean_text(value: str) -> str:
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    fence = chr(96) * 3
    if value.startswith(fence) and value.endswith(fence):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1]).strip()
    cleaned_lines = []
    for line in value.splitlines():
        line = line.strip()
        if line and line not in (fence, fence + "text", fence + "plaintext"):
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def split_voice_text(value: str, limit: int = 900) -> list[str]:
    paragraphs = [part.strip() for part in value.split("\n") if part.strip()]
    chunks = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) <= limit and len(current) + len(paragraph) + 1 <= limit:
            current = f"{current}\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(paragraph) > limit:
            cut = paragraph.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        current = paragraph
    if current:
        chunks.append(current)
    return chunks or [value[:limit]]


def extract_document_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".txt") or name.endswith(".csv") or name.endswith(".tsv"):
        return clean_text(data.decode("utf-8-sig", errors="replace"))
    if name.endswith(".pdf"):
        reader = PdfReader(BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return clean_text("\n\n".join(pages))
    if name.endswith(".docx"):
        document = Document(BytesIO(data))
        parts = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return clean_text("\n".join(parts))
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
        rows = []
        for sheet in workbook.worksheets:
            rows.append(f"[{sheet.title}]")
            for row in sheet.iter_rows(values_only=True):
                values = [str(value).strip() for value in row if value is not None]
                if values:
                    rows.append(" | ".join(values))
        workbook.close()
        return clean_text("\n".join(rows))
    raise ValueError("unsupported document type")


async def save_pending(chat_id: int, text: str, image_data: bytes | None) -> None:
    if not redis_client:
        return
    data = {"text": text, "image": base64.b64encode(image_data).decode() if image_data else None}
    try:
        await asyncio.wait_for(
            redis_client.set(f"pending:{chat_id}", json.dumps(data), ex=600), timeout=5
        )
        logger.info(
            "Redis pending data saved: image=%s characters=%d expires_seconds=600",
            bool(image_data),
            len(text),
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
        logger.info("Redis pending data not found")
        return "", None
    data = json.loads(raw)
    pending_text = data.get("text", "")
    pending_image = base64.b64decode(data["image"]) if data.get("image") else None
    logger.info(
        "Redis pending data loaded: image=%s characters=%d",
        bool(pending_image),
        len(pending_text),
    )
    return pending_text, pending_image


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
            [KeyboardButton(BOTH), KeyboardButton(TEXT_ONLY)],
            [KeyboardButton(VOICE), KeyboardButton(VOICE_TO_TEXT)],
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
            model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is not configured")
            prompt = (
                (
                    "Read the image as an OCR document. Extract only text that is visibly readable. "
                    "Read from the top of the page to the bottom. Within each row, read from left to right. "
                    "For multi-column layouts, finish the left column from top to bottom before the next column. "
                    "Keep headings, paragraphs, lists, dates, numbers, and meaningful line breaks in their visual order. "
                    "Do not guess unclear characters; omit unreadable fragments rather than inventing text. "
                    "Copy personal names, place names, organization names, phone numbers, IDs, email addresses, URLs, "
                    "dates, and amounts exactly as visible. Do not normalize, translate, or transliterate proper names. "
                    "Do not translate, summarize, label, or explain. Ignore QR codes, logos, stamps, signatures, "
                    "decorative marks, watermarks, and isolated page numbers. Return plain text only."
                    if language == "text"
                    else f"Translate the following text into {language}. Detect the source language automatically. "
                    "If an image is included, first read visible text from top to bottom and left to right; "
                    "for columns, finish the left column before the next column. "
                    "Preserve meaning, names, numbers, emojis, paragraph order, and useful line breaks. "
                    "Keep personal names, place names, organization names, IDs, phone numbers, email addresses, URLs, "
                    "dates, and amounts exactly as provided when they are readable. Do not translate or transliterate "
                    "proper names unless the source explicitly provides a standard translated name. "
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
                            "Treat names and other proper nouns as protected text: preserve their spelling exactly "
                            "whenever readable. "
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
                        logger.info(
                            "Gemini request started: target=%s attempt=%d",
                            language,
                            attempt + 1,
                        )
                        response = await client.post(url, headers=headers, json=payload)
                        response.raise_for_status()
                        data = response.json()
                        result = clean_text(data["candidates"][0]["content"]["parts"][0]["text"])
                        logger.info(
                            "Gemini request succeeded: target=%s characters=%d",
                            language,
                            len(result),
                        )
                        return result
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
            return f"🇬🇧 English\n\n{await translate_to('en')}"
        if target == "km":
            return f"🇰🇭 Khmer\n\n{await translate_to('km')}"
        english, khmer = await asyncio.gather(
            translate_to("en"),
            translate_to("km"),
        )
        return (
            f"🇬🇧 English\n\n{english}\n\n"
            f"🇰🇭 Khmer\n\n{khmer}"
        )
    except Exception:
        logger.exception("Translation request failed")
        return "Sorry, I could not translate that right now. Please try again."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Welcome to Translate!\n\n"
        "Send or forward text, or upload an image, then choose an option:\n\n"
        "🌐 EN + KM — translate into both languages\n"
        "📝 Extract Text — read clean text from an image or document\n"
        "🔊 Text to Voice — turn text into audio\n"
        "🎙️ Voice to Text — convert speech into copyable text\n\n"
        "Choose a button below to get started.",
        reply_markup=language_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send or forward text or an image, then choose a button below.\n\n"
        "Commands:\n"
        "/start - Start the translator\n"
        "/help - Show these instructions\n"
        "/reset - Clear stuck pending data\n"
        "/status - Check pending request",
        reply_markup=language_keyboard(),
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    active_task = active_tasks.get(chat_id)
    if active_task and not active_task.done():
        active_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await active_task
        logger.info("Active request cancelled by user: chat_id=%s", chat_id)
    context.user_data.pop("pending_text", None)
    context.user_data.pop("pending_image", None)
    context.user_data.pop("pending_source", None)
    if redis_client:
        try:
            await asyncio.wait_for(
                redis_client.delete(f"pending:{chat_id}"), timeout=5
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
                "⏳ You have a pending request. Choose a button below to continue.\n\n"
            "Use /reset if it is stuck.",
            reply_markup=language_keyboard(),
        )
        return
    await update.message.reply_text(
        "✅ Bot is online and working.\n\n"
        "✅ No pending request. Send or forward text or an image to begin.",
        reply_markup=language_keyboard(),
    )


async def send_voice(text: str, language: str = "en") -> BytesIO:
    started = time.perf_counter()
    logger.info(
        "Voice generation requested: language=%s characters=%d",
        language,
        len(text),
    )
    audio = BytesIO()
    audio.name = "translation.mp3"
    speech_language = "km" if language == "km" else "en"
    try:
        await asyncio.to_thread(
            gTTS(text=text, lang=speech_language, slow=False).write_to_fp,
            audio,
        )
    except Exception:
        logger.exception(
            "Voice provider request failed: language=%s characters=%d",
            speech_language,
            len(text),
        )
        raise
    audio.seek(0)
    logger.info(
        "Voice generated successfully: language=%s bytes=%d duration_ms=%d",
        speech_language,
        audio.getbuffer().nbytes,
        int((time.perf_counter() - started) * 1000),
    )
    return audio


async def convert_to_telegram_voice(audio: BytesIO) -> BytesIO:
    def convert() -> BytesIO:
        import imageio_ffmpeg

        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "source.mp3")
            target = os.path.join(folder, "voice.ogg")
            with open(source, "wb") as stream:
                stream.write(audio.getvalue())
            subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-y",
                    "-i",
                    source,
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "48k",
                    "-vn",
                    target,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            with open(target, "rb") as stream:
                result = BytesIO(stream.read())
            result.name = "voice.ogg"
            return result

    return await asyncio.to_thread(convert)


async def transcribe_audio(audio_data: bytes, mime_type: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    payload = {
        "systemInstruction": {
            "parts": [{"text": "Transcribe only the spoken words. Detect the language automatically. Return plain text only."}]
        },
        "contents": [{"parts": [
            {"text": "Transcribe this audio accurately. Preserve names, numbers, and the original language."},
            {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio_data).decode("ascii")}},
        ]}],
        "generationConfig": {"temperature": 0.0},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(3):
            try:
                logger.info("Voice transcription request started: attempt=%d", attempt + 1)
                response = await client.post(
                    url,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                result = clean_text(response.json()["candidates"][0]["content"]["parts"][0]["text"])
                logger.info("Voice transcription succeeded: characters=%d", len(result))
                return result
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                if status not in (429, 500, 503, 504) or attempt == 2:
                    raise
                delay = 2 ** attempt
                logger.warning(
                    "Gemini voice transcription returned %s; retrying in %ss",
                    status,
                    delay,
                )
                await asyncio.sleep(delay)
    raise RuntimeError("voice transcription failed after retries")


async def download_image(message) -> bytes:
    media = message.photo[-1] if message.photo else message.document
    for attempt in range(2):
        try:
            media_file = await media.get_file()
            image_data = bytes(await media_file.download_as_bytearray())
            if len(image_data) > MAX_IMAGE_BYTES:
                raise ValueError("image is too large")
            logger.info("Image downloaded: bytes=%d attempt=%d", len(image_data), attempt + 1)
            return image_data
        except Exception:
            if attempt == 1:
                raise
            logger.warning("Image download failed; retrying once")
    raise RuntimeError("image download failed")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = clean_text(update.message.text or update.message.caption or "")
    image_data = None
    document_received = bool(update.message.document and not image_received)
    image_received = bool(
        update.message.photo
        or (
            update.message.document
            and (update.message.document.mime_type or "").startswith("image/")
        )
    )
    if image_received:
        logger.info(
            "Image update received: photo=%s document=%s caption_characters=%d",
            bool(update.message.photo),
            bool(update.message.document),
            len(text),
        )
        try:
            # Acknowledge immediately, but do not stop image processing if this
            # Telegram response temporarily fails.
            await asyncio.wait_for(
                update.message.reply_text(
                    "📷 Image received. Preparing it now…\n\nChoose a button when processing is ready.",
                    reply_markup=language_keyboard(),
                ),
                timeout=10,
            )
        except Exception:
            logger.exception("Could not send image acknowledgement; continuing")
    try:
        if image_received:
            image_data = await asyncio.wait_for(
                download_image(update.message),
                timeout=25,
            )
    except asyncio.TimeoutError:
        logger.error("Image download timed out after 25 seconds")
        await delete_pending(update.effective_chat.id)
        await update.message.reply_text(
            "⏱️ Image processing took too long and was removed. Please send a smaller image.",
            reply_markup=language_keyboard(),
        )
        return
    except Exception:
        logger.exception("Could not download image")
        await delete_pending(update.effective_chat.id)
        await update.message.reply_text(
            "⚠️ I could not read that image. Please send a smaller image or try again.",
            reply_markup=language_keyboard(),
        )
        return
    if document_received:
        filename = update.message.document.file_name or ""
        logger.info("Document update received: filename=%s", filename or "(unnamed)")
        try:
            if update.message.document.file_size and update.message.document.file_size > MAX_DOCUMENT_BYTES:
                raise ValueError("document is too large")
            document_file = await asyncio.wait_for(
                update.message.document.get_file(),
                timeout=15,
            )
            document_data = bytes(
                await asyncio.wait_for(
                    document_file.download_as_bytearray(),
                    timeout=25,
                )
            )
            text = await asyncio.wait_for(
                asyncio.to_thread(extract_document_text, filename, document_data),
                timeout=25,
            )
            if not text:
                await update.message.reply_text(
                    "⚠️ I could not find readable text in that file.",
                    reply_markup=language_keyboard(),
                )
                return
            logger.info(
                "Document text extracted: filename=%s characters=%d",
                filename or "(unnamed)",
                len(text),
            )
        except asyncio.TimeoutError:
            logger.error("Document processing timed out: filename=%s", filename or "(unnamed)")
            await update.message.reply_text(
                "⏱️ That file took too long to read and was removed. Please send a smaller file.",
                reply_markup=language_keyboard(),
            )
            return
        except ValueError as error:
            logger.warning("Document rejected: filename=%s reason=%s", filename or "(unnamed)", error)
            await update.message.reply_text(
                "⚠️ This file is too large or unsupported. Send TXT, PDF, DOCX, XLSX, or XLSM files up to 10 MB.",
                reply_markup=language_keyboard(),
            )
            return
        except Exception:
            logger.exception("Could not read document: filename=%s", filename or "(unnamed)")
            await update.message.reply_text(
                "⚠️ I could not read that file. Please send a TXT, PDF, DOCX, XLSX, or XLSM file.",
                reply_markup=language_keyboard(),
            )
            return
    if update.message.voice or update.message.audio:
        if context.user_data.get("mode") != "voice_to_text":
            await update.message.reply_text(
                "🎙️ Select Voice to Text first, then send a voice message or audio file.",
                reply_markup=language_keyboard(),
            )
            return
        context.user_data.pop("mode", None)
        media = update.message.voice or update.message.audio
        try:
            audio_file = await asyncio.wait_for(media.get_file(), timeout=15)
            audio_data = bytes(
                await asyncio.wait_for(audio_file.download_as_bytearray(), timeout=25)
            )
            mime_type = (
                "audio/ogg"
                if update.message.voice
                else (media.mime_type or "audio/mpeg")
            )
            await update.message.chat.send_action(ChatAction.TYPING)
            result = await asyncio.wait_for(
                transcribe_audio(audio_data, mime_type),
                timeout=45,
            )
            await update.message.reply_text(
                result or "⚠️ No speech was detected.",
                reply_markup=language_keyboard(),
            )
        except asyncio.TimeoutError:
            logger.warning("Voice transcription timed out")
            await update.message.reply_text(
                "⏱️ Voice transcription took too long. Please send a shorter recording.",
                reply_markup=language_keyboard(),
            )
        except Exception:
            logger.exception("Voice transcription failed")
            await update.message.reply_text(
                "⚠️ I could not convert that voice message to text. Please try again.",
                reply_markup=language_keyboard(),
            )
        return
    if text == VOICE_TO_TEXT:
        context.user_data["mode"] = "voice_to_text"
        await update.message.reply_text(
            "🎙️ Voice to Text selected.\n\nNow send a voice message or audio file.",
            reply_markup=language_keyboard(),
        )
        return
    if not text and not image_data:
        return
    if text == VOICE:
        pending_text = context.user_data.pop("pending_text", "")
        context.user_data.pop("pending_image", None)
        context.user_data.pop("pending_source", None)
        if not pending_text:
            pending_text, _ = await load_pending(update.effective_chat.id)
        else:
            await delete_pending(update.effective_chat.id)
        if not pending_text:
            await update.message.reply_text(
                "🔊 Send or forward text first, then press Voice.",
                reply_markup=language_keyboard(),
            )
            return
        language = context.user_data.get("target", "en")
        if language not in ("en", "km"):
            language = "km" if any("\u1780" <= char <= "\u17ff" for char in pending_text) else "en"
        try:
            await update.message.chat.send_action(ChatAction.UPLOAD_VOICE)
            voice_chunks = split_voice_text(pending_text)
            logger.info(
                "Voice generation split into chunks: chunks=%d characters=%d",
                len(voice_chunks),
                len(pending_text),
            )
            for chunk in voice_chunks:
                audio = await asyncio.wait_for(send_voice(chunk, language), timeout=45)
                try:
                    voice = await asyncio.wait_for(
                        convert_to_telegram_voice(audio),
                        timeout=35,
                    )
                    await update.message.reply_voice(
                        voice=voice,
                        reply_markup=language_keyboard(),
                    )
                except Exception:
                    logger.exception("OGG/Opus voice conversion failed")
                    await update.message.reply_text(
                        "⚠️ I could not create a Telegram voice message. Please try shorter text.",
                        reply_markup=language_keyboard(),
                    )
        except asyncio.TimeoutError:
            logger.warning(
                "Voice generation timed out: language=%s characters=%d",
                language,
                len(pending_text),
            )
            await update.message.reply_text(
                "⏱️ Voice generation took too long and was stopped. Please try shorter text.",
                reply_markup=language_keyboard(),
            )
        except Exception:
            logger.exception("Voice generation failed")
            await update.message.reply_text(
                "⚠️ I could not create the voice message. Please try again with shorter text.",
                reply_markup=language_keyboard(),
            )
        return
    if text in (BOTH, TEXT_ONLY):
        target = {BOTH: "both", TEXT_ONLY: "text"}[text]
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
            chat_id = update.effective_chat.id
            translation_task = asyncio.create_task(
                translate_text(pending_text, target, pending_image)
            )
            active_tasks[chat_id] = translation_task
            try:
                result = await asyncio.wait_for(translation_task, timeout=60)
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
            except asyncio.CancelledError:
                logger.info("Translation cancelled: chat_id=%s", chat_id)
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
            finally:
                if active_tasks.get(chat_id) is translation_task:
                    active_tasks.pop(chat_id, None)
            await update.message.reply_text(result, reply_markup=language_keyboard())
            return
        await update.message.reply_text(
            f"✅ {text} selected.\n\nSend or forward text or an image, then choose a button below.",
            reply_markup=language_keyboard(),
        )
        return
    if text in (IMAGE_SOURCE, MESSAGE_SOURCE):
        context.user_data["pending_source"] = "image" if text == IMAGE_SOURCE else "message"
        await update.message.reply_text(
            f"✅ {text} selected.\n\nNow choose EN + KM:",
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
        "📩 Text received.\n\nPlease choose an option below:",
        reply_markup=language_keyboard(),
    )
