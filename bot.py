# app.py
import os
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# ---------- Logging ----------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("tech-news-bot")

# ---------- Globals (lazy-validated) ----------
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
PUBLIC_URL = (os.getenv("PUBLIC_URL") or "").strip()  # e.g. https://your-app.onrender.com
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook").strip()
WEBHOOK_SECRET = (os.getenv("WEBHOOK_SECRET") or "").strip()  # generate a long random string

# Create bot/dispatcher objects; defer crash if token missing until startup
bot = Bot(token=BOT_TOKEN or "0", default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ---------- Handlers ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📰 News", callback_data="news")],
        [InlineKeyboardButton(text="🤖 AI News", callback_data="ai_news")],
        [InlineKeyboardButton(text="🔧 Python Code", callback_data="code")],
        [InlineKeyboardButton(text="📡 IoT", callback_data="iot_news")],
    ])
    try:
        await message.answer("سلام 👋\nمن ربات اخبار تکنولوژی و کدهای جذاب هستم.", reply_markup=kb)
    except Exception as e:
        log.exception("Failed to send /start response: %s", e)

@dp.callback_query(F.data == "news")
async def cb_news(cq: types.CallbackQuery):
    await cq.answer("آخرین اخبار تکنولوژی ✨", show_alert=False)
    await cq.message.answer("📰 آخرین اخبار تکنولوژی…")

@dp.callback_query(F.data == "ai_news")
async def cb_ai(cq: types.CallbackQuery):
    await cq.answer("هوش مصنوعی – به‌روز شد ✅", show_alert=False)
    await cq.message.answer("🤖 آخرین اخبار هوش مصنوعی…")

@dp.callback_query(F.data == "code")
async def cb_code(cq: types.CallbackQuery):
    await cq.answer("یک نمونه کد آماده شد 💻", show_alert=False)
    await cq.message.answer("🔧 یک کد جذاب پایتون:\n<code>print('Hello AI Bot!')</code>")

@dp.callback_query(F.data == "iot_news")
async def cb_iot(cq: types.CallbackQuery):
    await cq.answer("IoT به‌روز شد 📡", show_alert=False)
    await cq.message.answer("📡 اخبار اینترنت اشیاء…")

# Debug catch-all (keep lightweight)
@dp.message()
async def any_msg(m: types.Message):
    log.info("Update from %s: %r", m.from_user.id if m.from_user else "unknown", m.text)

# ---------- Web app / webhook ----------
async def on_startup(app: web.Application):
    # Validate envs here to avoid import-time crashes
    missing = []
    if not BOT_TOKEN: missing.append("BOT_TOKEN")
    if not PUBLIC_URL: missing.append("PUBLIC_URL")
    if not WEBHOOK_SECRET: missing.append("WEBHOOK_SECRET")
    if missing:
        raise RuntimeError(f"Missing required env(s): {', '.join(missing)}")

    # Set webhook with secret; drop old pending updates
    await bot.delete_webhook(drop_pending_updates=True)
    webhook_url = PUBLIC_URL.rstrip("/") + WEBHOOK_PATH
    await bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET)
    log.info("✅ Webhook set: %s", webhook_url)

async def on_cleanup(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    log.info("🧹 Webhook deleted and session closed")

def build_app() -> web.Application:
    app = web.Application()

    async def ok(_): return web.Response(text="OK")
    async def health(_): return web.Response(text="healthy")  # no Telegram calls

    app.router.add_get("/", ok)
    app.router.add_get("/healthz", health)

    # Register webhook handler with secret verification
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        # aiogram validates 'X-Telegram-Bot-Api-Secret-Token' header automatically
        secret_token=WEBHOOK_SECRET or None,
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    web.run_app(build_app(), host="0.0.0.0", port=port)
