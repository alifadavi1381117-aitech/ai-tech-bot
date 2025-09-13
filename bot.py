import os
import logging
import feedparser
import httpx
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# ---------------------------
# تنظیمات اولیه
# ---------------------------
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tech-news-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
PUBLIC_URL = os.getenv("PUBLIC_URL")  # آدرس پابلیک render
port = int(os.getenv("PORT", 10000))

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN در .env تعریف نشده!")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# ---------------------------
# RSS FEEDS
# ---------------------------
TECH_FEED = "https://feeds.arstechnica.com/arstechnica/technology-lab"
AI_FEED = "https://www.artificialintelligence-news.com/feed/"
IOT_FEED = "https://www.iot-now.com/feed/"

# ---------------------------
# کیبورد اصلی
# ---------------------------
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/start")]
    ],
    resize_keyboard=True
)

# ---------------------------
# توابع کمکی
# ---------------------------
def fetch_feed(url: str, limit: int = 3):
    feed = feedparser.parse(url)
    return feed.entries[:limit]

async def translate_text(text: str, target_lang: str = "fa"):
    api_url = "https://api.mymemory.translated.net/get"
    async with httpx.AsyncClient() as client:
        r = await client.get(api_url, params={"q": text, "langpair": f"en|{target_lang}"})
        data = r.json()
        return data.get("responseData", {}).get("translatedText", text)

async def fetch_python_codes(query="useful python snippets"):
    url = f"https://api.duckduckgo.com/?q={query}&format=json"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        data = r.json()
        results = []
        for topic in data.get("RelatedTopics", []):
            if "Text" in topic and "FirstURL" in topic:
                results.append(f"🔗 {topic['Text']}\n{topic['FirstURL']}")
        return results[:3] if results else ["❌ چیزی پیدا نشد."]

# ---------------------------
# ارسال خبر
# ---------------------------
async def send_news(cq: CallbackQuery, feed_url: str, tag: str):
    news = fetch_feed(feed_url)
    if not news:
        await cq.message.answer("❌ خبری پیدا نشد.", reply_markup=main_menu)
        return

    for entry in news:
        text = f"<b>{entry.title}</b>\n\n{entry.summary[:500]}...\n\n🔗 {entry.link}"
        kb = InlineKeyboardBuilder()
        kb.button(text="🇮🇷 فارسی", callback_data=f"tr:{tag}:fa:{entry.link}")
        kb.button(text="🇬🇧 English", callback_data=f"tr:{tag}:en:{entry.link}")
        await cq.message.answer(text, reply_markup=kb.as_markup())

# ---------------------------
# هندلرها
# ---------------------------
@dp.message(F.text == "/start")
async def start_cmd(msg: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 Tech News", callback_data="news")
    kb.button(text="🤖 AI News", callback_data="ai")
    kb.button(text="🌐 IoT News", callback_data="iot")
    kb.button(text="📚 کدهای مفید پایتون", callback_data="pycodes")
    kb.adjust(2)

    await msg.answer("سلام! یکی از گزینه‌ها رو انتخاب کن:", reply_markup=kb.as_markup())
    await msg.answer("برای برگشت به منو، /start رو بزن 👇", reply_markup=main_menu)

# اخبار
@dp.callback_query(F.data == "news")
async def cb_news(cq: CallbackQuery):
    await send_news(cq, TECH_FEED, "tech")

@dp.callback_query(F.data == "ai")
async def cb_ai(cq: CallbackQuery):
    await send_news(cq, AI_FEED, "ai")

@dp.callback_query(F.data == "iot")
async def cb_iot(cq: CallbackQuery):
    await send_news(cq, IOT_FEED, "iot")

# ترجمه
@dp.callback_query(F.data.startswith("tr:"))
async def cb_translate(cq: CallbackQuery):
    _, tag, lang, link = cq.data.split(":", 3)
    news = fetch_feed(
        TECH_FEED if tag == "tech" else AI_FEED if tag == "ai" else IOT_FEED
    )
    entry = next((e for e in news if e.link == link), None)
    if not entry:
        await cq.message.answer("❌ خبر پیدا نشد.", reply_markup=main_menu)
        return

    translated = await translate_text(entry.summary, target_lang=lang)
    await cq.message.answer(
        f"<b>{entry.title}</b>\n\n{translated}\n\n🔗 {entry.link}",
        reply_markup=main_menu
    )

# کدهای پایتون
@dp.callback_query(F.data == "pycodes")
async def cb_pycodes(cq: CallbackQuery):
    codes = await fetch_python_codes()
    for c in codes:
        await cq.message.answer(c, reply_markup=main_menu)

# ---------------------------
# وب‌هوک
# ---------------------------
async def on_startup(app: web.Application):
    missing = [var for var in ["WEBHOOK_SECRET", "PUBLIC_URL"] if not os.getenv(var)]
    if missing:
        raise RuntimeError(f"Missing required env(s): {', '.join(missing)}")

    webhook_url = f"{PUBLIC_URL}/webhook"
    await bot.set_webhook(webhook_url, secret_token=WEBHOOK_SECRET)
    logger.info(f"✅ Webhook set: {webhook_url}")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("🧹 Webhook deleted and session closed")

def build_app():
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    return app

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=port)
