import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ========= НАСТРОЙКИ =========
TOKEN = ("8722347795:AAHkjvoZ0sAPZMb6wztkRI9YuDB-E8zoUKU")
CHANNEL_USERNAME = "@Data_Osinter"
ANTISPAM_SECONDS = 5
SEARCH_TIMEOUT = 600
MAX_CONCURRENT_SEARCHES = 3

# ========= ЛОГИ =========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========= ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =========
search_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)
user_last_request = {}

# ========= КНОПКИ =========

def subscribe_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Подписаться",
         url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}")],
        [InlineKeyboardButton("✅ Я подписался", callback_data="check_sub")]
    ])

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ℹ️ Информация", callback_data="info")]
    ])

def info_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Открыть канал",
         url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}")],
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

    if await check_subscription(user_id, context):
        await update.message.reply_text(
            "👋 Привет!\n\nОтправь username для поиска.",
            reply_markup=main_keyboard()
        )
    else:
        await update.message.reply_text(
            "🚫 Нужно подписаться на канал.",
            reply_markup=subscribe_keyboard()
        )

# ========= КНОПКИ =========

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "check_sub":
        if await check_subscription(user_id, context):
            await query.edit_message_text(
                "✅ Подписка подтверждена!\n\nТеперь отправь username.",
                reply_markup=main_keyboard()
            )
        else:
            await query.answer("❌ Вы не подписаны!", show_alert=True)

    elif query.data == "info":
        await query.edit_message_text(
            f"Бот ищет аккаунты через Maigret.\n\nКанал: {CHANNEL_USERNAME}",
            reply_markup=info_keyboard()
        )

    elif query.data == "back":
        await query.edit_message_text(
            "Отправь username для поиска.",
            reply_markup=main_keyboard()
        )

# ========= ПОИСК =========

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = asyncio.get_running_loop().time()

    if not await check_subscription(user_id, context):
        await update.message.reply_text(
            "🚫 Нужно подписаться.",
            reply_markup=subscribe_keyboard()
        )
        return

    if user_id in user_last_request and now - user_last_request[user_id] < ANTISPAM_SECONDS:
        await update.message.reply_text("⚠ Подожди несколько секунд.")
        return

    user_last_request[user_id] = now
    username = update.message.text.strip()

    if not username.replace("_", "").isalnum():
        await update.message.reply_text("❌ Некорректный username.")
        return

    msg = await update.message.reply_text(f"🔎 Ищу {username}...")

    async with search_semaphore:
        try:
            process = await asyncio.create_subprocess_exec(
                    "python", "-m", "maigret", username,
                    "--all",
                    "--with-domains",
                    "--top-sites", "2000",
                    "--no-progressbar",
                    "--timeout", "15",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                   )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=SEARCH_TIMEOUT
            )

        except asyncio.TimeoutError:
            process.kill()
            await msg.edit_text("⏱ Время вышло.")
            return

        except Exception as e:
            logger.error(e)
            await msg.edit_text("⚠ Ошибка поиска.")
            return

    result = stdout.decode(errors="ignore")
    links = [line for line in result.splitlines() if "http" in line]

    if not links:
        await msg.edit_text("❌ Ничего не найдено.")
        return

    filename = f"result_{username}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(links))

    await msg.edit_text("📁 Отправляю файл...")

    with open(filename, "rb") as f:
        await context.bot.send_document(chat_id=user_id, document=f)

    os.remove(filename)

# ========= ERROR =========

async def error_handler(update, context):
    logger.error(context.error)

# ========= MAIN =========

def main():
    if not TOKEN:
        raise RuntimeError("Установи BOT_TOKEN")

    app = Application.builder().token(TOKEN).concurrent_updates(True).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))
    app.add_error_handler(error_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
