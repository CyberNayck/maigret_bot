import os
import json
import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = ("8722347795:AAHkjvoZ0sAPZMb6wztkRI9YuDB-E8zoUKU")
CHANNEL_USERNAME = "@Data_Osinter"

DAILY_LIMIT = 3
SEARCH_TIMEOUT = 600
MAX_CONCURRENT_SEARCHES = 3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

search_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)

DB_FILE = "users.json"


# ========= DATABASE =========

def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r") as f:
        return json.load(f)


def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f)


db = load_db()


def get_user(user_id):

    uid = str(user_id)

    if uid not in db:
        db[uid] = {
            "requests": DAILY_LIMIT,
            "date": str(datetime.now().date()),
            "referrals": 0,
            "invited_by": None
        }
        save_db(db)

    user = db[uid]

    today = str(datetime.now().date())

    if user["date"] != today:
        user["date"] = today
        user["requests"] = DAILY_LIMIT
        save_db(db)

    return user


# ========= КНОПКИ =========

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ℹ️ Информация", callback_data="info")],
        [InlineKeyboardButton("🎁 Реферальная помощь", callback_data="ref")]
    ])


def info_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Открыть канал",
         url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ])


def ref_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ])


# ========= ПРОВЕРКА ПОДПИСКИ =========

async def check_subscription(user_id, context):
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False


# ========= START =========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    args = context.args

    user = get_user(user_id)

    if args:

        ref_id = args[0]

        if ref_id != str(user_id) and user["invited_by"] is None:

            if ref_id in db:
                user["invited_by"] = ref_id
                db[ref_id]["requests"] += 1
                db[ref_id]["referrals"] += 1
                save_db(db)

    await update.message.reply_text(
        "👋 Отправь username для поиска.",
        reply_markup=main_keyboard()
    )


# ========= КНОПКИ =========

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "info":

        user = get_user(user_id)

        await query.edit_message_text(
            f"""
🤖 Бот ищет аккаунты через Maigret

📊 Осталось запросов: {user['requests']}
👥 Рефералов: {user['referrals']}

📢 Канал: {CHANNEL_USERNAME}
""",
            reply_markup=info_keyboard()
        )

    elif query.data == "ref":

        bot_username = (await context.bot.get_me()).username

        ref_link = f"https://t.me/{bot_username}?start={user_id}"

        user = get_user(user_id)

        await query.edit_message_text(
            f"""
🎁 Реферальная программа

Приглашай друзей и получай +1 поиск.

Твоя ссылка:

{ref_link}

👥 Приглашено: {user['referrals']}
""",
            reply_markup=ref_keyboard()
        )

    elif query.data == "back":

        await query.edit_message_text(
            "Отправь username для поиска",
            reply_markup=main_keyboard()
        )


# ========= ПОИСК =========

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    username = update.message.text.strip()

    if not await check_subscription(user_id, context):

        await update.message.reply_text("Подпишись на канал")
        return

    user = get_user(user_id)

    if user["requests"] <= 0:

        await update.message.reply_text(
            "❌ Лимит запросов на сегодня исчерпан.\n\n"
            "Приглашай друзей через реферальную программу."
        )
        return

    user["requests"] -= 1
    save_db(db)

    msg = await update.message.reply_text("🔎 Поиск...")

    async with search_semaphore:

        try:

            process = await asyncio.create_subprocess_exec(
                "python", "-m", "maigret", username,
                "--all",
                "--with-domains",
                "--top-sites", "2000",
                "--no-progressbar",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=SEARCH_TIMEOUT
            )

        except asyncio.TimeoutError:

            process.kill()
            await msg.edit_text("⏱ Время вышло")
            return

    result = stdout.decode(errors="ignore")

    links = [line for line in result.splitlines() if "http" in line]

    if not links:

        await msg.edit_text("Ничего не найдено")
        return

    filename = f"result_{username}.txt"

    with open(filename, "w") as f:
        f.write("\n".join(links))

    await context.bot.send_document(
        chat_id=user_id,
        document=open(filename, "rb")
    )

    os.remove(filename)

    await msg.delete()


# ========= MAIN =========

def main():

    app = Application.builder().token(TOKEN).concurrent_updates(True).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))

    app.run_polling()


if __name__ == "__main__":
    main()
