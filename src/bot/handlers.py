import logging
import os
import base64
import asyncio
import contextlib
import json
import time
import subprocess
import tempfile
import wave
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
ENGLISH = "English"
KHMER = "Khmer"
BOTH = "អង់គ្លេស និង ខ្មែរ"
TEXT_ONLY = "ទាញយកអត្ថបទ"
VOICE = "អត្ថបទទៅជាសំឡេង"
VOICE_TO_TEXT = "សំឡេងទៅជាអត្ថបទ"
IMAGE_SOURCE = "អត្ថបទពីរូបភាព"
MESSAGE_SOURCE = "អត្ថបទពីសារ"
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


async def record_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record lightweight per-user usage statistics for /profile."""
    user = update.effective_user
    if not user:
        return
    message = update.effective_message
    stats = context.user_data.setdefault("activity", {"messages": 0, "images": 0, "documents": 0, "voice": 0})
    stats["messages"] += 1
    if message and message.photo:
        stats["images"] += 1
    if message and message.document:
        stats["documents"] += 1
    if message and (message.voice or message.audio):
        stats["voice"] += 1
    if redis_client:
        try:
            key = f"activity:{user.id}"
            await asyncio.wait_for(redis_client.hincrby(key, "messages", 1), timeout=5)
            if message and message.photo:
                await asyncio.wait_for(redis_client.hincrby(key, "images", 1), timeout=5)
            if message and message.document:
                await asyncio.wait_for(redis_client.hincrby(key, "documents", 1), timeout=5)
            if message and (message.voice or message.audio):
                await asyncio.wait_for(redis_client.hincrby(key, "voice", 1), timeout=5)
        except Exception as error:
            logger.warning("Activity tracking skipped: %s", error)


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return
    display_name = user.full_name or user.username or "អ្នកប្រើប្រាស់"
    stats = context.user_data.get("activity", {})
    if redis_client:
        try:
            stored = await asyncio.wait_for(redis_client.hgetall(f"activity:{user.id}"), timeout=5)
            if stored:
                stats = {key.decode() if isinstance(key, bytes) else key: int(value) for key, value in stored.items()}
        except Exception as error:
            logger.warning("Profile activity lookup skipped: %s", error)
    await update.message.reply_text(
        "ប្រវត្តិរូបអ្នកប្រើប្រាស់\n\n"
        f"ឈ្មោះ៖ {display_name}\n"
        f"ចំនួនសារ៖ {stats.get('messages', 0)}\n"
        f"រូបភាព៖ {stats.get('images', 0)}\n"
        f"ឯកសារ៖ {stats.get('documents', 0)}\n"
        f"សារសំឡេង៖ {stats.get('voice', 0)}",
        reply_markup=language_keyboard(),
    )


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


async def reply_in_chunks(message, text: str, reply_markup=None) -> None:
    """Send long text safely within Telegram's message-size limit."""
    max_length = 3900
    chunks = [text[i : i + max_length] for i in range(0, len(text), max_length)] or [""]
    for index, chunk in enumerate(chunks):
        await message.reply_text(
            chunk,
            reply_markup=reply_markup if index == len(chunks) - 1 else None,
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
            if not image_data:
                logger.info("Text extraction completed from document/message: characters=%d", len(text))
                return clean_text(text)
            extracted = await translate_to("text")
            logger.info("Image text extracted: characters=%d", len(extracted))
            return extracted
        if target == "en":
            return f"English\n\n{await translate_to('en')}"
        if target == "km":
            return f"Khmer\n\n{await translate_to('km')}"
        english, khmer = await asyncio.gather(
            translate_to("en"),
            translate_to("km"),
        )
        return (
            f"English\n\n{english}\n\n"
            f"Khmer\n\n{khmer}"
        )
    except Exception:
        logger.exception("Translation request failed")
        return "សូមអភ័យទោស ខ្ញុំមិនអាចបកប្រែបានទេ។ សូមព្យាយាមម្តងទៀត។"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "សូមស្វាគមន៍មកកាន់កម្មវិធីបកប្រែ។\n\n"
        "សូមផ្ញើ ឬបញ្ជូនបន្តអត្ថបទ ឬបញ្ចូលរូបភាព រួចជ្រើសរើសជម្រើសមួយ៖\n\n"
        "«អង់គ្លេស និង ខ្មែរ» — បកប្រែជាភាសាទាំងពីរ\n"
        "«ទាញយកអត្ថបទ» — អានអត្ថបទពីរូបភាព ឬឯកសារ\n"
        "«អត្ថបទទៅជាសំឡេង» — បម្លែងអត្ថបទទៅជាសំឡេង\n"
        "«សំឡេងទៅជាអត្ថបទ» — បម្លែងសំឡេងទៅជាអត្ថបទ\n\n"
        "សូមជ្រើសរើសប៊ូតុងខាងក្រោម ដើម្បីចាប់ផ្តើម។",
        reply_markup=language_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "សូមផ្ញើ ឬបញ្ជូនបន្តអត្ថបទ ឬរូបភាព រួចជ្រើសរើសប៊ូតុងខាងក្រោម។\n\n"
        "ពាក្យបញ្ជា៖\n"
        "/start - ចាប់ផ្តើមកម្មវិធីបកប្រែ\n"
        "/help - បង្ហាញការណែនាំ\n"
        "/reset - លុបទិន្នន័យដែលកំពុងរង់ចាំ\n"
        "/status - ពិនិត្យសំណើដែលកំពុងរង់ចាំ\n"
        "/profile - បង្ហាញឈ្មោះ និងសកម្មភាពរបស់អ្នក",
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
        "អត្ថបទ និងទិន្នន័យរូបភាពដែលកំពុងរង់ចាំ ត្រូវបានលុបចោល។",
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
            "ប្រព័ន្ធកំពុងដំណើរការ។\n\n"
                "អ្នកមានសំណើដែលកំពុងរង់ចាំ។ សូមជ្រើសរើសប៊ូតុងខាងក្រោម ដើម្បីបន្ត។\n\n"
            "ប្រើ /reset ប្រសិនបើសំណើជាប់គាំង។",
            reply_markup=language_keyboard(),
        )
        return
    await update.message.reply_text(
        "ប្រព័ន្ធកំពុងដំណើរការ។\n\n"
        "មិនមានសំណើកំពុងរង់ចាំទេ។ សូមផ្ញើ ឬបញ្ជូនបន្តអត្ថបទ ឬរូបភាព ដើម្បីចាប់ផ្តើម។",
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
    if language == "km":
        # Gemini's official TTS language list does not include Khmer. Use the
        # Khmer-supported provider directly so Khmer is never synthesized with
        # the wrong language voice.
        audio.name = "translation.mp3"
        try:
            await asyncio.to_thread(gTTS(text=text, lang="km", slow=False).write_to_fp, audio)
        except Exception:
            logger.exception("Khmer voice generation failed: characters=%d", len(text))
            raise
        audio.seek(0)
        logger.info("Khmer voice generated successfully: bytes=%d", audio.getbuffer().nbytes)
        return audio
    audio.name = "translation.wav"
    api_key = os.getenv("GEMINI_API_KEY")
    tts_model = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
    try:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{tts_model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}},
            },
        }
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            parts = response.json()["candidates"][0]["content"]["parts"]
            audio_part = next(part for part in parts if part.get("inlineData"))
            pcm_data = base64.b64decode(audio_part["inlineData"]["data"])
        with wave.open(audio, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(pcm_data)
    except Exception:
        logger.exception(
            "Gemini TTS request failed: model=%s characters=%d",
            tts_model,
            len(text),
        )
        # Preserve Khmer voice support if the configured Gemini TTS model is
        # unavailable or does not support the requested account configuration.
        if language != "km":
            raise
        audio = BytesIO()
        audio.name = "translation.mp3"
        await asyncio.to_thread(gTTS(text=text, lang="km", slow=False).write_to_fp, audio)
    audio.seek(0)
    logger.info(
        "Voice generated successfully: model=%s bytes=%d duration_ms=%d",
        tts_model,
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
    await record_activity(update, context)
    text = clean_text(update.message.text or update.message.caption or "")
    image_data = None
    image_received = bool(
        update.message.photo
        or (
            update.message.document
            and (update.message.document.mime_type or "").startswith("image/")
        )
    )
    document_received = bool(update.message.document and not image_received)
    if image_received:
        media_group_id = update.message.media_group_id
        acknowledgement_key = f"image_ack:{media_group_id}" if media_group_id else "image_ack:single"
        logger.info(
            "Image update received: photo=%s document=%s caption_characters=%d",
            bool(update.message.photo),
            bool(update.message.document),
            len(text),
        )
        # Telegram sends each photo in an album as a separate update. Acknowledge
        # the album once instead of sending the same prompt for every photo.
        if not context.user_data.get(acknowledgement_key):
            context.user_data[acknowledgement_key] = True
            try:
                # Acknowledge immediately, but do not stop image processing if this
                # Telegram response temporarily fails.
                acknowledgement = (
                    "បានទទួលរូបភាពហើយ។ កំពុងរៀបចំ…\n\n"
                    "សូមជ្រើសរើសប៊ូតុង នៅពេលការរៀបចំរួចរាល់។"
                    if media_group_id
                    else "បានទទួលរូបភាពហើយ។ កំពុងរៀបចំ…\n\n"
                    "សូមជ្រើសរើសប៊ូតុង នៅពេលការរៀបចំរួចរាល់។"
                )
                await asyncio.wait_for(
                    update.message.reply_text(
                        acknowledgement,
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
            "ការដំណើរការរូបភាពចំណាយពេលយូរពេក ហើយត្រូវបានលុបចោល។ សូមផ្ញើរូបភាពតូចជាងនេះ។",
            reply_markup=language_keyboard(),
        )
        return
    except Exception:
        logger.exception("Could not download image")
        await delete_pending(update.effective_chat.id)
        await update.message.reply_text(
            "ខ្ញុំមិនអាចអានរូបភាពនេះបានទេ។ សូមផ្ញើរូបភាពតូចជាងនេះ ឬព្យាយាមម្តងទៀត។",
            reply_markup=language_keyboard(),
        )
        return
    if document_received:
        filename = update.message.document.file_name or ""
        caption_text = text
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
            extracted_text = await asyncio.wait_for(
                asyncio.to_thread(extract_document_text, filename, document_data),
                timeout=25,
            )
            if not extracted_text:
                await update.message.reply_text(
            "ខ្ញុំមិនអាចរកឃើញអត្ថបទដែលអាចអានបានក្នុងឯកសារនេះទេ។",
                    reply_markup=language_keyboard(),
                )
                return
            text = "\n\n".join(part for part in (caption_text, extracted_text) if part)
            logger.info(
                "Document text extracted: filename=%s characters=%d",
                filename or "(unnamed)",
                len(text),
            )
        except asyncio.TimeoutError:
            logger.error("Document processing timed out: filename=%s", filename or "(unnamed)")
            await update.message.reply_text(
                "ឯកសារនេះចំណាយពេលអានយូរពេក ហើយត្រូវបានលុបចោល។ សូមផ្ញើឯកសារតូចជាងនេះ។",
                reply_markup=language_keyboard(),
            )
            return
        except ValueError as error:
            logger.warning("Document rejected: filename=%s reason=%s", filename or "(unnamed)", error)
            await update.message.reply_text(
                "ឯកសារនេះធំពេក ឬមិនគាំទ្រ។ សូមផ្ញើ TXT, PDF, DOCX, XLSX ឬ XLSM ដែលមានទំហំរហូតដល់ ១០ MB។",
                reply_markup=language_keyboard(),
            )
            return
        except Exception:
            logger.exception("Could not read document: filename=%s", filename or "(unnamed)")
            await update.message.reply_text(
                "ខ្ញុំមិនអាចអានឯកសារនេះបានទេ។ សូមផ្ញើឯកសារ TXT, PDF, DOCX, XLSX ឬ XLSM។",
                reply_markup=language_keyboard(),
            )
            return
    if update.message.voice or update.message.audio:
        if context.user_data.get("mode") != "voice_to_text":
            await update.message.reply_text(
            "សូមជ្រើសរើស «សំឡេងទៅជាអត្ថបទ» ជាមុនសិន រួចផ្ញើសារសំឡេង ឬឯកសារសំឡេង។",
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
            await reply_in_chunks(
                update.message,
                result or "មិនរកឃើញសំឡេងនិយាយទេ។",
                reply_markup=language_keyboard(),
            )
        except asyncio.TimeoutError:
            logger.warning("Voice transcription timed out")
            await update.message.reply_text(
                "ការបម្លែងសំឡេងចំណាយពេលយូរពេក។ សូមផ្ញើសំឡេងខ្លីជាងនេះ។",
                reply_markup=language_keyboard(),
            )
        except Exception:
            logger.exception("Voice transcription failed")
            await update.message.reply_text(
                "ខ្ញុំមិនអាចបម្លែងសារសំឡេងនេះទៅជាអត្ថបទបានទេ។ សូមព្យាយាមម្តងទៀត។",
                reply_markup=language_keyboard(),
            )
        return
    if text == VOICE_TO_TEXT:
        context.user_data["mode"] = "voice_to_text"
        await update.message.reply_text(
            "បានជ្រើសរើស «សំឡេងទៅជាអត្ថបទ»។\n\nឥឡូវនេះ សូមផ្ញើសារសំឡេង ឬឯកសារសំឡេង។",
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
                "សូមផ្ញើ ឬបញ្ជូនបន្តអត្ថបទជាមុន រួចចុច «អត្ថបទទៅជាសំឡេង»។",
                reply_markup=language_keyboard(),
            )
            return
        # Text-to-voice should follow the text's script, not a previous
        # translation choice stored in the user's session.
        khmer_characters = sum("\u1780" <= char <= "\u17ff" for char in pending_text)
        # Gemini TTS automatically detects all of its supported languages.
        # Only Khmer needs a local route because Gemini TTS does not list Khmer.
        language = "km" if khmer_characters else "auto"
        logger.info(
            "Voice language routing selected: route=%s khmer_characters=%d",
            language,
            khmer_characters,
        )
        try:
            await update.message.chat.send_action(ChatAction.UPLOAD_VOICE)
            logger.info(
                "Single voice generation requested: language=%s characters=%d",
                language,
                len(pending_text),
            )
            audio = await asyncio.wait_for(send_voice(pending_text, language), timeout=45)
            voice = await asyncio.wait_for(convert_to_telegram_voice(audio), timeout=35)
            await update.message.reply_voice(
                voice=voice,
                reply_markup=language_keyboard(),
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Voice generation timed out: language=%s characters=%d",
                language,
                len(pending_text),
            )
            await update.message.reply_text(
                "ការបង្កើតសំឡេងចំណាយពេលយូរពេក ហើយត្រូវបានបញ្ឈប់។ សូមសាកល្បងអត្ថបទខ្លីជាងនេះ។",
                reply_markup=language_keyboard(),
            )
        except Exception:
            logger.exception("Voice generation failed")
            await update.message.reply_text(
                "ខ្ញុំមិនអាចបង្កើតសារសំឡេងបានទេ។ សូមព្យាយាមម្តងទៀតជាមួយអត្ថបទខ្លីជាងនេះ។",
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
            if target == "text" and not pending_image and not pending_text:
                await update.message.reply_text(
                    "សូមផ្ញើ ឬបញ្ជូនបន្តរូបភាព ឬឯកសារជាមុនសិន។",
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
                    "សំណើនេះចំណាយពេលយូរពេក ហើយត្រូវបានលុបចោល។ សូមព្យាយាមម្តងទៀតជាមួយរូបភាពតូចជាងនេះ ឬអត្ថបទខ្លីជាងនេះ។",
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
                    "ខ្ញុំមិនអាចដំណើរការសំណើនេះបានទេ ដូច្នេះវាត្រូវបានលុបចោល។ សូមព្យាយាមម្តងទៀតជាមួយរូបភាពតូចជាងនេះ ឬអត្ថបទខ្លីជាងនេះ។",
                    reply_markup=language_keyboard(),
                )
                return
            finally:
                if active_tasks.get(chat_id) is translation_task:
                    active_tasks.pop(chat_id, None)
            await reply_in_chunks(
                update.message,
                result,
                reply_markup=language_keyboard(),
            )
            return
        await update.message.reply_text(
            f"បានជ្រើសរើស {text}។\n\nសូមផ្ញើ ឬបញ្ជូនបន្តអត្ថបទ ឬរូបភាព រួចជ្រើសរើសប៊ូតុងខាងក្រោម។",
            reply_markup=language_keyboard(),
        )
        return
    if text in (IMAGE_SOURCE, MESSAGE_SOURCE):
        context.user_data["pending_source"] = "image" if text == IMAGE_SOURCE else "message"
        await update.message.reply_text(
            f"បានជ្រើសរើស {text}។\n\nសូមជ្រើសរើសជម្រើសបកប្រែខាងក្រោម៖",
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
            "សារនេះមានរូបភាព និងអត្ថបទដាច់ដោយឡែក។\n\nតើអ្នកចង់ឱ្យខ្ញុំដំណើរការអ្វី?",
            reply_markup=source_keyboard(),
        )
        return
    if image_received:
        # The immediate acknowledgement above is enough for image-only input.
        # Keep the keyboard visible without sending a duplicate "Text received" prompt.
        return
    await update.message.reply_text(
        "បានទទួលអត្ថបទហើយ។\n\nសូមជ្រើសរើសជម្រើសខាងក្រោម៖",
        reply_markup=language_keyboard(),
    )
