# Telegram English–Khmer Translator

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-26A5E4)](https://core.telegram.org/bots)
[![FastAPI](https://img.shields.io/badge/FastAPI-Webhook-009688)](https://fastapi.tiangolo.com/)
[![MyMemory](https://img.shields.io/badge/Translation-MyMemory-orange)](https://mymemory.translated.net/doc/spec.php)
[![Render](https://img.shields.io/badge/Deploy-Render-46E3B7)](https://render.com/)
[![GitHub Actions](https://img.shields.io/badge/CI%2FCD-GitHub_Actions-2088FF)](https://github.com/features/actions)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

A simple Telegram bot that translates text from any language into English and Khmer.

## What it does

- Send text in any language.
- Choose English, Khmer, or Both with the menu buttons.
- Send or forward text, then choose a button for translation.
- No database and no user data storage.
- Uses a Telegram webhook and can run on Render.

## Requirements

- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- No translation API key is required. The bot uses the MyMemory translation API.

## Run locally

1. Create a virtual environment and install packages:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install .
   ```

2. Copy `.env.example` to `.env` and add your `BOT_TOKEN`. `MYMEMORY_EMAIL` is optional.

3. Start the server:

   ```bash
   python main.py
   ```

When `WEBHOOK_URL` is empty, the bot automatically uses local polling, so you can test it directly in Telegram without ngrok or a webhook. The local health server is not used in polling mode.

The default local port is `9999`.

## Deploy on Render

1. Push this project to GitHub.
2. In Render, choose **New → Web Service** and connect the repository.
3. Use these settings:

   - **Runtime:** Python 3
   - **Build command:** `pip install .`
   - **Start command:** `python main.py`
   - **Health check path:** `/health`

4. Add these environment variables in Render:

   - `BOT_TOKEN` = your Telegram bot token
   - `MYMEMORY_EMAIL` = optional email for MyMemory usage limits

Render provides the public `RENDER_EXTERNAL_URL` automatically. The bot uses it to register the Telegram webhook. Render also provides `PORT`; locally the default is `9999`.

## Commands

- `/start` — start the bot
- `/help` — show instructions

Keep `.env` private and never commit API keys to GitHub.

## GitHub Actions deployment

The workflow in `.github/workflows/ci-cd.yml` compiles the project on every pull request and push. To deploy automatically to Render after pushes to `main` or `master`, create a Render deploy hook and add it to GitHub as the repository secret `RENDER_DEPLOY_HOOK_URL`. If the secret is missing, checks still run and deployment is skipped.

The bot uses MyMemory to automatically translate into English (`en`) and Khmer (`km`). Requests are limited to 500 bytes by the MyMemory API. See the [MyMemory API documentation](https://mymemory.translated.net/doc/spec.php).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

Copyright (c) 2026.
