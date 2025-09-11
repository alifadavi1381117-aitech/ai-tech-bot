import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")  # مثلا: https://ai-tech-bot-or63.onrender.com

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set")
if not PUBLIC_URL:
    raise ValueError("❌ PUBLIC_URL not set (e.g. https://your-service.onrender.com)")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ---------- handlers ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📰 News", callback_data="news")],
        [InlineKeyboardButton(text="🤖 AI News", callback_data="ai_news")],
        [InlineKeyboardButton(text="🔧 Python Code", callback_data="code")],
        [InlineKeyboardButton(text="📡 IoT", callback_data="iot_news")],
    ])
    await message.answer("سلام 👋\nمن ربات اخبار تکنولوژی و کدهای جذاب هستم.", reply_markup=kb)

@dp.callback_query(lambda cq: cq.data == "news")
async def cb_news(cq: types.CallbackQuery):
    await cq.message.answer("📰 آخرین اخبار تکنولوژی…")
    await cq.answer()

@dp.callback_query(lambda cq: cq.data == "ai_news")
async def cb_ai(cq: types.CallbackQuery):
    await cq.message.answer("🤖 آخرین اخبار هوش مصنوعی…")
    await cq.answer()

@dp.callback_query(lambda cq: cq.data == "code")
async def cb_code(cq: types.CallbackQuery):
    await cq.message.answer("🔧 یک کد جذاب پایتون:\n<code>print('Hello AI Bot!')</code>")
    await cq.answer()

@dp.callback_query(lambda cq: cq.data == "iot_news")
async def cb_iot(cq: types.CallbackQuery):
    await cq.message.answer("📡 اخبار اینترنت اشیاء…")
    await cq.answer()

# ---------- webhook app ----------
async def on_startup(app: web.Application):
    # حذف وبهوک قبلی و ست وبهوک جدید
    path = f"/webhook/{BOT_TOKEN}"
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url=PUBLIC_URL + path)
    print("✅ Webhook set:", PUBLIC_URL + path)

async def on_cleanup(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()

def build_app() -> web.Application:
    app = web.Application()
    # مسیر سلامت برای Render
    async def ok(_): return web.Response(text="OK")
    app.router.add_get("/", ok)

    # ثبت هندلر وبهوک
    webhook_path = f"/webhook/{BOT_TOKEN}"
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=webhook_path)
    setup_application(app, bot=bot)  # مدیریت lifecycle

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    web.run_app(build_app(), host="0.0.0.0", port=port)
