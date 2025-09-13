#!/usr/bin/env python3
# bot.py — Tech News Bot (webhook-friendly for Render + polling fallback)

import os
import io
import asyncio
import logging
import signal
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

# ───────────────── Config & Logging ─────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tech-news-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")  # if set -> use webhook (Render Web Service)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
PORT = int(os.getenv("PORT", os.getenv("RENDER_INTERNAL_PORT", "10000")))
RUN_MODE = os.getenv("RUN_MODE", "auto").lower()  # "auto" | "webhook" | "polling"

if not BOT_TOKEN:
    raise RuntimeError("Missing required env: BOT_TOKEN")

# choose mode
use_webhook = False
if RUN_MODE == "webhook":
    use_webhook = True
elif RUN_MODE == "polling":
    use_webhook = False
else:  # auto
    use_webhook = bool(PUBLIC_URL)

# default: no global parse_mode (we control per-message)
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
    return await asyncio.to_thread(feedparser.parse, url)

async def html_to_plain_async(html: str) -> str:
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
    def _translate(t: str, tgt: str) -> str:
        return GoogleTranslator(source="auto", target=tgt).translate(t)
    try:
        return await asyncio.to_thread(_translate, text, target)
    except Exception as e:
        log.warning("translate_text_async failed: %s", e)
        return text

# ───────────────── Robust code extractor -----------------
import re
import html as htmlmod

def extract_code_blocks_sync(html: str) -> Optional[str]:
    if not html:
        return None
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    try:
        tree = HTMLParser(html)
        node = tree.css_first("pre")
        if node:
            txt = node.text(separator="\n").strip()
            if len(txt) >= 8:
                return htmlmod.unescape(txt)
        node = tree.css_first("code")
        if node:
            txt = node.text(separator="\n").strip()
            if len(txt) >= 8:
                return htmlmod.unescape(txt)
    except Exception as e:
        log.debug("selectolax primary search failed: %s", e)
    try:
        tree = HTMLParser(html)
        for cls_keyword in ("highlight", "code", "example", "programiz", "syntax", "language-python"):
            node = tree.css_first(f"div[class*='{cls_keyword}']")
            if node:
                txt = node.text(separator="\n").strip()
                if len(txt) >= 8:
                    return htmlmod.unescape(txt)
    except Exception:
        pass
    try:
        tree = HTMLParser(html)
        node = tree.css_first("textarea")
        if node:
            txt = node.text(separator="\n").strip()
            if len(txt) >= 8:
                return htmlmod.unescape(txt)
    except Exception:
        pass
    m = re.search(r"(?is)<pre[^>]*>(.*?)</pre>", html)
    if m:
        txt = re.sub(r"\s+\n", "\n", htmlmod.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip()
        if len(txt) >= 8:
            return txt
    m2 = re.search(r"```(?:python)?\s*(.+?)```", html, flags=re.S | re.I)
    if m2:
        txt = m2.group(1).strip()
        if len(txt) >= 8:
            return htmlmod.unescape(txt)
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

    entry = entries[0]
    title, summary, link = await extract_entry_plain_async(entry)
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
MAX_INLINE_CODE = 3500

@dp.callback_query(F.data == "pycodes")
async def cb_pycodes(cq: types.CallbackQuery):
    try:
        html = await fetch_html(PROGRAMIZ_PY_EXAMPLES, timeout=20.0)
    except Exception as e:
        log.warning("Programiz fetch failed (network): %s", e)
        await cq.message.answer("❌ خطا در دریافت صفحهٔ Programiz.", reply_markup=main_menu)
        await cq.answer()
        return

    try:
        code = await asyncio.to_thread(extract_code_blocks_sync, html)
    except Exception as e:
        log.exception("extract_code_blocks_sync failed: %s", e)
        code = None

    if code:
        if len(code) > MAX_INLINE_CODE:
            bio = io.BytesIO(code.encode("utf-8"))
            bio.seek(0)
            await cq.message.answer_document(document=bio, filename="example.py", caption="📚 نمونه کد پایتون (Programiz)", reply_markup=main_menu)
            await cq.answer()
            return
        await cq.message.answer(f"📚 نمونه کد پایتون (Programiz):\n\n```python\n{code}\n```",
                                parse_mode="Markdown",
                                disable_web_page_preview=True,
                                reply_markup=main_menu)
        await cq.answer()
        return

    snippet = html[:4000] if html else ""
    log.warning("No code block found on Programiz page. HTML snippet logged (first 4k chars).")
    log.debug("Programiz HTML snippet: %s", snippet)

    try:
        m = re.search(r"(?is)<pre[^>]*>(.*?)</pre>", html)
        if m:
            raw = htmlmod.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
            if len(raw) >= 8:
                if len(raw) > MAX_INLINE_CODE:
                    bio = io.BytesIO(raw.encode("utf-8"))
                    bio.seek(0)
                    await cq.message.answer_document(document=bio, filename="example.py", caption="📚 نمونه کد پایتون (fallback)", reply_markup=main_menu)
                else:
                    await cq.message.answer(f"📚 نمونه کد پایتون (fallback):\n\n```python\n{raw}\n```",
                                            parse_mode="Markdown", reply_markup=main_menu)
                await cq.answer()
                return
    except Exception:
        pass

    await cq.message.answer("❌ کدی پیدا نشد — احتمالاً ساختار صفحه تغییر کرده یا سایت محتوای کد را به‌صورت داینامیک بارگذاری می‌کند.", reply_markup=main_menu)
    await cq.answer()

# ───────────────── /start ──────────────────
@dp.message(F.text == "/start")
async def start_cmd(msg: types.Message):
    await msg.answer("سلام! یکی از گزینه‌ها رو انتخاب کن:", reply_markup=main_inline_markup())
    await msg.answer("🔄 برای برگشت به منوی اصلی /start رو بزن 👇", reply_markup=main_menu)

# ───────────────── Health & Index ─────────
async def health(request: web.Request):
    return web.Response(text="ok")

async def index(request: web.Request):
    return web.Response(text="TechNewsBot: running")

# ───────────────── Webhook startup/shutdown ─
async def on_startup(app: web.Application):
    webhook_url = f"{PUBLIC_URL}/webhook"
    try:
        # drop pending updates to avoid backlog; tune max_connections as needed
        await bot.set_webhook(webhook_url, secret_token=WEBHOOK_SECRET, drop_pending_updates=True, max_connections=40)
        log.info("✅ Webhook set: %s", webhook_url)
    except Exception as e:
        log.exception("Failed to set webhook: %s", e)

async def on_shutdown(app: web.Application):
    try:
        # it's okay to delete webhook on shutdown; if you prefer to keep it, comment out
        await bot.delete_webhook()
    except Exception as e:
        log.warning("delete_webhook failed: %s", e)
    try:
        await bot.session.close()
    except Exception as e:
        log.warning("bot.session.close failed: %s", e)
    log.info("🧹 Webhook deleted and session closed")

def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_head("/", index)
    app.router.add_get("/health", health)

    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

# ───────────────── Signal logging (useful to debug restarts) ─
def setup_signal_logging():
    loop = asyncio.get_event_loop()
    def _on_signal(sig):
        log.info("Received signal: %s", sig)
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, lambda s=s: _on_signal(s))
        except NotImplementedError:
            # windows or limited loop — ignore
            pass

# ───────────────── Entrypoint ─────────────
async def _run_polling():
    log.info("Starting long polling...")
    await dp.start_polling(bot)

def main():
    setup_signal_logging()
    if use_webhook:
        log.info("Running in webhook mode (web service). PORT=%s", PORT)
        app = build_app()
        web.run_app(app, host="0.0.0.0", port=PORT)
    else:
        # polling mode (local dev or background worker)
        log.info("Running in polling mode.")
        try:
            asyncio.run(_run_polling())
        except KeyboardInterrupt:
            log.info("Polling stopped by user")

if __name__ == "__main__":
    main()
