# Telegram Daily Report and AI Chatbot

A professional Telegram bot for daily task reporting and AI-assisted chat. The bot receives Telegram updates through a FastAPI webhook, stores user profiles and reports in MySQL, encrypts sensitive fields, and forwards regular chat messages to OpenRouter.

## Features

- Daily task reporting with percentage-based progress tracking.
- Automatic report formatting for completed and in-progress tasks.
- AI chat support through OpenRouter for non-report messages.
- User profile setup for employee name and project name.
- MySQL persistence with encrypted profile, task, and chat-history fields.
- FastAPI webhook server with a `/health` endpoint.
- GitHub Actions CI for linting and syntax checks.

## Requirements

- Python 3.12 or compatible Python 3.10+
- Telegram bot token from BotFather
- OpenRouter API key
- MySQL 8.0

## Project Structure

```text
.
|-- main.py                 # Application entry point
|-- src/bot/main.py         # FastAPI webhook server and Telegram application setup
|-- src/bot/handlers.py     # Telegram commands, message parsing, and OpenRouter integration
|-- src/bot/storage.py      # MySQL persistence and field encryption
|-- requirements.txt        # Python dependencies
`-- .env.example            # Environment variable template
```

## Configuration

Create a `.env` file from the example template:

```bash
cp .env.example .env
```

Configure the following values:

```env
WEBHOOK_URL=https://your-domain.com
PORT=8000

BOT_TOKEN=your_telegram_bot_token
BOT_NAME=My Bot
DEVELOPER_NAME=Your Name

OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=openai/gpt-3.5-turbo

DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=bot_db
DB_USER=bot_user
DB_PASSWORD=bot_pass

ENCRYPTION_KEY=your_fernet_key
```

Generate an encryption key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep `ENCRYPTION_KEY` stable after setup. Changing it prevents existing encrypted profile, report, and chat-history data from being decrypted.

## Running the Bot

Install dependencies:

```bash
pip install -r requirements.txt
```

Make sure MySQL is running and the database settings in `.env` are valid.

Start the webhook server:

```bash
python main.py
```

The server listens on `0.0.0.0:${PORT}` and exposes:

- `POST /webhook/{BOT_TOKEN}` for Telegram updates.
- `GET /health` for health checks.

Telegram requires `WEBHOOK_URL` to be a public HTTPS URL.

## Bot Commands

- `/start` - Create or resume a user session and show the main menu.
- `/setup` - Configure the user's name and project.
- `/show` - Show today's generated daily progress report.
- `/profile` - Show the configured profile.
- `/clear` - Clear today's recorded tasks.
- `/reset` - Reset the configured name and project.

## Usage

Set up a profile first with `/setup`, then send task updates ending in a percentage:

```text
Fixed login screen bug 100%
Created dashboard layout 50%
```

Tasks at `100%` are marked as completed. Other percentages are marked as in progress.

Messages that do not match the task format are treated as AI chat messages and sent to OpenRouter:

```text
Write a short summary for today's progress.
```

## Security Notes

- Do not commit `.env` or database files.
- Use a strong, stable `ENCRYPTION_KEY`.
- Keep `WEBHOOK_URL` set to the public HTTPS origin only, without the webhook path.
- Restrict database access to trusted hosts only.

## Continuous Integration

The repository includes a GitHub Actions workflow at `.github/workflows/ci.yml`.

The workflow runs on pushes to `main` or `master` and on pull requests. It installs dependencies, runs Ruff linting, and compiles Python files to catch syntax errors without requiring a live MySQL database.

## License

This project is licensed under the MIT License. See `LICENSE` for details.

## Copyright

Copyright (c) 2026 Choch Kimhour.
