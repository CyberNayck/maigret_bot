import os
import json
import asyncio
import logging
from datetime import datetime
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ===== НАСТРОЙКИ =====

TOKEN = ("8722347795:AAHkjvoZ0sAPZMb6wztkRI9YuDB-E8zoUKU")
CHANNEL = "@Data_Osinter"

DAILY_LIMIT = 3
SEARCH_TIMEOUT = 600
MAX_CONCURRENT = 3
ANTISPAM = 5

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
            await q.edit_message_text(
                "✅ Подписка подтверждена",
                reply_markup=main_kb()
            )
        else:
            await q.answer("❌ Не подписан", show_alert=True)

    elif q.data == "info":

        await q.edit_message_text(
            f"""
🤖 Поиск через Maigret

📊 Осталось: {user['requests']}
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

+1 поиск за человека

🔗 {link}

👥 Приглашено: {user['referrals']}
""",
            reply_markup=back_kb()
        )

    elif q.data == "flags":

        await q.edit_message_text(
            """
⚑ Флажки Maigret:

--all → искать везде  
--top-sites 2000 → глубоко  
--timeout 5 → быстрее  
--retries 0 → без повторов  
--proxy URL → прокси  
--tor → через TOR  
--with-domains → домены  

📌 Пример:
username --proxy http://127.0.0.1:8080
""",
            reply_markup=back_kb()
        )

    elif q.data == "back":

        await q.edit_message_text(
            "Отправь username",
            reply_markup=main_kb()
        )


# ===== ПОИСК =====

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.effective_user.id
    text = update.message.text.strip()

    if not await check_sub(uid, context):
        await update.message.reply_text(
            "🚫 Подпишись на канал",
            reply_markup=sub_kb()
        )
        return

    now = asyncio.get_running_loop().time()

    if uid in last_request and now - last_request[uid] < ANTISPAM:
        await update.message.reply_text("⚠ Подожди")
        return

    last_request[uid] = now

    user = get_user(uid)

    if user["requests"] <= 0:
        await update.message.reply_text(
            "❌ Лимит исчерпан\n\nПриглашай друзей"
        )
        return

    parts = text.split()

    username = parts[0]
    flags = parts[1:]

    user["requests"] -= 1
    save_db()

    msg = await update.message.reply_text("🔎 Поиск...")

    async with semaphore:

        try:

            args = [
                "python3", "-m", "maigret", username,
                "--top-sites", "2000",
                "--workers", "50",
                "--no-progressbar",
                "--no-color"
            ]

            # добавляем пользовательские флаги
            args += flags

            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=SEARCH_TIMEOUT
            )

        except asyncio.TimeoutError:
            process.kill()
            await msg.edit_text("⏱ Таймаут")
            return

    result = stdout.decode(errors="ignore")

    links = [l for l in result.splitlines() if "http" in l]

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
