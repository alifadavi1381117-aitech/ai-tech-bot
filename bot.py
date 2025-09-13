import os
import logging
import random
import feedparser
import httpx
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from deep_translator import GoogleTranslator
from selectolax.parser import HTMLParser

# ------------------ تنظیمات لاگ ------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tech-news-bot")

# ------------------ لود env ------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "super-secret")
PUBLIC_URL = os.getenv("PUBLIC_URL")
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN در .env تعریف نشده است")
if not PUBLIC_URL:
    raise RuntimeError("❌ PUBLIC_URL در تنظیمات Render اضافه نشده است")

# ------------------ بات و دیسپچر ------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ------------------ RSS FEEDS ------------------
AI_FEED = "https://cointelegraph.com/rss/tag/ai"
IOT_FEED = "https://iotbusinessnews.com/feed/"

# ------------------ کیبورد اصلی ------------------
def main_inline_markup():
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 اخبار هوش مصنوعی", callback_data="ai_news")
    kb.button(text="📡 اخبار اینترنت اشیا", callback_data="iot_news")
    kb.button(text="🐍 کدهای آماده پایتون", callback_data="py_code")
    kb.adjust(1)
    return kb.as_markup()

# ------------------ ترجمه متن ------------------
def translate_text(text: str, lang: str):
    try:
        return GoogleTranslator(source="auto", target=lang).translate(text)
    except Exception as e:
        logger.error(f"❌ Error in translate: {e}")
        return text

# ------------------ گرفتن خبر از RSS ------------------
def fetch_feed(url: str):
    try:
        feed = feedparser.parse(url)
        if feed.entries:
            return random.choice(feed.entries)
    except Exception as e:
        logger.error(f"❌ Feed error: {e}")
    return None

# ------------------ گرفتن کد آماده ------------------
async def fetch_python_code():
    url = "https://www.programiz.com/python-programming/examples"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
        html = HTMLParser(r.text)
        codes = html.css("div.example pre")
        if codes:
            return random.choice(codes).text(strip=True)
    except Exception as e:
        logger.error(f"❌ Error fetching code: {e}")
    return None

# ------------------ ارسال خبر ------------------
async def send_news(cq: CallbackQuery, feed_url: str, tag: str):
    entry = fetch_feed(feed_url)
    if not entry:
        await cq.message.answer("❌ خبری پیدا نشد، دوباره امتحان کن.")
        return

    title = entry.get("title", "بدون عنوان")
    summary = entry.get("summary", "")
    link = entry.get("link", "")

    text = f"<b>{title}</b>\n\n{summary}\n\n<a href='{link}'>مطالعه کامل</a>"

    kb = InlineKeyboardBuilder()
    kb.button(text="🇮🇷 فارسی", callback_data=f"tr_fa|{tag}")
    kb.button(text="🇬🇧 English", callback_data=f"tr_en|{tag}")
    await cq.message.answer(text, reply_markup=kb.as_markup())

# ------------------ هندلرها ------------------
@dp.message(F.text == "/start")
async def start_cmd(msg: Message):
    await msg.answer("سلام 🙂 یکی از گزینه‌ها رو انتخاب کن:", reply_markup=main_inline_markup())

@dp.callback_query(F.data == "ai_news")
async def cb_ai(cq: CallbackQuery):
    await send_news(cq, AI_FEED, "ai")

@dp.callback_query(F.data == "iot_news")
async def cb_iot(cq: CallbackQuery):
    await send_news(cq, IOT_FEED, "iot")

@dp.callback_query(F.data == "py_code")
async def cb_py(cq: CallbackQuery):
    code = await fetch_python_code()
    if code:
        await cq.message.answer(f"<b>نمونه کد پایتون:</b>\n\n<pre><code>{code}</code></pre>")
    else:
        await cq.message.answer("❌ کدی پیدا نشد.")

@dp.callback_query(F.data.startswith("tr_"))
async def cb_translate(cq: CallbackQuery):
    data = cq.data.split("|")
    lang = "fa" if "fa" in data[0] else "en"
    original = cq.message.html_text

    translated = translate_text(original, lang)
    await cq.message.answer(translated)

# ------------------ استارتاپ / شات‌داون ------------------
async def on_startup(app: web.Application):
    await bot.set_webhook(f"{PUBLIC_URL}/webhook", secret_token=WEBHOOK_SECRET)
    logger.info(f"✅ Webhook set: {PUBLIC_URL}/webhook")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("🧹 Webhook deleted and session closed")

# ------------------ ساخت اپ aiohttp ------------------
def build_app():
    app = web.Application()

    async def root(request):
        return web.Response(text="ok", status=200)

    app.router.add_get("/", root)

    # ثبت وبهوک با SimpleRequestHandler
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET
    ).register(app, path="/webhook")

    # یکپارچه سازی دیسپچر و اپ
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app

# ------------------ اجرای اصلی ------------------
if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
