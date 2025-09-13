import os
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import feedparser
from deep_translator import GoogleTranslator
import httpx
from selectolax.parser import HTMLParser

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tech-news-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
PORT = int(os.getenv("PORT", "8000"))

if not BOT_TOKEN or not PUBLIC_URL:
    raise RuntimeError("Missing required env(s): BOT_TOKEN or PUBLIC_URL")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

NEWS_FEED = "https://feeds.bbci.co.uk/news/technology/rss.xml"
AI_FEED   = "https://techcrunch.com/category/artificial-intelligence/feed/"
IOT_FEED  = "https://www.iotworldtoday.com/feed"


# -------------------- Helpers --------------------
def _feed_url_by_label(label: str) -> str:
    if label == "news": return NEWS_FEED
    if label == "ai":   return AI_FEED
    return IOT_FEED


# -------------------- Start Menu --------------------
@dp.message(F.text == "/start")
async def start_cmd(msg: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 News", callback_data="news")
    kb.button(text="🤖 AI News", callback_data="ai")
    kb.button(text="🌐 IoT News", callback_data="iot")
    kb.button(text="📚 کدهای مفید پایتون", callback_data="pycodes")
    kb.adjust(2)
    await msg.answer("سلام! یکی از گزینه‌ها رو انتخاب کن:", reply_markup=kb.as_markup())


# -------------------- News Section --------------------
async def send_news(cq: types.CallbackQuery, feed_url: str, label: str, index: int = 0):
    feed = feedparser.parse(feed_url)
    entries = getattr(feed, "entries", [])
    if not entries:
        await cq.message.answer("❌ خبری پیدا نشد")
        await cq.answer()
        return

    index = max(0, min(index, len(entries)-1))
    entry = entries[index]
    title   = getattr(entry, "title", "Untitled")
    summary = getattr(entry, "summary", "")
    link    = getattr(entry, "link", "")

    text = f"🔹 <b>{title}</b>\n{summary}\n🔗 {link}"
    cb = f"t:{label}:{index}"

    kb = InlineKeyboardBuilder()
    kb.button(text="🇮🇷 فارسی",   callback_data=f"{cb}:fa")
    kb.button(text="🇬🇧 English", callback_data=f"{cb}:en")
    kb.adjust(2)

    await cq.message.answer(text, reply_markup=kb.as_markup())
    await cq.answer()


@dp.callback_query(F.data == "news")
async def cb_news(cq: types.CallbackQuery): await send_news(cq, NEWS_FEED, "news")

@dp.callback_query(F.data == "ai")
async def cb_ai(cq: types.CallbackQuery):   await send_news(cq, AI_FEED, "ai")

@dp.callback_query(F.data == "iot")
async def cb_iot(cq: types.CallbackQuery):  await send_news(cq, IOT_FEED, "iot")


# -------------------- Translate Section --------------------
@dp.callback_query(F.data.startswith("t:"))
async def cb_translate(cq: types.CallbackQuery):
    try:
        _, label, idx_str, lang = cq.data.split(":", 3)
        index = int(idx_str)
    except Exception:
        await cq.answer("Bad payload"); return

    feed = feedparser.parse(_feed_url_by_label(label))
    entries = getattr(feed, "entries", [])
    if not entries or not (0 <= index < len(entries)):
        await cq.answer("❌ خبر پیدا نشد"); return

    entry = entries[index]
    title   = getattr(entry, "title", "")
    summary = getattr(entry, "summary", "")
    link    = getattr(entry, "link", "")
    original = f"{title}\n{summary}"

    if lang == "fa":
        translated = GoogleTranslator(source="auto", target="fa").translate(original)
        await cq.message.answer(f"🇮🇷 {translated}\n\n🔗 {link}")
    else:
        await cq.message.answer(f"🇬🇧 {original}\n\n🔗 {link}")

    await cq.answer()


# -------------------- Python Codes Section --------------------
async def fetch_python_snippet():
    url = "https://www.geeksforgeeks.org/python-programming-examples/"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, timeout=20.0)
    tree = HTMLParser(r.text)
    snippet_node = tree.css_first("pre")
    if snippet_node:
        return snippet_node.text()
    return "❌ کدی پیدا نشد."


@dp.callback_query(F.data == "pycodes")
async def cb_pycodes(cq: types.CallbackQuery):
    code = await fetch_python_snippet()
    # escape برای MarkdownV2
    safe_code = code.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
    await cq.message.answer(f"```python\n{safe_code}\n```", parse_mode="MarkdownV2")
    await cq.answer()


# -------------------- Webhook Section --------------------
async def on_startup(app: web.Application):
    webhook_url = f"{PUBLIC_URL}/webhook"
    await bot.set_webhook(webhook_url, secret_token=WEBHOOK_SECRET)
    log.info(f"✅ Webhook set: {webhook_url}")

async def on_cleanup(app: web.Application):
    await bot.session.close()
    log.info("🧹 Session closed")


def build_app() -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    from aiogram.webhook.aiohttp_server import SimpleRequestHandler
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path="/webhook")

    async def healthz(_): return web.Response(text="healthy")
    app.router.add_get("/healthz", healthz)

    return app


if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
