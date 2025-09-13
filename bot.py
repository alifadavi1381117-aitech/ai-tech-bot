import os
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import feedparser
from deep_translator import GoogleTranslator

# logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tech-news-bot")

# env vars
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
PORT = int(os.getenv("PORT", "8000"))

if not BOT_TOKEN or not PUBLIC_URL:
    raise RuntimeError("Missing required env(s): BOT_TOKEN or PUBLIC_URL")

# init bot/dispatcher
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# RSS feeds
NEWS_FEED = "https://feeds.bbci.co.uk/news/technology/rss.xml"
AI_FEED = "https://techcrunch.com/category/artificial-intelligence/feed/"
IOT_FEED = "https://www.iotworldtoday.com/feed"

# ----------------- handlers -----------------
@dp.message(F.text == "/start")
async def start_cmd(msg: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 News", callback_data="news")
    kb.button(text="🤖 AI News", callback_data="ai")
    kb.button(text="🌐 IoT News", callback_data="iot")
    kb.adjust(2)
    await msg.answer("سلام! من ربات اخبار هستم، یکی از گزینه‌ها رو انتخاب کن:", reply_markup=kb.as_markup())

# ----------------- Fetch and show news -----------------
async def send_news(cq: types.CallbackQuery, feed_url: str, label: str):
    feed = feedparser.parse(feed_url)
    if not feed.entries:
        await cq.message.answer("❌ خبری پیدا نشد")
        return

    entry = feed.entries[0]  # اولین خبر
    text = f"🔹 <b>{entry.title}</b>\n{entry.summary}\n🔗 {entry.link}"

    kb = InlineKeyboardBuilder()
    kb.button(text="🇮🇷 فارسی", callback_data=f"translate:fa:{label}:{entry.link}")
    kb.button(text="🇬🇧 English", callback_data=f"translate:en:{label}:{entry.link}")
    kb.adjust(2)

    await cq.message.answer(text, reply_markup=kb.as_markup())
    await cq.answer()

@dp.callback_query(F.data == "news")
async def cb_news(cq: types.CallbackQuery):
    await send_news(cq, NEWS_FEED, "news")

@dp.callback_query(F.data == "ai")
async def cb_ai(cq: types.CallbackQuery):
    await send_news(cq, AI_FEED, "ai")

@dp.callback_query(F.data == "iot")
async def cb_iot(cq: types.CallbackQuery):
    await send_news(cq, IOT_FEED, "iot")

# ----------------- Translate -----------------
@dp.callback_query(F.data.startswith("translate"))
async def cb_translate(cq: types.CallbackQuery):
    _, lang, label, link = cq.data.split(":", 3)

    # انتخاب فید بر اساس label
    if label == "news":
        feed_url = NEWS_FEED
    elif label == "ai":
        feed_url = AI_FEED
    else:
        feed_url = IOT_FEED

    feed = feedparser.parse(feed_url)
    entry = next((e for e in feed.entries if e.link == link), None)
    if not entry:
        await cq.answer("❌ خبر پیدا نشد")
        return

    original = f"{entry.title}\n{entry.summary}"
    if lang == "fa":
        translated = GoogleTranslator(source="auto", target="fa").translate(original)
        await cq.message.answer(f"🇮🇷 {translated}\n\n🔗 {entry.link}")
    else:
        await cq.message.answer(f"🇬🇧 {original}\n\n🔗 {entry.link}")

    await cq.answer()

# ----------------- startup/cleanup -----------------
async def on_startup(app: web.Application):
    webhook_url = f"{PUBLIC_URL}/webhook"
    await bot.set_webhook(webhook_url, secret_token=WEBHOOK_SECRET)
    log.info(f"✅ Webhook set: {webhook_url}")

async def on_cleanup(app: web.Application):
    await bot.session.close()
    log.info("🧹 Session closed")

# ----------------- aiohttp app -----------------
def build_app() -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    from aiogram.webhook.aiohttp_server import SimpleRequestHandler
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path="/webhook")

    async def healthz(request: web.Request):
        return web.Response(text="healthy")

    app.router.add_get("/healthz", healthz)
    return app

# ----------------- run -----------------
if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
