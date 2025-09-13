import os
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import feedparser
from deep_translator import GoogleTranslator

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tech-news-bot")

# ---------- ENV ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")  # مثلا: https://ai-tech-bot-docer.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
PORT = int(os.getenv("PORT", "8000"))

if not BOT_TOKEN or not PUBLIC_URL:
    raise RuntimeError("Missing required env(s): BOT_TOKEN or PUBLIC_URL")

# ---------- Bot / Dispatcher ----------
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)  # aiogram 3.7+
)
dp = Dispatcher()

# ---------- RSS feeds ----------
NEWS_FEED = "https://feeds.bbci.co.uk/news/technology/rss.xml"
AI_FEED = "https://techcrunch.com/category/artificial-intelligence/feed/"
IOT_FEED = "https://www.iotworldtoday.com/feed"

# ---------- /start ----------
@dp.message(F.text == "/start")
async def start_cmd(msg: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 News", callback_data="news")
    kb.button(text="🤖 AI News", callback_data="ai")
    kb.button(text="🌐 IoT News", callback_data="iot")
    kb.adjust(2)
    await msg.answer("سلام! یکی از گزینه‌ها رو انتخاب کن:", reply_markup=kb.as_markup())

# ---------- helper: send one news item ----------
async def send_news(cq: types.CallbackQuery, feed_url: str, label: str):
    feed = feedparser.parse(feed_url)
    if not getattr(feed, "entries", None):
        await cq.message.answer("❌ خبری پیدا نشد")
        await cq.answer()
        return

    entry = feed.entries[0]  # اولین خبر
    title = getattr(entry, "title", "Untitled")
    summary = getattr(entry, "summary", "")
    link = getattr(entry, "link", "")

    text = f"🔹 <b>{title}</b>\n{summary}\n🔗 {link}"

    kb = InlineKeyboardBuilder()
    kb.button(text="🇮🇷 فارسی", callback_data=f"translate:fa:{label}:{link}")
    kb.button(text="🇬🇧 English", callback_data=f"translate:en:{label}:{link}")
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

# ---------- translate ----------
@dp.callback_query(F.data.startswith("translate"))
async def cb_translate(cq: types.CallbackQuery):
    try:
        _, lang, label, link = cq.data.split(":", 3)
    except ValueError:
        await cq.answer("Bad payload", show_alert=False)
        return

    feed_url = NEWS_FEED if label == "news" else AI_FEED if label == "ai" else IOT_FEED
    feed = feedparser.parse(feed_url)
    entry = next((e for e in feed.entries if getattr(e, "link", "") == link), None)
    if not entry:
        await cq.answer("❌ خبر پیدا نشد")
        return

    original = f"{getattr(entry,'title','')}\n{getattr(entry,'summary','')}"
    if lang == "fa":
        translated = GoogleTranslator(source="auto", target="fa").translate(original)
        await cq.message.answer(f"🇮🇷 {translated}\n\n🔗 {link}")
    else:
        await cq.message.answer(f"🇬🇧 {original}\n\n🔗 {link}")

    await cq.answer()

# ---------- lifecycle ----------
async def on_startup(app: web.Application):
    webhook_url = f"{PUBLIC_URL}/webhook"
    await bot.set_webhook(webhook_url, secret_token=WEBHOOK_SECRET)
    log.info(f"✅ Webhook set: {webhook_url}")

async def on_cleanup(app: web.Application):
    # مهم: وبهوک را حذف نمی‌کنیم
    await bot.session.close()
    log.info("🧹 Session closed")

# ---------- aiohttp app ----------
def build_app() -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    from aiogram.webhook.aiohttp_server import SimpleRequestHandler
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path="/webhook")

    async def healthz(_request: web.Request):
        return web.Response(text="healthy")

    app.router.add_get("/healthz", healthz)
    return app

# ---------- run ----------
if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
