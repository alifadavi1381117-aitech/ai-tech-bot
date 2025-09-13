import os
import logging
import feedparser
import httpx
from html import escape as html_escape
from aiohttp import web

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from deep_translator import GoogleTranslator
from selectolax.parser import HTMLParser

# ───────────────── Logging ─────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tech-news-bot")

# ───────────────── ENV / Bot ───────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")  # مثل: https://ai-tech-bot-docer.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN or not PUBLIC_URL:
    raise RuntimeError("Missing required env(s): BOT_TOKEN or PUBLIC_URL")

# به‌صورت صریح HTML، تا تلگرام MarkdownV2 برداشت نکند
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ───────────────── Feeds ───────────────────
TECH_FEED = "https://feeds.bbci.co.uk/news/technology/rss.xml"
AI_FEED   = "https://techcrunch.com/category/artificial-intelligence/feed/"
IOT_FEEDS = [
    "https://www.iot-now.com/feed/",
    "https://www.iotforall.com/feed/",
    "https://www.iotworldtoday.com/feed/",
    "https://iotbusinessnews.com/feed/",
]

# ───────────────── Helpers ─────────────────
def html_to_plain(html: str) -> str:
    """تبدیل HTML به متن ساده؛ حذف script/style و فاصله‌های اضافی"""
    if not html:
        return ""
    tree = HTMLParser(html)
    for n in tree.css("script, style"):
        n.decompose()
    text = tree.text(separator=" ").strip()
    return " ".join(text.split())

def escape_html(s: str, limit: int | None = None) -> str:
    """Escape امن برای parse_mode=HTML"""
    if not s:
        return ""
    s = html_escape(s)
    if limit and len(s) > limit:
        s = s[:limit] + "…"
    return s

def extract_entry_plain(entry) -> tuple[str, str, str]:
    title = getattr(entry, "title", "") or ""
    link  = getattr(entry, "link", "") or ""
    raw   = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    if not raw and hasattr(entry, "content") and entry.content:
        val = entry.content[0]
        raw = val.value if hasattr(val, "value") else str(val)
    summary = html_to_plain(raw)
    return title, summary, link

def pick_iot_feed() -> str | None:
    for url in IOT_FEEDS:
        feed = feedparser.parse(url)
        if getattr(feed, "entries", []):
            return url
    return None

async def fetch_html(url: str, timeout: float = 20.0) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (TechNewsBot/1.0)"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text

# ───────────────── Keyboards ───────────────
main_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="/start")]],
    resize_keyboard=True
)

def main_inline_markup():
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 Tech News", callback_data="news")
    kb.button(text="🤖 AI News", callback_data="ai")
    kb.button(text="🌐 IoT News", callback_data="iot")
    kb.button(text="📚 کدهای مفید پایتون", callback_data="pycodes")
    kb.adjust(2)
    return kb.as_markup()

# ───────────────── News Flow ───────────────
async def send_news(cq: types.CallbackQuery, feed_url: str, label: str):
    feed = feedparser.parse(feed_url)
    entries = getattr(feed, "entries", [])
    if not entries:
        await cq.message.answer("❌ خبری پیدا نشد.", reply_markup=main_menu)
        await cq.answer()
        return

    entry = entries[0]
    title, summary, link = extract_entry_plain(entry)

    safe_title = escape_html(title, 200)
    safe_sum   = escape_html(summary, 1800)
    safe_link  = escape_html(link, 1000)

    # متن HTML-safe
    text = f"📰 <b>{safe_title}</b>\n\n{safe_sum}\n\n🔗 <a href=\"{safe_link}\">{safe_link}</a>"

    kb = InlineKeyboardBuilder()
    kb.button(text="🇮🇷 فارسی", callback_data=f"t:{label}:fa")
    kb.button(text="🇬🇧 English", callback_data=f"t:{label}:en")
    kb.adjust(2)

    await cq.message.answer(text, reply_markup=kb.as_markup(), disable_web_page_preview=True)
    await cq.answer()

@dp.callback_query(F.data == "news")
async def cb_news(cq: types.CallbackQuery):
    await send_news(cq, TECH_FEED, "tech")

@dp.callback_query(F.data == "ai")
async def cb_ai(cq: types.CallbackQuery):
    await send_news(cq, AI_FEED, "ai")

@dp.callback_query(F.data == "iot")
async def cb_iot(cq: types.CallbackQuery):
    chosen = pick_iot_feed()
    if not chosen:
        await cq.message.answer("❌ خبر IoT پیدا نشد.", reply_markup=main_menu)
        await cq.answer()
        return
    await send_news(cq, chosen, "iot")

# ───────────────── Translate ───────────────
@dp.callback_query(F.data.startswith("t:"))
async def cb_translate(cq: types.CallbackQuery):
    try:
        _, label, lang = cq.data.split(":", 2)
    except Exception:
        await cq.answer("Bad payload"); return

    # فقط متن قابل‌مشاهده‌ی پیام فعلی را ترجمه می‌کنیم (بدون تگ‌ها)
    current_text = cq.message.html_text or cq.message.text or ""
    # حذف لینک پایانی برای ترجمه بهتر
    body = current_text.split("🔗")[0].strip()

    target = "fa" if lang == "fa" else "en"
    try:
        translated = GoogleTranslator(source="auto", target=target).translate(body)
    except Exception as e:
        log.warning(f"translate error: {e}")
        translated = body

    safe_trans = escape_html(translated, 2000)
    flag = "🇮🇷" if target == "fa" else "🇬🇧"
    await cq.message.answer(f"{flag} <pre>{safe_trans}</pre>", reply_markup=main_menu, disable_web_page_preview=True)
    await cq.answer()

# ───────────────── Python Snippet ──────────
PROGRAMIZ_PY_EXAMPLES = "https://www.programiz.com/python-programming/examples"

def extract_first_code_block(html: str) -> str | None:
    tree = HTMLParser(html)
    node = tree.css_first("pre, code")
    if node:
        txt = node.text(separator="\n").strip()
        return txt if len(txt) >= 8 else None
    return None

@dp.callback_query(F.data == "pycodes")
async def cb_pycodes(cq: types.CallbackQuery):
    try:
        html = await fetch_html(PROGRAMIZ_PY_EXAMPLES, timeout=20.0)
        code = extract_first_code_block(html)
        if code:
            code_safe = escape_html(code, 3500)
            await cq.message.answer(f"<b>📚 نمونه کد پایتون (Programiz):</b>\n<pre><code>{code_safe}</code></pre>",
                                    disable_web_page_preview=True)
            await cq.answer()
            return
    except Exception as e:
        log.warning(f"Programiz fetch failed: {e}")

    await cq.message.answer("❌ کدی پیدا نشد.", reply_markup=main_menu)
    await cq.answer()

# ───────────────── /start ──────────────────
@dp.message(F.text == "/start")
async def start_cmd(msg: types.Message):
    # این پیام هم با HTML ارسال می‌شود تا MarkdownV2 اعمال نشود
    await msg.answer(html_escape("سلام! یکی از گزینه‌ها رو انتخاب کن:"), reply_markup=main_inline_markup())
    await msg.answer(html_escape("🔄 برای برگشت به منوی اصلی /start رو بزن 👇"), reply_markup=main_menu)

# ───────────────── Webhook ────────────────
async def on_startup(app: web.Application):
    webhook_url = f"{PUBLIC_URL}/webhook"
    await bot.set_webhook(webhook_url, secret_token=WEBHOOK_SECRET)
    log.info(f"✅ Webhook set: {webhook_url}")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    log.info("🧹 Webhook deleted and session closed")

def build_app():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
