# Telegram Daily Report & AI Chatbot

A multi-purpose Telegram bot built with Python that seamlessly integrates **Daily Task Reporting** with a powerful **AI Chat Assistant** powered by OpenRouter. 

## 🌟 Features

- **Daily Task Reports**: Easily track your daily tasks by sending simple messages.
- **Smart Formatting**: Automatically generates clean, professional progress reports.
- **All-in-One AI Chatbot**: Talk to the bot normally to get instant AI responses powered by OpenRouter's vast selection of models. It automatically detects the difference between a task update and a chat message.
- **Profile Management**: Set up your name and project effortlessly.

## 🛠️ Requirements

- Python 3.10+
- `python-telegram-bot`
- `python-dotenv`
- `httpx` (for async OpenRouter API calls)

## 🚀 Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/kimhourchoch-zin/Telegram-Bot.git
   cd Telegram-Bot
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**
   Create a `.env` file in the root directory and add your API keys:
   ```env
   BOT_TOKEN=your_telegram_bot_token_here
   OPENROUTER_API_KEY=your_openrouter_api_key_here
   ```

4. **Run the bot:**
   ```bash
   python main.py
   ```
   *(Note: this uses `run_polling()`; Docker deployment also runs the same long-lived process.)*

## OpenRouter model

By default the bot uses OpenAI's GPT-3.5 Turbo via OpenRouter: `openai/gpt-3.5-turbo`.
You can override it with `OPENROUTER_MODEL` (and optionally `OPENROUTER_MAX_TOKENS`, `OPENROUTER_TEMPERATURE`).

## Deploy on Your Own Server (Docker, 24/7)

1. Install Docker on your server.
2. Make sure `BOT_TOKEN` and `OPENROUTER_API_KEY` are set in `.env`.
3. Build and start:

```bash
docker compose up -d --build
```

To restart:

```bash
docker compose restart
```

Logs:

```bash
docker compose logs -f my-boy-bot
```

## 💬 Usage

### Basic Commands
- `/start` - Start the bot and initialize your profile (Name and Project).
- `/setup` - Configure your profile for daily reporting (prompts for your name, then project).
- `/show` - View your generated daily progress report for today.
- `/profile` - Check your currently configured Name and Project.
- `/clear` - Wipe out all tasks logged for today.
- `/reset` - Clear your profile to set a new Name and Project.

### How to use the Bot

1. **Adding a Task Update:**
   Send a message ending with a number or percentage.
   - Example: `Fixed login screen bug 100%`
   - Example: `Setup database schema 50`
   *If the number is 100, it's marked as "Completed". Otherwise, it's marked as "In Progress".*

2. **Chatting with AI:**
   Just talk to the bot! If your message doesn't format like a task update (i.e. doesn't end in a number), the bot will forward your query to the OpenRouter AI and reply instantly.
   - Example: `What are the top 3 frameworks for Python?`
   - Example: `Write a regular expression for an email address.`

## 📂 Project Structure

- `main.py`: The entry point configuring the bot application.
- `src/bot/handlers.py`: Contains all command logic, message parsing, AI integration, and routing.
- `src/bot/storage.py`: Handles local JSON based storage for users and their daily reports in the `/data/` folder.
