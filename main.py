import os
import asyncio
import logging
from datetime import datetime
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ===== НАСТРОЙКИ =====
TOKEN = ("8722347795:AAHkjvoZ0sAPZMb6wztkRI9YuDB-E8zoUKU")
CHANNEL = "@Data_Osinter"

DAILY_LIMIT = 3
ANTISPAM = 5
SEARCH_TIMEOUT = 300

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

users = {}
last_request = {}

# ===== КНОПКИ =====

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚑ Флажки", callback_data="flags")],
        [InlineKeyboardButton("ℹ️ Информация", callback_data="info")]
    ])

def back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅ Назад", callback_data="back")]
    ])

# ===== START =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid not in users:
        users[uid] = {
            "limit": DAILY_LIMIT,
            "date": str(datetime.now().date())
        }

    await update.message.reply_text(
        "👋 Отправь username или username с флагами\n\nПример:\nusername --timeout 5",
        reply_markup=main_kb()
    )

# ===== КНОПКИ =====

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "flags":
        await q.edit_message_text(
            """
⚑ Флажки:

--timeout 5 → быстрее  
--retries 0 → без повторов  
--proxy URL → прокси  
--tor-proxy → TOR  
--with-domains → домены  
--top-sites 500 → лимит сайтов  

📌 Пример:
username --timeout 5
""",
            reply_markup=back_kb()
        )

    elif q.data == "info":
        await q.edit_message_text(
            "Бот ищет аккаунты через Maigret",
            reply_markup=back_kb()
        )

    elif q.data == "back":
        await q.edit_message_text(
            "Отправь username",
            reply_markup=main_kb()
        )

# ===== ПАРСЕР MAIGRET =====

def parse_maigret_output(text):
    results = []

    for line in text.splitlines():
        line = line.strip()

        # ловим строки вида: [+] Site: https://...
        if "[+]" in line and "http" in line:
            parts = line.split()
            for p in parts:
                if p.startswith("http"):
                    results.append(p)

        # иногда просто ссылки
        elif line.startswith("http"):
            results.append(line)

    return list(set(results))

# ===== ПОИСК =====

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    now = asyncio.get_running_loop().time()

    # антиспам
    if uid in last_request and now - last_request[uid] < ANTISPAM:
        await update.message.reply_text("⚠ Подожди пару секунд")
        return

    last_request[uid] = now

    # лимит
    user = users.get(uid)
    if user:
        today = str(datetime.now().date())
        if user["date"] != today:
            user["date"] = today
            user["limit"] = DAILY_LIMIT

        if user["limit"] <= 0:
            await update.message.reply_text("❌ Лимит на сегодня исчерпан")
            return

        user["limit"] -= 1

    parts = text.split()
    username = parts[0]
    flags = parts[1:]

    msg = await update.message.reply_text("🔎 Ищу...")

    try:
        cmd = ["python3", "-m", "maigret", username]
        cmd += flags

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=SEARCH_TIMEOUT
        )

    except Exception as e:
        logger.error(e)
        await msg.edit_text("⚠ Ошибка запуска")
        return

    output = stdout.decode(errors="ignore")
    error = stderr.decode(errors="ignore")

    # если есть ошибка — показываем
    if error.strip():
        await msg.edit_text(f"Ошибка:\n{error[:500]}")
        return

    links = parse_maigret_output(output)

    if not links:
        await msg.edit_text("❌ Ничего не найдено")
        return

    file = BytesIO("\n".join(links).encode())
    file.name = f"{username}.txt"

    await context.bot.send_document(uid, file)
    await msg.delete()

# ===== MAIN =====

def main():
    if not TOKEN:
        raise RuntimeError("Нет BOT_TOKEN")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))

    app.run_polling()

if __name__ == "__main__":
    main()
