# bot/main.py
from __future__ import annotations

import os
import logging
from urllib.parse import urlencode
from dotenv import load_dotenv

from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в .env (получить у @BotFather).")
if not WEBAPP_URL:
    raise RuntimeError(
        "WEBAPP_URL не задан в .env. Укажи публичный HTTPS URL на index.html "
        "(например: https://<site>.ngrok-free.app/index.html?api=https%3A%2F%2F<backend>.ngrok-free.app)"
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("tg_shop.bot")


def build_webapp_url() -> str:
    # WEBAPP_URL уже может содержать ?api=... — просто возвращаем как есть
    return WEBAPP_URL


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = build_webapp_url()

    # Нижняя большая кнопка (Reply Keyboard)
    reply_kb = ReplyKeyboardMarkup(
        [[KeyboardButton(text="🛍 Открыть магазин", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

    # Инлайн-кнопка над сообщением (дублируем)
    inline_kb = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton(text="Открыть магазин", web_app=WebAppInfo(url=url))
    )

    text = (
        "Привет! Это WebApp-магазин.\n\n"
        "Нажми кнопку ниже, чтобы открыть приложение.\n"
        "Если кнопка не появилась, обнови Telegram до последней версии."
    )
    await update.message.reply_text(text, reply_markup=reply_kb)
    await update.message.reply_text("Или нажми здесь:", reply_markup=inline_kb)


async def open_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Альтернативная команда /open — сразу присылает инлайн-кнопку."""
    url = build_webapp_url()
    inline_kb = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton(text="Открыть магазин", web_app=WebAppInfo(url=url))
    )
    await update.message.reply_text("Открыть магазин:", reply_markup=inline_kb)


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("open", open_cmd))
    log.info("🤖 Bot started")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
