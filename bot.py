import os
import logging
import re
import feedparser
import httpx
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from deep_translator import GoogleTranslator

# 🔹 لاگ‌ها
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tech-news-bot")

# 🔹 توکن
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN is missing")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# 🔹 Feeds
TECH_FEED = "https://feeds.bbci.co.uk/news/technology/rss.xml"
AI_FEED   = "https://www.artificialintelligence-news.com/feed/"
IOT_FEED  = "https://iotbusinessnews.com/feed/"

# ────────────── Helpers ──────────────
def clean_html(raw_html: str) -> str:
    """پاک کردن تگ‌های HTML غیرمجاز"""
    clean = re.sub(r"<.*?>", "", raw_html)
    return clean.strip()

async def fetch_python_codes():
    """کدهای پایتون از GeeksForGeeks"""
    url = "https://www.geeksforgeeks.org/python-programming-examples/"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            if r.status_code == 200:
                links = re.findall(r'href="(https://www\.geeksforgeeks\.org/[^"]+)"', r.text)
                titles = re.findall(r'>([^<]+)</a>', r.text)
                results = []
                for t, l in zip(titles, links):
                    if "python" in l:
                        results.append((t.strip(), l))
                return results[:5]
    except Exception as e:
        logger.error(f"Error fetching python codes: {e}")
    return []

async def send_news(cq: types.CallbackQuery, feed_url: str, prefix: str):
    feed = feedparser.parse(feed_url)
    if not feed.entries:
        await cq.message.answer("❌ چیزی پیدا نشد.")
        return

    entry = feed.entries[0]
    title = entry.title
    link = entry.link
    summary = clean_html(getattr(entry, "summary", ""))

    text = f"📰 <b>{title}</b>\n\n{summary}\n\n🔗 {link}"

    kb = InlineKeyboardBuilder()
    kb.button(text="🇮🇷 فارسی", callback_data=f"{prefix}_fa")
    kb.button(text="🇬🇧 English", callback_data=f"{prefix}_en")
    kb.adjust(2)

    await cq.message.answer(text, reply_markup=kb.as_markup())

# ────────────── Keyboards ──────────────
main_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="/start")]],
    resize_keyboard=True
)

def get_main_inline():
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 Tech News", callback_data="news")
    kb.button(text="🤖 AI News", callback_data="ai")
    kb.button(text="🌐 IoT News", callback_data="iot")
    kb.button(text="📚 کدهای مفید پایتون", callback_data="pycodes")
    kb.adjust(2)
    return kb.as_markup()

# ────────────── Handlers ──────────────
@dp.message(F.text == "/start")
async def start_cmd(msg: types.Message):
    await msg.answer(
        "سلام! یکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=get_main_inline()
    )
    await msg.answer(
        "🔄 برای برگشت به منوی اصلی /start رو بزن 👇",
        reply_markup=main_menu
    )

@dp.callback_query(F.data == "news")
async def cb_news(cq: types.CallbackQuery):
    await send_news(cq, TECH_FEED, "news")

@dp.callback_query(F.data == "ai")
async def cb_ai(cq: types.CallbackQuery):
    await send_news(cq, AI_FEED, "ai")

@dp.callback_query(F.data == "iot")
async def cb_iot(cq: types.CallbackQuery):
    await send_news(cq, IOT_FEED, "iot")

@dp.callback_query(F.data == "pycodes")
async def cb_codes(cq: types.CallbackQuery):
    codes = await fetch_python_codes()
    if not codes:
        await cq.message.answer("❌ هیچ کدی پیدا نشد.")
        return
    text = "📚 چند نمونه کد پایتون:\n\n"
    for title, link in codes:
        text += f"🔹 <a href='{link}'>{clean_html(title)}</a>\n"
    await cq.message.answer(text)

# ترجمه خبر
@dp.callback_query(F.data.endswith("_fa"))
async def cb_translate_fa(cq: types.CallbackQuery):
    original = cq.message.text
    translated = GoogleTranslator(source="auto", target="fa").translate(original)
    await cq.message.answer(f"🇮🇷 {translated}")

@dp.callback_query(F.data.endswith("_en"))
async def cb_translate_en(cq: types.CallbackQuery):
    original = cq.message.text
    translated = GoogleTranslator(source="auto", target="en").translate(original)
    await cq.message.answer(f"🇬🇧 {translated}")

# ────────────── Webhook ──────────────
async def on_startup(app: web.Application):
    public_url = os.getenv("PUBLIC_URL")
    if not public_url:
        raise RuntimeError("❌ Missing PUBLIC_URL")
    await bot.set_webhook(f"{public_url}/webhook")
    logger.info(f"✅ Webhook set: {public_url}/webhook")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("🧹 Webhook deleted and session closed")

def build_app():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    web.run_app(build_app(), host="0.0.0.0", port=port)
