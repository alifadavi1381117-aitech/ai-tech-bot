import os
import logging
import feedparser
import httpx
from aiohttp import web

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties  # kept for compatibility if you want later
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
PUBLIC_URL = os.getenv("PUBLIC_URL")  # e.g. https://your-service.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN or not PUBLIC_URL:
    raise RuntimeError("Missing required env(s): BOT_TOKEN or PUBLIC_URL")

# Use plain text by default; avoid MarkdownV2 auto-parsing issues on feed text
bot = Bot(token=BOT_TOKEN)  # no default parse_mode
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
    if not html:
        return ""
    tree = HTMLParser(html)
    for n in tree.css("script, style"):
        n.decompose()
    text = tree.text(separator=" ").strip()
    return " ".join(text.split())

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
        try:
            feed = feedparser.parse(url)
            if getattr(feed, "entries", []):
                return url
        except Exception as e:
            log.warning(f"IoT feed parse failed for {url}: {e}")
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
    kb.button(text="📚 Python codes", callback_data="pycodes")
    kb.adjust(2)
    return kb.as_markup()

# ───────────────── News Flow ───────────────
async def send_news(cq: types.CallbackQuery, feed_url: str, label: str):
    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        log.warning(f"Feed parse error for {feed_url}: {e}")
        await cq.message.answer("❌ خطا در دریافت خبر.", reply_markup=main_menu)
        await cq.answer()
        return

    entries = getattr(feed, "entries", [])
    if not entries:
        await cq.message.answer("❌ خبری پیدا نشد.", reply_markup=main_menu)
        await cq.answer()
        return

    entry = entries[0]
    title, summary, link = extract_entry_plain(entry)
    text = f"📰 {title}\n\n{summary}\n\n🔗 {link}"

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
        await cq.answer("Bad payload")
        return

    body = cq.message.text or ""
    target = "fa" if lang == "fa" else "en"
    try:
        translated = GoogleTranslator(source="auto", target=target).translate(body)
    except Exception as e:
        log.warning(f"translate error: {e}")
        translated = body

    flag = "🇮🇷" if target == "fa" else "🇬🇧"
    await cq.message.answer(f"{flag} {translated}", reply_markup=main_menu, disable_web_page_preview=True)
    await cq.answer()

# ───────────────── Python Snippet ──────────
PROGRAMIZ_PY_EXAMPLES = "https://www.programiz.com/python-programming/examples"

def extract_first_code_block(html: str) -> str | None:
    tree = HTMLParser(html)
    # prefer <pre><code> if exists
    node = tree.css_first("pre code") or tree.css_first("pre, code")
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
            if len(code) > 3500:
                code = code[:3500] + "…"
            # Explicit Markdown code fence for this message only
            await cq.message.answer(
                f"📚 نمونه کد پایتون (Programiz):\n\n```python\n{code}\n```",
                disable_web_page_preview=True
            )
            await cq.answer()
            return
    except Exception as e:
        log.warning(f"Programiz fetch failed: {e}")

    await cq.message.answer("❌ کدی پیدا نشد.", reply_markup=main_menu)
    await cq.answer()

# ───────────────── /start ──────────────────
@dp.message(F.text.startswith("/start"))
async def start_cmd(msg: types.Message):
    await msg.answer("سلام! یکی از گزینه‌ها رو انتخاب کن:", reply_markup=main_inline_markup())
    await msg.answer("🔄 برای برگشت به منوی اصلی /start رو بزن 👇", reply_markup=main_menu)

# ───────────────── Webhook / Health ─────────
async def on_startup(app: web.Application):
    webhook_url = f"{PUBLIC_URL}/webhook"
    await bot.set_webhook(webhook_url, secret_token=WEBHOOK_SECRET)
    log.info(f"✅ Webhook set: {webhook_url}")

async def on_shutdown(app: web.Application):
    try:
        await bot.delete_webhook()
    except Exception as e:
        log.warning(f"Webhook delete error: {e}")
    try:
        await bot.session.close()
    except Exception as e:
        log.warning(f"Bot session close error: {e}")
    log.info("🧹 Webhook deleted and session closed")

def build_app():
    app = web.Application()

    # Webhook
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    # Health / index endpoints (Render hits "/")
    async def index(request):
        return web.Response(text="OK")
    async def health(request):
        return web.Response(text="OK")

    app.router.add_get("/", index)      # HEAD auto-registered; don't add add_head
    app.router.add_get("/health", health)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
