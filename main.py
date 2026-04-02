import os
import json
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
MAX_CONCURRENT = 3

DB_FILE = "users.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

semaphore = asyncio.Semaphore(MAX_CONCURRENT)
last_request = {}

# ===== БАЗА =====

def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db():
    with open(DB_FILE, "w") as f:
        json.dump(db, f)

db = load_db()

def get_user(uid):
    uid = str(uid)

    if uid not in db:
        db[uid] = {
            "requests": DAILY_LIMIT,
            "date": str(datetime.now().date()),
            "referrals": 0,
            "invited_by": None
        }
        save_db()

    user = db[uid]
    today = str(datetime.now().date())

    if user["date"] != today:
        user["date"] = today
        user["requests"] = DAILY_LIMIT
        save_db()

    return user

# ===== КНОПКИ =====

def sub_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Подписаться",
         url=f"https://t.me/{CHANNEL.replace('@','')}")],
        [InlineKeyboardButton("✅ Я подписался", callback_data="check")]
    ])

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚑ Флажки", callback_data="flags")],
        [InlineKeyboardButton("ℹ️ Информация", callback_data="info")],
        [InlineKeyboardButton("🎁 Реферальная система", callback_data="ref")]
    ])

def back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅ Назад", callback_data="back")]
    ])

# ===== ПРОВЕРКА ПОДПИСКИ =====

async def check_sub(user_id, context):
    try:
        m = await context.bot.get_chat_member(CHANNEL, user_id)
        return m.status in ["member", "administrator", "creator"]
    except:
        return False

# ===== START =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args

    user = get_user(uid)

    # рефералка
    if args:
        ref = args[0]
        if ref != str(uid) and user["invited_by"] is None:
            if ref in db:
                user["invited_by"] = ref
                db[ref]["requests"] += 1
                db[ref]["referrals"] += 1
                save_db()

    if not await check_sub(uid, context):
        await update.message.reply_text(
            "🚫 Подпишитесь на канал",
            reply_markup=sub_kb()
        )
        return

    await update.message.reply_text(
        "👋 Отправь username или username с флагами",
        reply_markup=main_kb()
    )

# ===== КНОПКИ =====

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    user = get_user(uid)

    if q.data == "check":
        if await check_sub(uid, context):
            await q.edit_message_text("✅ Подписка подтверждена", reply_markup=main_kb())
        else:
            await q.answer("❌ Не подписан", show_alert=True)

    elif q.data == "info":
        await q.edit_message_text(
            f"""
🤖 Бот ищет аккаунты через Maigret

📊 Осталось запросов: {user['requests']}
👥 Рефералы: {user['referrals']}

📢 Канал: {CHANNEL}
""",
            reply_markup=back_kb()
        )

    elif q.data == "ref":
        bot = await context.bot.get_me()
        link = f"https://t.me/{bot.username}?start={uid}"

        await q.edit_message_text(
            f"""
🎁 Реферальная система

+1 запрос за каждого пользователя

🔗 Ваша ссылка:
{link}

👥 Приглашено: {user['referrals']}
""",
            reply_markup=back_kb()
        )

    elif q.data == "flags":
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

    elif q.data == "back":
        await q.edit_message_text("Отправь username", reply_markup=main_kb())

# ===== ПАРСИНГ =====

def parse_output(text):
    links = []

    for line in text.splitlines():
        line = line.strip()

        if "[+]" in line and "http" in line:
            for part in line.split():
                if part.startswith("http"):
                    links.append(part)

        elif line.startswith("http"):
            links.append(line)

    return list(set(links))

# ===== ПОИСК =====

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if not await check_sub(uid, context):
        await update.message.reply_text("🚫 Подпишитесь", reply_markup=sub_kb())
        return

    now = asyncio.get_running_loop().time()

    if uid in last_request and now - last_request[uid] < ANTISPAM:
        await update.message.reply_text("⚠ Подожди пару секунд")
        return

    last_request[uid] = now

    user = get_user(uid)

    if user["requests"] <= 0:
        await update.message.reply_text("❌ Лимит исчерпан")
        return

    user["requests"] -= 1
    save_db()

    parts = text.split()
    username = parts[0]
    flags = parts[1:]

    msg = await update.message.reply_text("🔎 Поиск...")

    async with semaphore:
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

    if error.strip():
        await msg.edit_text(f"Ошибка:\n{error[:500]}")
        return

    links = parse_output(output)

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

    app = Application.builder().token(TOKEN).concurrent_updates(True).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))

    app.run_polling()

if __name__ == "__main__":
    main()
