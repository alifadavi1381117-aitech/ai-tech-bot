import json
import logging
import os
from contextlib import suppress
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv
from aiogram.exceptions import TelegramBadRequest

# ------------------- تنظیمات پایه -------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret123")
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN تعریف نشده است (env)")
if not PUBLIC_URL:
    raise RuntimeError("❌ PUBLIC_URL تعریف نشده است (env)")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-tech-bot")

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.Markdown)
dp = Dispatcher()

# ------------------- لود دیتای پروژه‌ها -------------------
with open("projects.json", "r", encoding="utf-8") as f:
    db = json.load(f)

robotics = db.get("robotics", [])
iot = db.get("iot", [])
py_libs = db.get("py_libs", [])

# ------------------- کمک‌تابع‌ها -------------------
async def safe_ack(cb: CallbackQuery):
    """ACK بدون خطا حتی اگر کال‌بک قدیمی باشد."""
    with suppress(TelegramBadRequest):
        await cb.answer()

def is_stale_callback(cb: CallbackQuery, max_age_sec: int = 300) -> bool:
    """اگر پیام مربوط به کال‌بک خیلی قدیمی باشد True."""
    if not cb.message or not cb.message.date:
        return False
    now = datetime.now(timezone.utc)
    age = (now - cb.message.date).total_seconds()
    return age > max_age_sec

# ------------------- کیبوردها -------------------
def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🤖 رباتیک", callback_data="cat_robotics")
    kb.button(text="🌐 اینترنت اشیا (IoT)", callback_data="cat_iot")
    kb.button(text="🐍 کتابخانه‌های پایتون", callback_data="cat_libs")
    kb.adjust(1)
    return kb.as_markup()

def list_projects(category: str):
    kb = InlineKeyboardBuilder()
    items = robotics if category == "robotics" else iot
    for p in items:
        kb.button(text=p["title"], callback_data=f"proj_{category}_{p['id']}")
    kb.button(text="🔙 بازگشت", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()

def list_libs():
    kb = InlineKeyboardBuilder()
    for lib in py_libs:
        kb.button(text=lib["name"], callback_data=f"lib_{lib['name']}")
    kb.button(text="🔙 بازگشت", callback_data="back_main")
    kb.adjust(2)
    return kb.as_markup()

def code_options(category: str, proj_id: str):
    kb = InlineKeyboardBuilder()
    for lang in ["c", "cpp", "micropython"]:
        kb.button(text=lang.upper(), callback_data=f"code_{category}_{proj_id}_{lang}")
    kb.button(text="🔙 بازگشت", callback_data=f"back_projlist_{category}")
    kb.adjust(3)
    return kb.as_markup()

def back_to_libs():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 بازگشت", callback_data="cat_libs")
    return kb.as_markup()

# ------------------- هندلرها -------------------
@dp.message(F.text == "/start")
async def start_cmd(msg: Message):
    await msg.answer(
        "سلام 👋\nبه ربات آموزشی خوش اومدی!\nیک دسته‌بندی انتخاب کن:",
        reply_markup=main_menu(),
    )

@dp.callback_query(F.data.startswith("cat_"))
async def open_category(cb: CallbackQuery):
    await safe_ack(cb)
    if is_stale_callback(cb):
        return
    cat = cb.data.split("_")[1]
    if cat == "robotics":
        await cb.message.edit_text("🤖 پروژه‌های رباتیک:", reply_markup=list_projects("robotics"))
    elif cat == "iot":
        await cb.message.edit_text("🌐 پروژه‌های اینترنت اشیا:", reply_markup=list_projects("iot"))
    elif cat == "libs":
        await cb.message.edit_text("🐍 کتابخانه‌های پایتون:", reply_markup=list_libs())

@dp.callback_query(F.data.startswith("proj_"))
async def project_detail(cb: CallbackQuery):
    await safe_ack(cb)
    if is_stale_callback(cb):
        return
    _, cat, proj_id = cb.data.split("_", 2)
    items = robotics if cat == "robotics" else iot
    proj = next((p for p in items if p["id"] == proj_id), None)
    if not proj:
        await cb.answer("❌ پیدا نشد", show_alert=True)
        return
    text = f"📌 *{proj['title']}*\n\n{proj['description']}\n\n⚡️ بوردها: {', '.join(proj['boards'])}"
    await cb.message.edit_text(text, reply_markup=code_options(cat, proj_id))

@dp.callback_query(F.data.startswith("code_"))
async def send_code(cb: CallbackQuery):
    await safe_ack(cb)
    if is_stale_callback(cb):
        return
    _, cat, proj_id, lang = cb.data.split("_", 3)
    items = robotics if cat == "robotics" else iot
    proj = next((p for p in items if p["id"] == proj_id), None)
    if not proj:
        await cb.answer("❌ پیدا نشد", show_alert=True)
        return
    code = proj["code"].get(lang, "// کد موجود نیست")
    text = f"📌 *{proj['title']}* - {lang.upper()}\n\n```\n{code}\n```"
    await cb.message.edit_text(text, reply_markup=code_options(cat, proj_id))

@dp.callback_query(F.data.startswith("lib_"))
async def lib_detail(cb: CallbackQuery):
    await safe_ack(cb)
    if is_stale_callback(cb):
        return
    lib_name = cb.data.split("_", 1)[1]
    lib = next((l for l in py_libs if l["name"] == lib_name), None)
    if not lib:
        await cb.answer("❌ پیدا نشد", show_alert=True)
        return
    text = (
        f"🐍 *{lib['name']}*\n"
        f"📂 دسته: {lib['category']}\n\n"
        f"{lib['description']}\n\n"
        f"📦 نصب:\n`{lib['install']}`\n\n"
        f"💡 مثال:\n```python\n{lib['example']}\n```"
    )
    await cb.message.edit_text(text, reply_markup=back_to_libs())

# ------------------- دکمه‌های بازگشت -------------------
@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery):
    await safe_ack(cb)
    if is_stale_callback(cb):
        return
    await cb.message.edit_text("🔙 بازگشت به منوی اصلی:", reply_markup=main_menu())

@dp.callback_query(F.data.startswith("back_projlist_"))
async def back_projlist(cb: CallbackQuery):
    await safe_ack(cb)
    if is_stale_callback(cb):
        return
    cat = cb.data.split("_")[2]
    await cb.message.edit_text(
        f"🔙 بازگشت به لیست پروژه‌های {cat}:",
        reply_markup=list_projects(cat),
    )

# ------------------- وبهوک -------------------
async def on_startup(app: web.Application):
    await bot.set_webhook(
        f"{PUBLIC_URL}/webhook",
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,  # 👈 صف قدیمی‌ها پاک شود
    )
    logger.info(f"✅ Webhook set: {PUBLIC_URL}/webhook")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("🧹 Webhook deleted and session closed")

def build_app():
    app = web.Application()
    # صفحه‌ی سادهٔ ریشه
    async def root(_):
        return web.Response(text="Bot is running!")
    app.router.add_get("/", root)

    # ثبت مسیر /webhook با هندلر آماده‌ی Aiogram
    SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET
    ).register(app, path="/webhook")

    # اتصال Dispatcher به اپ aiohttp
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
