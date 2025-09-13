import os
import logging
import random
import feedparser
import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiohttp import web
from deep_translator import GoogleTranslator
from selectolax.parser import HTMLParser

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tech-news-bot")

# ---------------- Config ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mysecret")
PUBLIC_URL = os.getenv("PUBLIC_URL")
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing!")

if not PUBLIC_URL:
    raise RuntimeError("PUBLIC_URL is missing!")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ---------------- Feeds ----------------
AI_FEED = "https://feeds.feedburner.com/TechCrunch/artificial-intelligence"
IOT_FEED = "https://www.iotforall.com/feed"

# Python examples scraping
PYTHON_EXAMPLES_URL = "https://www.programiz.com/python-programming/examples"

# ---------------- Keyboards ----------------
def main_inline_markup():
    kb = [
        [InlineKeyboardButton(text="📰 اخبار AI", callback_data="ai_news")],
        [InlineKeyboardButton(text="🌐 اخبار IoT", callback_data="iot_news")],
        [InlineKeyboardButton(text="🐍 کدهای مفید پایتون", callback_data="py_codes")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def translate_markup(category: str, idx: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇮🇷 فارسی", callback_data=f"tr:{category}:{idx}:fa"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data=f"tr:{category}:{idx}:en")
        ]
    ])

# ---------------- Helpers ----------------
def parse_feed(feed_url: str):
    d = feedparser.parse(feed_url)
    items = []
    for e in d.entries[:5]:
        desc = e.get("summary", "").replace("\n", " ").strip()
        clean_desc = desc.replace("<p>", "").replace("</p>", "").replace("<br>", " ")
        items.append({
            "title": e.title,
            "desc": clean_desc,
            "link": e.link
        })
    return items

async def scrape_python_examples():
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(PYTHON_EXAMPLES_URL)
    html = HTMLParser(r.text)
    links = html.css("a")
    examples = []
    for a in links:
        href = a.attrs.get("href", "")
        text = a.text(strip=True)
        if "/python-programming/examples/" in href and text:
            examples.append((text, f"https://www.programiz.com{href}"))
    return examples

# ---------------- Handlers ----------------
@router.message(Command("start"))
async def start_cmd(msg: Message):
    await msg.answer(
        "سلام 👋 یکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=main_inline_markup()
    )

@router.callback_query(F.data == "ai_news")
async def cb_ai(cq: CallbackQuery):
    await send_news(cq, AI_FEED, "ai")

@router.callback_query(F.data == "iot_news")
async def cb_iot(cq: CallbackQuery):
    await send_news(cq, IOT_FEED, "iot")

async def send_news(cq: CallbackQuery, feed_url: str, category: str):
    items = parse_feed(feed_url)
    if not items:
        await cq.message.answer("❌ خبری پیدا نشد.")
        return
    item = random.choice(items)  # یک خبر تصادفی
    text = f"<b>{item['title']}</b>\n\n{item['desc']}\n\n🔗 {item['link']}"
    await cq.message.answer(text, reply_markup=translate_markup(category, items.index(item)))
    await cq.answer()

@router.callback_query(F.data == "py_codes")
async def cb_py(cq: CallbackQuery):
    examples = await scrape_python_examples()
    if not examples:
        await cq.message.answer("❌ کدی پیدا نشد.")
        return
    example = random.choice(examples)
    text = f"🐍 <b>{example[0]}</b>\n🔗 {example[1]}"
    await cq.message.answer(text)
    await cq.answer()

@router.callback_query(F.data.startswith("tr:"))
async def cb_translate(cq: CallbackQuery):
    _, category, idx, lang = cq.data.split(":")
    feed_url = AI_FEED if category == "ai" else IOT_FEED
    items = parse_feed(feed_url)
    idx = int(idx)
    if idx >= len(items):
        await cq.answer("❌ مورد نامعتبر.")
        return
    item = items[idx]
    text = f"{item['title']}\n\n{item['desc']}"
    try:
        translated = GoogleTranslator(source="auto", target=lang).translate(text)
    except Exception as e:
        translated = f"⚠️ خطا در ترجمه: {e}"
    await cq.message.answer(translated)
    await cq.answer()

# ---------------- Webhook ----------------
async def on_startup(app):
    webhook_url = f"{PUBLIC_URL}/webhook"
    await bot.set_webhook(webhook_url, secret_token=WEBHOOK_SECRET)
    logger.info(f"✅ Webhook set: {webhook_url}")

async def on_shutdown(app):
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("🧹 Webhook deleted and session closed")

def build_app():
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    # Root route (200 OK)
    async def root(request):
        return web.Response(text="ok", status=200)

    app.router.add_get("/", root)
    app.router.add_post("/webhook", dp.middleware.webhook_handler(secret_token=WEBHOOK_SECRET))
    return app

# ---------------- Run ----------------
if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
