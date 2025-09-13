import os
import logging
from html import unescape as html_unescape
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import feedparser
from deep_translator import GoogleTranslator
import httpx
from selectolax.parser import HTMLParser

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tech-news-bot")

# ---------- ENV ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")  # مثل: https://ai-tech-bot-docer.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
PORT = int(os.getenv("PORT", "8000"))

if not BOT_TOKEN or not PUBLIC_URL:
    raise RuntimeError("Missing required env(s): BOT_TOKEN or PUBLIC_URL")

# ---------- Bot / Dispatcher ----------
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# ---------- RSS feeds ----------
NEWS_FEED = "https://feeds.bbci.co.uk/news/technology/rss.xml"
AI_FEED   = "https://techcrunch.com/category/artificial-intelligence/feed/"
# چند منبع IoT
IOT_FEEDS = [
    "https://www.iot-now.com/feed/",
    "https://www.iotforall.com/feed/",
    "https://www.iotworldtoday.com/feed/",
]

# ---------- Helpers ----------
def clean_html_to_text(html: str) -> str:
    if not html:
        return ""
    tree = HTMLParser(html)
    for n in tree.css("script, style"):
        n.decompose()
    text = tree.text(separator=" ").strip()
    return " ".join(text.split())

def extract_entry(entry) -> tuple[str, str, str]:
    title = getattr(entry, "title", "") or ""
    link  = getattr(entry, "link", "") or ""
    raw = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    if not raw and hasattr(entry, "content") and entry.content:
        raw = entry.content[0].value if hasattr(entry.content[0], "value") else str(entry.content[0])
    summary = clean_html_to_text(html_unescape(raw))
    if len(summary) > 800:
        summary = summary[:800] + "…"
    return title, summary, link

def mdv2_escape(s: str) -> str:
    for ch in r"\_*[]()~`>#+-=|{}.!" :
        s = s.replace(ch, "\\" + ch)
    return s

async def fetch_html(url: str, timeout: float = 20.0) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (TechNewsBot/1.0)"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text

# ---------- Start Menu ----------
@dp.message(F.text == "/start")
async def start_cmd(msg: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 News", callback_data="news")
    kb.button(text="🤖 AI News", callback_data="ai")
    kb.button(text="🌐 IoT News", callback_data="iot")
    kb.button(text="📚 کدهای مفید پایتون", callback_data="pycodes")
    kb.adjust(2)
    await msg.answer("سلام! یکی از گزینه‌ها رو انتخاب کن:", reply_markup=kb.as_markup())

# ---------- News ----------
async def send_news(cq: types.CallbackQuery, feed_url: str, label: str, index: int = 0):
    feed = feedparser.parse(feed_url)
    entries = getattr(feed, "entries", [])
    if not entries:
        await cq.message.answer("❌ خبری پیدا نشد")
        await cq.answer()
        return

    index = max(0, min(index, len(entries) - 1))
    entry = entries[index]
    title, summary, link = extract_entry(entry)
    if not summary:
        summary = "—"

    text = f"🔹 <b>{title or 'Untitled'}</b>\n{summary}\n🔗 {link}"
    cb = f"t:{label}:{index}"

    kb = InlineKeyboardBuilder()
    kb.button(text="🇮🇷 فارسی", callback_data=f"{cb}:fa")
    kb.button(text="🇬🇧 English", callback_data=f"{cb}:en")
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
    chosen = None
    for url in IOT_FEEDS:
        feed = feedparser.parse(url)
        if getattr(feed, "entries", []):
            chosen = url
            break
    if not chosen:
        await cq.message.answer("❌ خبر IoT پیدا نشد.")
        await cq.answer()
        return
    await send_news(cq, chosen, "iot")

# ---------- Translate ----------
@dp.callback_query(F.data.startswith("t:"))
async def cb_translate(cq: types.CallbackQuery):
    try:
        _, label, idx_str, lang = cq.data.split(":", 3)
        index = int(idx_str)
    except Exception:
        await cq.answer("Bad payload"); return

    feed_url = None
    if label == "news":
        feed_url = NEWS_FEED
    elif label == "ai":
        feed_url = AI_FEED
    elif label == "iot":
        for url in IOT_FEEDS:
            feed = feedparser.parse(url)
            if getattr(feed, "entries", []):
                feed_url = url
                break

    if not feed_url:
        await cq.answer("❌ فید پیدا نشد"); return

    feed = feedparser.parse(feed_url)
    entries = getattr(feed, "entries", [])
    if not entries or not (0 <= index < len(entries)):
        await cq.answer("❌ خبر پیدا نشد"); return

    entry = entries[index]
    title, summary, link = extract_entry(entry)
    original = f"{title}\n{summary}"

    if lang == "fa":
        translated = GoogleTranslator(source="auto", target="fa").translate(original)
        await cq.message.answer(f"🇮🇷 {translated}\n\n🔗 {link}")
    else:
        await cq.message.answer(f"🇬🇧 {original}\n\n🔗 {link}")
    await cq.answer()

# ---------- Python Codes (Programiz) ----------
PROGRAMIZ_PY_EXAMPLES = "https://www.programiz.com/python-programming/examples"

def extract_first_code_block(html: str) -> str | None:
    tree = HTMLParser(html)
    node = tree.css_first("pre, code")
    if node:
        return node.text(separator="\n").strip() or None
    return None

async def fetch_python_snippet_from_web() -> str:
    try:
        html = await fetch_html(PROGRAMIZ_PY_EXAMPLES)
        code = extract_first_code_block(html)
        if code and len(code) >= 10:
            return code
    except Exception as e:
        log.warning(f"Programiz fetch failed: {e}")
    return "❌ کدی پیدا نشد."

@dp.callback_query(F.data == "pycodes")
async def cb_pycodes(cq: types.CallbackQuery):
    code = await fetch_python_snippet_from_web()
    safe = mdv2_escape(code)
    await cq.message.answer(f"```python\n{safe}\n```", parse_mode="MarkdownV2")
    await cq.answer()

# ---------- Webhook / App ----------
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
