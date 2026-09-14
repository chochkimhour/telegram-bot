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
- Choose `English`, `Khmer`, or `Both` for translation.
- Send or forward an image and choose `Text` to extract readable text only.
- Supports image captions and images sent as photos or files.
- No database and no user data storage.
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

2. Copy `.env.example` to `.env` and add your Telegram and Gemini keys.

3. Start the server:

   ```bash
   python main.py
   ```

When `WEBHOOK_URL` is empty, the bot automatically uses local polling, so you can test it directly in Telegram without ngrok or a webhook. On Vercel, the bot automatically uses the Vercel deployment URL as its webhook URL.

The default local port is `9999`.

After `/start`, the menu has four buttons in a 2×2 layout:

```text
🇬🇧 English    🇰🇭 Khmer
🌐 Both        📝 Text
```

For image OCR, send or forward the image first, then press `📝 Text`. The bot returns plain extracted text without headings or explanations.

## Deploy on Vercel

1. Push this project to GitHub.
2. In Vercel, choose **Add New → Project** and import the repository.
3. Add these environment variables in Vercel:

   - `BOT_TOKEN` = your Telegram bot token
   - `GEMINI_API_KEY` = your Google Gemini API key
   - `GEMINI_MODEL` = `gemini-3.1-flash-lite`

4. Deploy the project. Vercel automatically detects `api/index.py` as a Python Function and provides the public URL used for the Telegram webhook.

Vercel Functions are stateless. The send-then-select workflow requires temporary per-user storage for production image use; local polling is recommended for testing this workflow without a database.

## Commands

- `/start` — start the bot
- `/help` — show instructions

Keep `.env` private and never commit API keys to GitHub.

## GitHub Actions checks

The workflow in `.github/workflows/ci-cd.yml` installs the project and compiles the Python code on every pull request and push. Vercel deploys automatically when the GitHub repository is connected to a Vercel project.

The bot uses Gemini 3.1 Flash-Lite to automatically detect the source language and translate into English and Khmer. Google describes this model as suitable for fast, high-volume translation. See the [Gemini model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

Copyright (c) 2026.
