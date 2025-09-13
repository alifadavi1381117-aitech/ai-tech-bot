import os
import logging
import random
from html import escape as html_escape

import feedparser
import httpx
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
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
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ------------------ RSS FEEDS ------------------
AI_FEED = "https://cointelegraph.com/rss/tag/ai"
IOT_FEED = "https://iotbusinessnews.com/feed/"

# ------------------ ابزارهای کمکی ------------------
def clean_html(raw_html: str, limit: int | None = 1200) -> str:
    """حذف تگ‌ها و متن خالص با طول معقول برگرداندن"""
    tree = HTMLParser(raw_html or "")
    for n in tree.css("script,style"):
        n.decompose()
    text = tree.text(separator=" ").strip()
    text = " ".join(text.split())
    if limit and len(text) > limit:
        text = text[:limit] + "…"
    return text

async def fetch_html(url: str, timeout: float = 20.0) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (TechNewsBot/1.0)"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text

# ------------------ کیبورد اصلی ------------------
def main_inline_markup():
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 اخبار هوش مصنوعی", callback_data="ai_news")
    kb.button(text="📡 اخبار اینترنت اشیا", callback_data="iot_news")
    kb.button(text="🐍 کدهای آماده پایتون", callback_data="py_code")
    kb.adjust(2, 1)  # دو تا بالا، یکی پایین
    return kb.as_markup()

# ------------------ ترجمه متن ------------------
def translate_text(text: str, lang: str):
    try:
        return GoogleTranslator(source="auto", target=lang).translate(text)
    except Exception as e:
        logger.error(f"❌ Error in translate: {e}")
        return text

# ------------------ گرفتن خبر از RSS ------------------
def fetch_feed_entry(url: str):
    try:
        feed = feedparser.parse(url)
        if feed.entries:
            return random.choice(feed.entries)  # یکی تصادفی
    except Exception as e:
        logger.error(f"❌ Feed error: {e}")
    return None

# ------------------ گرفتن کد آماده ------------------
async def fetch_python_code():
    index_url = "https://www.programiz.com/python-programming/examples"
    try:
        # 1) جمع کردن لینک‌های مثال
        html = await fetch_html(index_url, timeout=25)
        tree = HTMLParser(html)
        links = []
        for a in tree.css("a"):
            href = a.attrs.get("href", "")
            if "/python-programming/examples/" in href:
                if href.startswith("/"):
                    href = "https://www.programiz.com" + href
                elif href.startswith("http"):
                    pass
                else:
                    href = "https://www.programiz.com/" + href
                links.append(href)
        links = list({x for x in links})  # یکتا

        if not links:
            return None

        # 2) یکی را انتخاب و وارد صفحه شده و کد را بخوان
        ex_url = random.choice(links)
        ex_html = await fetch_html(ex_url, timeout=25)
        t2 = HTMLParser(ex_html)
        node = t2.css_first("pre code") or t2.css_first("pre")
        if node:
            txt = node.text(separator="\n").strip()
            return txt if len(txt) >= 8 else None
    except Exception as e:
        logger.error(f"❌ Error fetching code: {e}")
    return None

# ------------------ ارسال خبر ------------------
async def send_news(cq: CallbackQuery, feed_url: str, tag: str):
    entry = fetch_feed_entry(feed_url)
    if not entry:
        await cq.message.answer("❌ خبری پیدا نشد، دوباره امتحان کن.")
        await cq.answer()
        return

    title = getattr(entry, "title", "") or "بدون عنوان"
    link = getattr(entry, "link", "") or ""
    raw_summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    summary = clean_html(raw_summary)

    # امن کردن بخش‌های HTML
    safe_title = html_escape(title)
    safe_link = html_escape(link)

    text = (
        f"<b>{safe_title}</b>\n\n"
        f"{summary}\n\n"
        f"🔗 <a href=\"{safe_link}\">{safe_link}</a>"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🇮🇷 فارسی", callback_data=f"tr_fa|{tag}")
    kb.button(text="🇬🇧 English", callback_data=f"tr_en|{tag}")
    kb.adjust(2)

    await cq.message.answer(text, reply_markup=kb.as_markup(), disable_web_page_preview=True)
    await cq.answer()

# ------------------ هندلرها ------------------
@dp.message(F.text == "/start")
async def start_cmd(msg: Message):
    await msg.answer(
        "سلام 🙂 یکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=main_inline_markup()
    )

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
        # برای تلگرام escape نیاز نیست داخل <pre><code>، ولی بهتره طول محدود کنیم
        safe = html_escape(code)
        await cq.message.answer(f"<b>نمونه کد پایتون:</b>\n\n<pre><code>{safe[:3500]}</code></pre>")
    else:
        await cq.message.answer("❌ کدی پیدا نشد.")
    await cq.answer()

@dp.callback_query(F.data.startswith("tr_"))
async def cb_translate(cq: CallbackQuery):
    # tr_fa|ai  یا tr_en|iot
    try:
        data = cq.data.split("|", 1)
        lang = "fa" if "fa" in data[0] else "en"
    except Exception:
        await cq.answer("payload نامعتبر")
        return

    # فقط تیتر و خلاصه را ترجمه کنیم (بدون لینک)
    original = (cq.message.html_text or cq.message.text or "")
    base = original.split("🔗")[0].strip()

    translated = translate_text(base, lang)
    # ترجمه را به صورت متن ساده می‌فرستیم که مشکل HTML نداشته باشد
    await cq.message.answer(translated[:3500], disable_web_page_preview=True)
    await cq.answer()

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
