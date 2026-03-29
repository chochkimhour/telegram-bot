import logging
import re
import os
import httpx
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from src.bot import storage

logger = logging.getLogger(__name__)

BOT_NAME = os.getenv("BOT_NAME")
DEVELOPER_NAME = os.getenv("DEVELOPER_NAME")

def _log_request(update: Update, action: str):
    user = update.effective_user
    # Mask message text for privacy as per user request
    text_preview = "[HIDDEN]"
    if update.message and update.message.text:
        # Show first few chars if it's a command, otherwise keep hidden
        if update.message.text.startswith('/'):
            text_preview = update.message.text[:20] + "..." if len(update.message.text) > 20 else update.message.text
    
    logger.info(
        f"chat_id={update.effective_chat.id} user={user.username or user.first_name} "
        f"action={action} text=\"{text_preview}\""
    )

def _is_name_question(text: str) -> bool:
    t = text.lower()
    return bool(
        re.search(
            r"\b(what(?:'s| is) your name|your name|bot name|name of (this )?(bot|assistant)|who are you|what are you|introduce yourself)\b",
            t,
        )
    )

def _is_developer_question(text: str) -> bool:
    t = text.lower()
    return bool(
        re.search(
            r"\b(develop\w*|made|built|created)\b.*\b(by)\b|\bwho (made|built|created)\b|\bdeveloper\b",
            t,
        )
    )

OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL")

def format_ai_response(text: str) -> str:
    """Simple helper to make AI Markdown look better in Telegram's basic Markdown mode."""
    # Convert headers (### Header) to bold (*Header*)
    text = re.sub(r"^###\s+(.*)$", r"*\1*", text, flags=re.MULTILINE)
    text = re.sub(r"^##\s+(.*)$", r"*\1*", text, flags=re.MULTILINE)
    text = re.sub(r"^#\s+(.*)$", r"*\1*", text, flags=re.MULTILINE)
    return text

async def ask_openrouter(user: dict, prompt: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "Internal Error: OPENROUTER_API_KEY is not configured."
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/kimhourchoch-zin/Telegram-Bot",
        "X-Title": "My Boy Telegram Bot"
    }

    system_content = "You are a friendly and helpful AI assistant."
    if user.get("name"):
        system_content += f" The user's name is {user.get('name')}."
    if user.get("project"):
        system_content += f" The user is working on a project named {user.get('project')}."

    messages = [{"role": "system", "content": system_content}]
    history = user.get("chat_history") or []
    messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", "2048"))
    temperature = float(os.getenv("OPENROUTER_TEMPERATURE", "0.2"))

    data = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        logger.info(f"Trying model: {data['model']}")
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data, timeout=30.0)
            response.raise_for_status()
            result = response.json()
            reply = result["choices"][0]["message"]["content"]

            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": reply})
            storage.update_user(user["chat_id"], "chat_history", history[-20:])

            return reply
    except Exception as e:
        logger.error(f"OpenRouter API error: {e}")
        return "Sorry, I couldn't reach the AI at the moment. Please try again later."

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🚀 Start"), KeyboardButton("👤 Profile")],
        [KeyboardButton("⚙️ Setup"), KeyboardButton("📊 Show")],
        [KeyboardButton("🧹 Clear"), KeyboardButton("🔄 Reset")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_request(update, "COMMAND /start")
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username or update.effective_user.first_name

    user = storage.find_user(chat_id)
    if not user:
        storage.create_user(chat_id, username)
    else:
        # Clear any trapped setup state
        if user.get("step") in ["ASK_NAME", "ASK_PROJECT"]:
            storage.update_user(chat_id, "step", "NONE")

    await update.message.reply_text(
        f"👋 *Welcome!* I am *{BOT_NAME}* (AI Chatbot + Daily Reporter).\n\n"
        f"Please choose an option from the menu below:",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_request(update, "COMMAND /setup")
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username or update.effective_user.first_name

    user = storage.find_user(chat_id)
    if not user:
        storage.create_user(chat_id, username)

    storage.update_user(chat_id, "name", None)
    storage.update_user(chat_id, "project", None)
    storage.update_user(chat_id, "step", "ASK_NAME")
    await update.message.reply_text("Let's set up your profile for daily reports!\nPlease enter your name:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_request(update, "MESSAGE")
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()
    user = storage.find_user(chat_id)

    if not user:
        user = storage.create_user(chat_id, update.effective_user.username or update.effective_user.first_name)

    # Process menu buttons
    if text == "🚀 Start":
        return await start(update, context)
    elif text == "⚙️ Setup":
        return await setup(update, context)
    elif text == "👤 Profile":
        return await profile(update, context)
    elif text == "📊 Show":
        return await show(update, context)
    elif text == "🧹 Clear":
        return await clear(update, context)
    elif text == "🔄 Reset":
        return await reset(update, context)

    step = user.get("step")

    if step == "ASK_NAME":
        storage.update_user(chat_id, "name", text)
        storage.update_user(chat_id, "step", "ASK_PROJECT")
        return await update.message.reply_text("Got it!\nNow enter your project:")

    if step == "ASK_PROJECT":
        storage.update_user(chat_id, "project", text)
        storage.update_user(chat_id, "step", "READY")
        return await update.message.reply_text("Setup complete! You can now log tasks or chat with me.")

    # Identity responses: keep these exact and don't forward to Groq.
    if _is_name_question(text) or _is_developer_question(text):
        if _is_name_question(text) and _is_developer_question(text):
            return await update.message.reply_text(
                f"I'm *{BOT_NAME}*. Developed by *{DEVELOPER_NAME}*.",
                parse_mode=ParseMode.MARKDOWN
            )
        if _is_name_question(text):
            return await update.message.reply_text(f"My name is *{BOT_NAME}*.", parse_mode=ParseMode.MARKDOWN)
        return await update.message.reply_text(f"Developed by *{DEVELOPER_NAME}*.", parse_mode=ParseMode.MARKDOWN)

    # Process report OR Chat
    # Advanced multi-task detection: Look for patterns of [text] followed by [number]%?
    # This works across multiple lines or even multiple tasks on the same line.
    # Ex: "Fixed bugs 100 Fix issues 50" -> catches both.
    tasks_to_log = []
    
    # This regex finds text followed by a number (and optional %)
    # It avoids greedily grabbing the numbers.
    pattern = r"([a-zA-Z\s\u2022\-\.]+?)\s*(\d+)%?\b"
    found_matches = re.findall(pattern, text)
    
    for task_name, percent_str in found_matches:
        task_name = task_name.strip()
        # Clean up common prefixes from chat or bullet points
        task_name = re.sub(r"^[\u2022\-\*\d\.]+\s*", "", task_name).strip()
        if task_name:
            tasks_to_log.append((task_name, int(percent_str)))

    # If no tasks are found, treat as a chat message.
    if not tasks_to_log:
        await update.message.chat.send_action(action="typing")
        reply = await ask_openrouter(user, text)
        return await update.message.reply_text(format_ai_response(reply), parse_mode=ParseMode.MARKDOWN)

    # If the user hasn't configured a profile, they probably didn't intend to log a task.
    if not user.get("name") or not user.get("project"):
        await update.message.chat.send_action(action="typing")
        reply = await ask_openrouter(user, text)
        return await update.message.reply_text(format_ai_response(reply), parse_mode=ParseMode.MARKDOWN)

    now = datetime.now()
    date_str = now.strftime("%d-%m-%Y")
    date_display = now.strftime("%d %B %Y")
    timestamp = now.strftime("%H:%M")

    # Save all found tasks
    for task_name, percent in tasks_to_log:
        status_text = "Completed" if percent == 100 else "In Progress"
        storage.save_report(user, task_name, percent, status_text, date_str, timestamp)

    # Build formatted report
    report_data = storage.load_today_report(user, date_str)
    tasks = report_data.get("tasks", []) if report_data else []

    completed = [t for t in tasks if t["status"] == "Completed"]
    in_progress = [t for t in tasks if t["status"] == "In Progress"]

    lines = []
    lines.append("*DAILY PROGRESS REPORT*")
    lines.append(f"\n*Date:* {date_display}")
    lines.append(f"*Employee:* {user.get('name')}")
    lines.append(f"*Project:* {user.get('project')}")
    lines.append("\n*1. Code Inspection*")
    lines.append("Status: N/A")
    lines.append("*2. Progress on Tasks*")
    if completed:
        lines.append("*Completed*")
        for t in completed:
            lines.append(f"\u2022 {t['task']} ({t['percent']}%)")
    if in_progress:
        lines.append("*In Progress*")
        for t in in_progress:
            lines.append(f"\u2022 {t['task']} ({t['percent']}%)")
    if not completed and not in_progress:
        lines.append("Status: N/A")
    lines.append("*3. Challenges / Issues*")
    lines.append("Status: N/A")
    lines.append("*4. Problem-Solving Approach*")
    lines.append("Status: N/A")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_request(update, "COMMAND /show")
    chat_id = str(update.effective_chat.id)
    user = storage.find_user(chat_id)
    
    if not user or not user.get("name") or not user.get("project"):
        return await update.message.reply_text("Please use /start to set your name and project first.")
        
    now = datetime.now()
    date_str = now.strftime("%d-%m-%Y")
    date_display = now.strftime("%d %B %Y")
    
    report_data = storage.load_today_report(user, date_str)
    tasks = report_data.get("tasks", []) if report_data else []
    
    if not tasks:
        return await update.message.reply_text("You have no tasks recorded for today.")
        
    completed = [t for t in tasks if t["status"] == "Completed"]
    in_progress = [t for t in tasks if t["status"] == "In Progress"]
    
    lines = []
    lines.append("*DAILY PROGRESS REPORT*")
    lines.append(f"\n*Date:* {date_display}")
    lines.append(f"*Employee:* {user.get('name')}")
    lines.append(f"*Project:* {user.get('project')}")
    lines.append("\n*1. Code Inspection*")
    lines.append("Status: N/A")
    lines.append("*2. Progress on Tasks*")
    if completed:
        lines.append("*Completed*")
        for t in completed:
            lines.append(f"\u2022 {t['task']} ({t['percent']}%)")
    if in_progress:
        lines.append("*In Progress*")
        for t in in_progress:
            lines.append(f"\u2022 {t['task']} ({t['percent']}%)")
    if not completed and not in_progress:
        lines.append("Status: N/A")
    lines.append("*3. Challenges / Issues*")
    lines.append("Status: N/A")
    lines.append("*4. Problem-Solving Approach*")
    lines.append("Status: N/A")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_request(update, "COMMAND /clear")
    chat_id = str(update.effective_chat.id)
    user = storage.find_user(chat_id)
    
    if not user or not user.get("name"):
        return await update.message.reply_text("Please use /start to set your name first.")
        
    now = datetime.now()
    date_str = now.strftime("%d-%m-%Y")
    storage.clear_today_report(user, date_str)
    await update.message.reply_text("Today's tasks have been cleared.")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_request(update, "COMMAND /reset")
    chat_id = str(update.effective_chat.id)
    user = storage.find_user(chat_id)
    
    if not user:
        return await update.message.reply_text("Please use /start to set your name first.")

    storage.update_user(chat_id, "name", None)
    storage.update_user(chat_id, "project", None)
    storage.update_user(chat_id, "step", "ASK_NAME")
    await update.message.reply_text("Your name and project have been reset. Please enter your name:")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_request(update, "COMMAND /profile")
    chat_id = str(update.effective_chat.id)
    user = storage.find_user(chat_id)
    
    if not user or not user.get("name") or not user.get("project"):
        return await update.message.reply_text("You haven't set up your profile yet. Please use /start.")
        
    name = user.get("name")
    project = user.get("project")
    await update.message.reply_text(
        f"👤 *Profile Information*\n"
        f"{'─' * 20}\n"
        f"*Name:* {name}\n"
        f"*Project:* {project}",
        parse_mode=ParseMode.MARKDOWN
    )
