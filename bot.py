#!/usr/bin/env python3
# bot.py — Tech News Bot (async-safe, safer translate & parsing)

import os
import io
import asyncio
import logging
from typing import Optional, Tuple

import feedparser
import httpx
from aiohttp import web

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from deep_translator import GoogleTranslator
from selectolax.parser import HTMLParser

# ───────────────── Logging ─────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tech-news-bot")

# ───────────────── ENV / Bot ───────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")  # e.g. https://your-service.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN or not PUBLIC_URL:
    raise RuntimeError("Missing required env(s): BOT_TOKEN or PUBLIC_URL")

# default: no parse_mode globally to avoid Telegram HTML parsing errors
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
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

# ───────────────── HTTP helper ─────────────
async def fetch_html(url: str, timeout: float = 20.0) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (TechNewsBot/1.0)"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text

# ───────────────── Sync -> Async wrappers ──
async def parse_feed_async(url: str):
    """Run feedparser.parse in threadpool (it's sync)."""
    return await asyncio.to_thread(feedparser.parse, url)

async def html_to_plain_async(html: str) -> str:
    """Convert HTML to plain text using selectolax in threadpool."""
    if not html:
        return ""
    def _convert(h: str) -> str:
        tree = HTMLParser(h)
        for n in tree.css("script, style"):
            n.decompose()
        text = tree.text(separator=" ").strip()
        return " ".join(text.split())
    return await asyncio.to_thread(_convert, html)

async def extract_entry_plain_async(entry) -> Tuple[str, str, str]:
    title = getattr(entry, "title", "") or ""
    link  = getattr(entry, "link", "") or ""
    raw   = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    if not raw and hasattr(entry, "content") and entry.content:
        val = entry.content[0]
        raw = val.value if hasattr(val, "value") else str(val)
    summary = await html_to_plain_async(raw)
    return title, summary, link

async def pick_iot_feed_async() -> Optional[str]:
    for url in IOT_FEEDS:
        try:
            feed = await parse_feed_async(url)
            if getattr(feed, "entries", []):
                return url
        except Exception as e:
            log.debug("IoT feed check failed for %s: %s", url, e)
    return None

async def translate_text_async(text: str, target: str) -> str:
    """Run deep_translator in threadpool with fallback."""
    def _translate(t: str, tgt: str) -> str:
        return GoogleTranslator(source="auto", target=tgt).translate(t)
    try:
        return await asyncio.to_thread(_translate, text, target)
    except Exception as e:
        log.warning("translate_text_async failed: %s", e)
        return text

def extract_first_code_block_sync(html: str) -> Optional[str]:
    """Sync helper to extract first <pre> or <code> block using selectolax."""
    tree = HTMLParser(html)
    node = tree.css_first("pre, code")
    if node:
        txt = node.text(separator="\n").strip()
        return txt if len(txt) >= 8 else None
    return None

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
    try:
        feed = await parse_feed_async(feed_url)
    except Exception as e:
        log.warning("feed parse failed (%s): %s", feed_url, e)
        await cq.message.answer("❌ خطا در دریافت فید.", reply_markup=main_menu)
        await cq.answer()
        return

    entries = getattr(feed, "entries", [])
    if not entries:
        await cq.message.answer("❌ خبری پیدا نشد.", reply_markup=main_menu)
        await cq.answer()
        return

    # first entry
    entry = entries[0]
    title, summary, link = await extract_entry_plain_async(entry)

    # plain text (no global parse_mode) — safe
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
    chosen = await pick_iot_feed_async()
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

    translated = await translate_text_async(body, target)
    flag = "🇮🇷" if target == "fa" else "🇬🇧"
    await cq.message.answer(f"{flag} {translated}", reply_markup=main_menu, disable_web_page_preview=True)
    await cq.answer()

# ───────────────── Python Snippet ──────────
PROGRAMIZ_PY_EXAMPLES = "https://www.programiz.com/python-programming/examples"
MAX_INLINE_CODE = 3500  # if longer, send as file

@dp.callback_query(F.data == "pycodes")
async def cb_pycodes(cq: types.CallbackQuery):
    try:
        html = await fetch_html(PROGRAMIZ_PY_EXAMPLES, timeout=20.0)
        code = await asyncio.to_thread(extract_first_code_block_sync, html)
        if code:
            # Trim if too long for Telegram message; better send as file for really long code
            if len(code) > MAX_INLINE_CODE:
                # send as file/document
                bio = io.BytesIO(code.encode("utf-8"))
                bio.seek(0)
                await cq.message.answer_document(document=bio, filename="example.py", caption="📚 نمونه کد پایتون (Programiz)", reply_markup=main_menu)
                await cq.answer()
                return
            # send with Markdown triple-backticks (local parse_mode)
            await cq.message.answer(f"📚 نمونه کد پایتون (Programiz):\n\n```python\n{code}\n```",
                                    parse_mode="Markdown",
                                    disable_web_page_preview=True,
                                    reply_markup=main_menu)
            await cq.answer()
            return
    except Exception as e:
        log.warning("Programiz fetch failed: %s", e)

    await cq.message.answer("❌ کدی پیدا نشد.", reply_markup=main_menu)
    await cq.answer()

# ───────────────── /start ──────────────────
@dp.message(F.text == "/start")
async def start_cmd(msg: types.Message):
    await msg.answer("سلام! یکی از گزینه‌ها رو انتخاب کن:", reply_markup=main_inline_markup())
    await msg.answer("🔄 برای برگشت به منوی اصلی /start رو بزن 👇", reply_markup=main_menu)

# ───────────────── Health endpoint ─────────
async def health(request: web.Request):
    return web.Response(text="ok")

# ───────────────── Webhook ────────────────
async def on_startup(app: web.Application):
    webhook_url = f"{PUBLIC_URL}/webhook"
    try:
        await bot.set_webhook(webhook_url, secret_token=WEBHOOK_SECRET)
        log.info("✅ Webhook set: %s", webhook_url)
    except Exception as e:
        log.exception("Failed to set webhook: %s", e)
        # Don't raise; app can still run but will log the problem.

async def on_shutdown(app: web.Application):
    try:
        await bot.delete_webhook()
    except Exception as e:
        log.warning("delete_webhook failed: %s", e)
    try:
        await bot.session.close()
    except Exception as e:
        log.warning("bot.session.close failed: %s", e)
    log.info("🧹 Webhook deleted and session closed")

def build_app():
    app = web.Application()
    # health check
    app.router.add_get("/health", health)

    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

if __name__ == "__main__":
    # When deploying behind services that expect a health check, use /health
    log.info("Starting app on port %s", PORT)
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
