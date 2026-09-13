# Telegram English–Khmer Translator

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-26A5E4)](https://core.telegram.org/bots)
[![FastAPI](https://img.shields.io/badge/FastAPI-Webhook-009688)](https://fastapi.tiangolo.com/)
[![Lingva Translate](https://img.shields.io/badge/Translation-Lingva-orange)](https://github.com/thedaviddelta/lingva-translate)
[![Vercel](https://img.shields.io/badge/Deploy-Vercel-000000)](https://vercel.com/)
[![GitHub Actions](https://img.shields.io/badge/CI%2FCD-GitHub_Actions-2088FF)](https://github.com/features/actions)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

A simple Telegram bot that translates text from any language into English and Khmer.

## What it does

- Send text in any language.
- Choose English, Khmer, or Both with the menu buttons.
- Send or forward text, then choose a button for translation.
- No database and no user data storage.
- Uses a Telegram webhook and can run on Vercel.

## Requirements

- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Uses the Lingva Translate API for automatic language detection and translation.

## Run locally

1. Create a virtual environment and install packages:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install .
   ```

2. Copy `.env.example` to `.env` and add your `BOT_TOKEN`.

3. Start the server:

   ```bash
   python main.py
   ```

When `WEBHOOK_URL` is empty, the bot automatically uses local polling, so you can test it directly in Telegram without ngrok or a webhook. On Vercel, the bot automatically uses the Vercel deployment URL as its webhook URL.

The default local port is `9999`.

## Deploy on Vercel

1. Push this project to GitHub.
2. In Vercel, choose **Add New → Project** and import the repository.
3. Add these environment variables in Vercel:

   - `BOT_TOKEN` = your Telegram bot token
   - `LINGVA_URL` = `https://lingva.ml` (optional; backup instances are automatic)

4. Deploy the project. Vercel automatically detects `api/index.py` as a Python Function and provides the public URL used for the Telegram webhook.

## Commands

- `/start` — start the bot
- `/help` — show instructions

Keep `.env` private and never commit API keys to GitHub.

## GitHub Actions checks

The workflow in `.github/workflows/ci-cd.yml` installs the project and compiles the Python code on every pull request and push. Vercel deploys automatically when the GitHub repository is connected to a Vercel project.

The bot uses Lingva to automatically detect the source language and translate into English (`en`) and Khmer (`km`). It tries backup Lingva instances and then a direct Google Translate web fallback if the public instances are unavailable. These free endpoints are unofficial and may occasionally be rate-limited. See the [Lingva Translate API documentation](https://github.com/thedaviddelta/lingva-translate#public-apis).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

Copyright (c) 2026.
