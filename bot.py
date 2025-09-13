import os
import logging
import random
from collections import defaultdict
from html import escape as html_escape

import feedparser
import httpx
from aiohttp import web
from selectolax.parser import HTMLParser
from deep_translator import GoogleTranslator

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application


# ────────────────────────────── Logging ──────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tech-news-bot")


# ────────────────────────────── ENV / Config ─────────────────────────
BOT_TOKEN      = os.getenv("BOT_TOKEN")
PUBLIC_URL     = os.getenv("PUBLIC_URL")  # e.g. https://ai-tech-bot-docer.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
PORT           = int(os.getenv("PORT", "10000"))

# Keepalive (optional)
KEEPALIVE_TOKEN = os.getenv("KEEPALIVE_TOKEN", "")

if not BOT_TOKEN or not PUBLIC_URL:
    raise RuntimeError("Missing required env(s): BOT_TOKEN or PUBLIC_URL")

# Force HTML so Telegram از MarkdownV2 استفاده نکند
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# ────────────────────────────── Data Sources ─────────────────────────
TECH_FEED = "https://feeds.bbci.co.uk/news/technology/rss.xml"
AI_FEED   = "https://techcrunch.com/category/artificial-intelligence/feed/"
IOT_FEEDS = [
    "https://www.iot-now.com/feed/",
    "https://www.iotforall.com/feed/",
    "https://www.iotworldtoday.com/feed/",
    "https://iotbusinessnews.com/feed/",
]

PROGRAMIZ_PY_EXAMPLES = "https://www.programiz.com/python-programming/examples"


# ────────────────────────────── State (per-user) ─────────────────────
# نگه‌داشتن ایندکس خبر برای هر کاربر/دسته‌بندی تا تکراری ارسال نشود
# user_indexes[user_id]["tech"/"ai"/"iot"] = int
user_indexes: dict[int, dict[str, int]] = defaultdict(lambda: {"tech": 0, "ai": 0, "iot": 0})


# ────────────────────────────── Helpers ──────────────────────────────
def html_to_plain(html: str) -> str:
    """Extract clean text from HTML (remove script/style & extra spaces)."""
    if not html:
        return ""
    tree = HTMLParser(html)
    for n in tree.css("script, style"):
        n.decompose()
    text = tree.text(separator=" ").strip()
    return " ".join(text.split())


def escape_html(s: str, limit: int | None = None) -> str:
    """Safe HTML escaping for parse_mode=HTML."""
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
    """Try multiple IoT feeds; return first viable feed with entries."""
    random.shuffle(IOT_FEEDS)
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


def get_category_title(cat: str) -> str:
    return {"tech": "💻 Tech", "ai": "🤖 AI", "iot": "🌐 IoT"}.get(cat, "📰 News")


def feed_for_category(cat: str) -> str | None:
    if cat == "tech":
        return TECH_FEED
    if cat == "ai":
        return AI_FEED
    if cat == "iot":
        return pick_iot_feed()
    return None


# ────────────────────────────── Keyboards ────────────────────────────
def home_menu_inline():
    kb = InlineKeyboardBuilder()
    kb.button(text="💻 Tech News", callback_data="cat:tech")
    kb.button(text="🤖 AI News",   callback_data="cat:ai")
    kb.button(text="🌐 IoT News",  callback_data="cat:iot")
    kb.button(text="🐍 کدهای مفید پایتون", callback_data="py:menu")
    kb.adjust(2)
    return kb.as_markup()


def home_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="/start")]],
        resize_keyboard=True
    )


def news_controls(cat: str):
    kb = InlineKeyboardBuilder()
    # ترجمه
    kb.button(text="🇮🇷 فارسی",  callback_data=f"tr:fa")
    kb.button(text="🇬🇧 English", callback_data=f"tr:en")
    # صفحه‌بندی
    kb.button(text="⬅️ قبلی", callback_data=f"nav:prev:{cat}")
    kb.button(text="بعدی ➡️", callback_data=f"nav:next:{cat}")
    # خانه
    kb.button(text="🏠 خانه", callback_data="home")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def python_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📚 دریافت یک نمونه کد", callback_data="py:get")
    kb.button(text="🏠 خانه", callback_data="home")
    kb.adjust(1, 1)
    return kb.as_markup()


# ────────────────────────────── News Sending ─────────────────────────
async def build_news_text(entry_title: str, entry_summary: str, entry_link: str, cat: str, idx: int, total: int) -> str:
    safe_title = escape_html(entry_title, 200)
    safe_sum   = escape_html(entry_summary, 1800)
    safe_link  = escape_html(entry_link, 1000)
    header = f"{get_category_title(cat)} • {idx+1}/{total}"
    return (
        f"<b>{header}</b>\n\n"
        f"📰 <b>{safe_title}</b>\n"
        f"{safe_sum}\n\n"
        f"🔗 <a href=\"{safe_link}\">{safe_link}</a>"
    )


async def send_or_edit_news(message: types.Message, cat: str, *, edit: bool = False):
    """Send or edit a news message based on user's current index in that category."""
    user_id = message.chat.id
    feed_url = feed_for_category(cat)
    if not feed_url:
        await message.answer("❌ خبر IoT پیدا نشد.", reply_markup=home_reply_kb())
        return

    feed = feedparser.parse(feed_url)
    entries = getattr(feed, "entries", [])

    if not entries:
        await message.answer("❌ خبری پیدا نشد.", reply_markup=home_reply_kb())
        return

    # محدودیت: تا 20 آیتم کافی است
    entries = entries[:20]

    idx = user_indexes[user_id][cat]
    if idx >= len(entries):
        idx = 0
        user_indexes[user_id][cat] = 0

    entry = entries[idx]
    title, summary, link = extract_entry_plain(entry)
    text = await build_news_text(title, summary, link, cat, idx, len(entries))

    markup = news_controls(cat)

    if edit:
        await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    else:
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


# ────────────────────────────── Python Snippets ──────────────────────
async def programiz_random_example_url(html: str) -> str | None:
    """From Programiz examples page, pick one example URL randomly."""
    tree = HTMLParser(html)
    links = []
    for a in tree.css("a"):
        href = a.attributes.get("href", "")
        # نمونه لینک‌های مناسب شامل /python-programming/examples/ هستند
        if "/python-programming/examples/" in href:
            if href.startswith("/"):
                href = "https://www.programiz.com" + href
            elif href.startswith("http"):
                pass
            else:
                href = "https://www.programiz.com/" + href
            links.append(href)
    links = list({x for x in links})  # unique
    if not links:
        return None
    return random.choice(links)


def extract_first_code_block(html: str) -> str | None:
    tree = HTMLParser(html)
    # معمولاً کدها داخل pre > code هستند
    node = tree.css_first("pre code") or tree.css_first("pre")
    if node:
        txt = node.text(separator="\n").strip()
        return txt if len(txt) >= 8 else None
    return None


async def get_random_python_snippet() -> str | None:
    try:
        main_html = await fetch_html(PROGRAMIZ_PY_EXAMPLES, timeout=25.0)
        example_url = await programiz_random_example_url(main_html)
        if not example_url:
            return None
        example_html = await fetch_html(example_url, timeout=25.0)
        code = extract_first_code_block(example_html)
        if code:
            return code
    except Exception as e:
        log.warning(f"Programiz fetch failed: {e}")
    return None


# ────────────────────────────── Handlers: Navigation ─────────────────
@dp.callback_query(F.data.startswith("nav:"))
async def cb_nav(cq: types.CallbackQuery):
    # nav:prev:cat  |  nav:next:cat
    try:
        _, direction, cat = cq.data.split(":", 2)
    except:
        await cq.answer("Bad payload")
        return

    user_id = cq.from_user.id
    # بازسازی ایندکس
    idx = user_indexes[user_id][cat]
    if direction == "next":
        user_indexes[user_id][cat] = idx + 1
    elif direction == "prev":
        user_indexes[user_id][cat] = max(0, idx - 1)

    await send_or_edit_news(cq.message, cat, edit=True)
    await cq.answer()


@dp.callback_query(F.data == "home")
async def cb_home(cq: types.CallbackQuery):
    await cq.message.answer(
        (
            "👋 <b>به ربات تکنولوژی خوش اومدی!</b>\n\n"
            "اینجا می‌تونی:\n"
            "🔹 جدیدترین اخبار 🤖 AI / 🌐 IoT / 💻 Tech رو ببینی\n"
            "🔹 متن خبرها رو سریع ترجمه کنی (🇮🇷/🇬🇧)\n"
            "🔹 نمونه‌کدهای آماده‌ی 🐍 پایتون بگیری\n\n"
            "از منوی زیر شروع کن 👇"
        ),
        reply_markup=home_menu_inline()
    )
    await cq.answer()


# ────────────────────────────── Handlers: Categories ────────────────
@dp.callback_query(F.data.startswith("cat:"))
async def cb_category(cq: types.CallbackQuery):
    # cat:tech | cat:ai | cat:iot
    _, cat = cq.data.split(":", 1)
    # ریست نرم ایندکس اگر پیام قبلی طولانی شده
    user_indexes[cq.from_user.id][cat] = user_indexes[cq.from_user.id][cat]
    await send_or_edit_news(cq.message, cat, edit=False)
    await cq.answer()


# ────────────────────────────── Handlers: Translate ─────────────────
@dp.callback_query(F.data.startswith("tr:"))
async def cb_translate(cq: types.CallbackQuery):
    # tr:fa | tr:en
    _, lang = cq.data.split(":", 1)
    target = "fa" if lang == "fa" else "en"

    # متن فعلی پیام (نمایشی) را ترجمه می‌کنیم
    current_text = cq.message.html_text or cq.message.text or ""
    # بهتره لینک انتهای پیام را برای ترجمه حذف کنیم
    base_txt = current_text.split("🔗")[0].strip()

    try:
        translated = GoogleTranslator(source="auto", target=target).translate(base_txt)
    except Exception as e:
        log.warning(f"translate error: {e}")
        translated = base_txt

    flag = "🇮🇷" if target == "fa" else "🇬🇧"
    safe_trans = escape_html(translated, 3500)
    await cq.message.answer(f"{flag} <pre><code>{safe_trans}</code></pre>", disable_web_page_preview=True)
    await cq.answer()


# ────────────────────────────── Handlers: Python Menu ───────────────
@dp.callback_query(F.data == "py:menu")
async def cb_py_menu(cq: types.CallbackQuery):
    await cq.message.answer("🐍 از گزینه‌های زیر انتخاب کن:", reply_markup=python_menu_kb())
    await cq.answer()


@dp.callback_query(F.data == "py:get")
async def cb_py_get(cq: types.CallbackQuery):
    code = await get_random_python_snippet()
    if code:
        code_safe = escape_html(code, 3500)
        await cq.message.answer(
            "<b>📚 نمونه کد پایتون (Programiz):</b>\n<pre><code>" + code_safe + "</code></pre>",
            disable_web_page_preview=True
        )
    else:
        await cq.message.answer("❌ کدی پیدا نشد. دوباره تلاش کن.", reply_markup=python_menu_kb())
    await cq.answer()


# ────────────────────────────── /start ──────────────────────────────
@dp.message(F.text == "/start")
async def start_cmd(msg: types.Message):
    # reset soft (ایندکس‌ها را دست نزنیم؛ فقط UI)
    start_text = (
        "👋 <b>سلام! به ربات تکنولوژی خوش اومدی</b>\n\n"
        "از اینجا می‌تونی:\n"
        "• اخبار جدید <b>🤖 AI</b>، <b>🌐 IoT</b> و <b>💻 Tech</b> رو ببینی\n"
        "• متن خبرها رو سریع به <b>🇮🇷 فارسی</b> یا <b>🇬🇧 انگلیسی</b> ترجمه کنی\n"
        "• <b>🐍 نمونه‌کدهای پایتون</b> آماده دریافت کنی\n\n"
        "از منوی زیر شروع کن 👇"
    )
    await msg.answer(start_text, reply_markup=home_menu_inline())
    await msg.answer("🔄 برای برگشت به منوی اصلی /start رو بزن ⬇️", reply_markup=home_reply_kb())


# ────────────────────────────── Webhook / Server ────────────────────
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

    # webhook handler
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    # healthz (برای keep-alive با توکن اختیاری)
    async def healthz(request):
        token = request.query.get("token", "")
        if KEEPALIVE_TOKEN and token != KEEPALIVE_TOKEN:
            return web.Response(text="forbidden", status=403)
        return web.Response(text="ok", status=200)

    app.router.add_get("/healthz", healthz)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
