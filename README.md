# Telegram Daily Report & AI Chatbot

A multi-purpose Telegram bot built with Python that seamlessly integrates **Daily Task Reporting** with a powerful **AI Chat Assistant** powered by Groq (Llama 3). 

## 🌟 Features

- **Daily Task Reports**: Easily track your daily tasks by sending simple messages.
- **Smart Formatting**: Automatically generates clean, professional progress reports.
- **All-in-One AI Chatbot**: Talk to the bot normally to get instant AI responses powered by Groq's high-speed inference. It automatically detects the difference between a task update and a chat message.
- **Profile Management**: Set up your name and project effortlessly.

## 🛠️ Requirements

- Python 3.10+
- `python-telegram-bot`
- `python-dotenv`
- `httpx` (for async Groq API calls)

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
   TOKEN=your_telegram_bot_token_here
   GROQ_API_KEY=your_groq_api_key_here
   ```

4. **Run the bot:**
   ```bash
   python main.py
   ```
   *(Note: This uses `run_polling()` for local development. On Vercel we use a webhook endpoint instead of polling.)*

## Running on Vercel (24/7)

Vercel serverless functions don't keep long-running polling processes alive. To run your Telegram bot "24/7" on Vercel, configure Telegram to send updates to the webhook endpoint:

- Deploy to Vercel.
- In Vercel environment variables, set `TOKEN` and `GROQ_API_KEY`.
- Set your Telegram webhook to:
  `https://<your-vercel-domain>/api/telegram`

One way to set it (replace the placeholders):

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-vercel-domain>/api/telegram"
```

## Groq model

By default the bot uses Groq’s recommended general-purpose model: `llama-3.3-70b-versatile`.
You can override it with `GROQ_MODEL` (and optionally `GROQ_MAX_TOKENS`, `GROQ_TEMPERATURE`).

## 💬 Usage

### Basic Commands
- `/start` - Start the bot and initialize your profile (Name and Project).
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
   Just talk to the bot! If your message doesn't format like a task update (i.e. doesn't end in a number), the bot will forward your query to the Groq AI and reply instantly.
   - Example: `What are the top 3 frameworks for Python?`
   - Example: `Write a regular expression for an email address.`

## 📂 Project Structure

- `main.py`: The entry point configuring the bot application.
- `src/bot/handlers.py`: Contains all command logic, message parsing, AI integration, and routing.
- `src/bot/storage.py`: Handles local JSON based storage for users and their daily reports in the `/data/` folder.
