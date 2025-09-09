from __future__ import annotations
import asyncio
import os
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv
import pytz

from aiogram.client.default import DefaultBotProperties

from feeds import FEEDS_GENERAL, FEEDS_AI, FEEDS_IOT_ROBOTICS, fetch_rss, format_items
from snippets import pick_code, code_to_text

# -------- Config --------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TZ = os.getenv("TZ", "Europe/Berlin")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not found. Put it in .env")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
rt = Router()
dp.include_router(rt)

# Ensure timezone exists (no-op if invalid)
try:
    pytz.timezone(TZ)
except Exception:
    TZ = "UTC"

# -------- UI --------
def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📰 اخبار تکنولوژی", callback_data="news"),
            InlineKeyboardButton(text="🤖 اخبار هوش مصنوعی", callback_data="ai_news"),
        ],
        [
            InlineKeyboardButton(text="🛰️ IoT/رباتیک", callback_data="iot_news"),
            InlineKeyboardButton(text="💻 کدهای کاربردی", callback_data="code"),
        ],
    ])

# -------- Handlers --------
@rt.message(CommandStart())
async def start(msg: Message):
    await msg.answer(
        "سلام! 👋 من ربات خبرهای داغ تکنولوژی/هوش‌مصنوعی و کدهای کاربردی پایتون/رباتیک/IoT هستم.\n"
        "از دکمه‌های زیر استفاده کن یا دستورات /help /news /ai_news /iot_news /code رو بزن.",
        reply_markup=main_kb()
    )

@rt.message(Command("help"))
async def help_cmd(msg: Message):
    await msg.answer(
        "دستورات موجود:\n"
        "/news — آخرین خبرهای تکنولوژی\n"
        "/ai_news — تازه‌های هوش مصنوعی\n"
        "/iot_news — خبرهای IoT/رباتیک\n"
        "/code — یک اسنیپت کد کاربردی (مثلاً: /code python یا /code iot)\n"
        "می‌تونی از دکمه‌ها هم استفاده کنی 👇",
        reply_markup=main_kb()
    )

@rt.message(Command("news"))
async def news_cmd(msg: Message):
    items = fetch_rss(FEEDS_GENERAL, limit=8)
    await msg.answer(format_items(items, "خبرهای تکنولوژی"))

@rt.message(Command("ai_news"))
async def ai_news_cmd(msg: Message):
    items = fetch_rss(FEEDS_AI, limit=8)
    await msg.answer(format_items(items, "تازه‌های هوش مصنوعی"))

@rt.message(Command("iot_news"))
async def iot_news_cmd(msg: Message):
    items = fetch_rss(FEEDS_IOT_ROBOTICS, limit=8)
    await msg.answer(format_items(items, "IoT و رباتیک"))

@rt.message(Command("code"))
async def code_cmd(msg: Message):
    parts = (msg.text or "").split()
    tag = parts[1].lower() if len(parts) > 1 else None
    sn = pick_code(tag)
    if not sn:
        await msg.answer("برای این تگ کدی ندارم. تگ‌های موجود: python, perf, async, network, robotics, sensors, iot, mqtt")
        return
    await msg.answer(code_to_text(sn))

# -------- Callback handlers (ACK fast; tolerate stale queries) --------
@rt.callback_query(F.data == "news")
async def cb_news(cq):
    try:
        await cq.answer()  # ACK فوری
    except TelegramBadRequest:
        return  # کوئری قدیمی: رها کن
    items = fetch_rss(FEEDS_GENERAL, limit=8)
    try:
        await cq.message.edit_text(format_items(items, "خبرهای تکنولوژی"), reply_markup=main_kb())
    except TelegramBadRequest:
        pass

@rt.callback_query(F.data == "ai_news")
async def cb_ai(cq):
    try:
        await cq.answer()
    except TelegramBadRequest:
        return
    items = fetch_rss(FEEDS_AI, limit=8)
    try:
        await cq.message.edit_text(format_items(items, "تازه‌های هوش مصنوعی"), reply_markup=main_kb())
    except TelegramBadRequest:
        pass

@rt.callback_query(F.data == "iot_news")
async def cb_iot(cq):
    try:
        await cq.answer()
    except TelegramBadRequest:
        return
    items = fetch_rss(FEEDS_IOT_ROBOTICS, limit=8)
    try:
        await cq.message.edit_text(format_items(items, "IoT و رباتیک"), reply_markup=main_kb())
    except TelegramBadRequest:
        pass

@rt.callback_query(F.data == "code")
async def cb_code(cq):
    try:
        await cq.answer()
    except TelegramBadRequest:
        return
    sn = pick_code(None)
    try:
        await cq.message.edit_text(code_to_text(sn), reply_markup=main_kb())
    except TelegramBadRequest:
        pass

# -------- Entry --------
async def main():
    print("Bot is running…")
    # 🔥 صف آپدیت‌های قدیمی را پاک کن تا Callbackهای کهنه خطا ندن
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
