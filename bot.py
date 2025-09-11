import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
PUBLIC_URL = (os.getenv("PUBLIC_URL") or "").strip()  # e.g. https://ai-tech-bot-or63.onrender.com
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set")
if not PUBLIC_URL:
    raise ValueError("❌ PUBLIC_URL not set (e.g. https://your-service.onrender.com)")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

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

# برای عیب‌یابی: هر پیامی رسید لاگ کنیم
@dp.message()
async def any_msg(m: types.Message):
    print(f"📥 Update from {m.from_user.id}: {m.text!r}")

# ---------- Webhook ----------
async def on_startup(app: web.Application):
    webhook_path = "/webhook"
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url=PUBLIC_URL + webhook_path)
    print("✅ Webhook set:", PUBLIC_URL + webhook_path)

async def on_cleanup(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()

def build_app() -> web.Application:
    app = web.Application()
    async def ok(_): return web.Response(text="OK")
    app.router.add_get("/", ok)

    webhook_path = "/webhook"
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=webhook_path)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    web.run_app(build_app(), host="0.0.0.0", port=port)
