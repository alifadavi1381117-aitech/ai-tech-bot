import os
import asyncio
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# گرفتن توکن از Environment
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN is not set in environment variables.")

# تنظیم Bot و Dispatcher
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# ================== وب‌سرور برای Render ==================
async def start_http_server():
    app = web.Application()

    async def ok(_):
        return web.Response(text="OK")

    app.router.add_get("/", ok)
    port = int(os.getenv("PORT", "8000"))  # Render متغیر PORT رو ست می‌کنه
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    print(f"✅ HTTP server is listening on 0.0.0.0:{port}")

# ================== هندلرها ==================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📰 News", callback_data="news")],
            [InlineKeyboardButton(text="🤖 AI News", callback_data="ai_news")],
            [InlineKeyboardButton(text="🔧 Python Code", callback_data="code")],
            [InlineKeyboardButton(text="📡 IoT", callback_data="iot_news")]
        ]
    )
    await message.answer("سلام 👋\nمن ربات اخبار تکنولوژی و کدهای جذاب هستم.", reply_markup=keyboard)

@dp.callback_query(lambda cq: cq.data == "news")
async def cb_news(cq: types.CallbackQuery):
    await cq.message.answer("📰 آخرین اخبار تکنولوژی...")
    await cq.answer()

@dp.callback_query(lambda cq: cq.data == "ai_news")
async def cb_ai_news(cq: types.CallbackQuery):
    await cq.message.answer("🤖 آخرین اخبار هوش مصنوعی...")
    await cq.answer()

@dp.callback_query(lambda cq: cq.data == "code")
async def cb_code(cq: types.CallbackQuery):
    await cq.message.answer("🔧 یک کد جذاب پایتون:")
    await cq.message.answer("```python\nprint('Hello AI Bot!')\n```")
    await cq.answer()

@dp.callback_query(lambda cq: cq.data == "iot_news")
async def cb_iot(cq: types.CallbackQuery):
    await cq.message.answer("📡 اخبار اینترنت اشیاء...")
    await cq.answer()

# ================== main ==================
async def main():
    # پاک کردن آپدیت‌های قدیمی
    await bot.delete_webhook(drop_pending_updates=True)

    # استارت وب‌سرور برای health check
    asyncio.create_task(start_http_server())

    print("🤖 Bot is running…")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
