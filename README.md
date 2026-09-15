# Telegram English–Khmer Translator

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-26A5E4)](https://core.telegram.org/bots)
[![FastAPI](https://img.shields.io/badge/FastAPI-Webhook-009688)](https://fastapi.tiangolo.com/)
[![Google Gemini](https://img.shields.io/badge/Translation-Google_Gemini-4285F4)](https://ai.google.dev/gemini-api/docs)
[![Vercel](https://img.shields.io/badge/Deploy-Vercel-000000)](https://vercel.com/)
[![GitHub Actions](https://img.shields.io/badge/CI%2FCD-GitHub_Actions-2088FF)](https://github.com/features/actions)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

A simple Telegram bot that translates text and reads text from images using Google Gemini.

## What it does

- Send or forward text in any language.
- Choose `EN + KM` to receive English and Khmer together.
- Send or paste text and choose `Text to Voice` to receive spoken audio.
- Send or forward an image and choose `Extract Text` to get clean OCR text.
- Send a voice message or audio file to receive clean transcribed text.
- Send TXT, PDF, DOCX, XLSX, or XLSM files to extract their text for translation or voice.
- Supports image captions and images sent as photos or files.
- Images are acknowledged immediately, and slow requests are removed after 60 seconds with a user message.
- Uses Redis temporarily for pending text/images; data expires after 10 minutes or after processing.
- Uses local polling or a FastAPI webhook on Vercel.

## Requirements

- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Uses Google Gemini for automatic language detection and translation.

## Run locally

1. Create a virtual environment and install packages:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install .
   ```

2. Copy `.env.example` to `.env` and add your Telegram, webhook, Gemini, and Redis settings.

3. Start the server:

   ```bash
   python main.py
   ```

When `WEBHOOK_URL` is empty, the bot automatically uses local polling, so you can test it directly in Telegram without ngrok or a webhook. On Vercel, the bot automatically uses the Vercel deployment URL as its webhook URL.

The default local port is `9999`.

After `/start`, the menu has four buttons in a 2×2 layout:

```text
🌐 EN + KM           📝 Extract Text
🔊 Text to Voice     🎙️ Voice to Text
```

For image OCR, send or forward the image first, then press `📝 Extract Text`. The bot returns plain extracted text without headings or explanations.

For text-to-voice, send or paste text, then press `🔊 Text to Voice`. Khmer text is spoken in Khmer; other text is spoken in English. Keep the text reasonably short for faster audio generation.

For voice-to-text, send a Telegram voice message or audio file. The bot returns clean, copyable transcription text.

Images are limited to 10 MB. Failed downloads receive a friendly error message and do not stop the bot.

## Deploy on Vercel

1. Push this project to GitHub.
2. In Vercel, choose **Add New → Project** and import the repository.
3. Add these environment variables in Vercel:

   - `BOT_TOKEN` = your Telegram bot token
   - `WEBHOOK_SECRET` = a long random secret used in the webhook path
   - `GEMINI_API_KEY` = your Google Gemini API key
   - `GEMINI_MODEL` = `gemini-3.6-flash`
   - `REDIS_URL` = your Redis connection URL for pending images/text

4. Deploy the project. Vercel automatically detects `api/index.py` as a Python Function and provides the public URL used for the Telegram webhook.

The webhook endpoint uses `/api/webhook/<WEBHOOK_SECRET>` and validates Telegram’s secret header. The Telegram bot token is never included in the public webhook path. Redis data expires after 10 minutes and is deleted after processing.

## Commands

- `/start` — start the bot
- `/help` — show instructions
- `/reset` — remove pending text, image, and source-selection data if a request is stuck
- `/status` — check that the bot is online and whether a request is pending

Telegram suggests these commands when you type /. Use `/reset` if an image or translation appears stuck.

Keep `.env` private and never commit API keys to GitHub.

Never expose Telegram, Gemini, Redis, or webhook secrets. Rotate any secret that has been exposed.

## GitHub Actions checks

The workflow in `.github/workflows/ci-cd.yml` installs the project and compiles the Python code on every pull request and push. Vercel deploys automatically when the GitHub repository is connected to a Vercel project.

The bot uses Gemini 3.6 Flash to automatically detect the source language, read images/documents/audio, and translate into English and Khmer. See the [Gemini model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

Copyright (c) 2026.
