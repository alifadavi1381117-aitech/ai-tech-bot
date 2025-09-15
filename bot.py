import os
import json
import logging
import html
from pathlib import Path
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties

from aiohttp import web

# ------------------------------------ تنظیمات لاگر ------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-tech-bot")

# ------------------------------------ لود env ------------------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN تعریف نشده است")

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://example.com/webhook")
PORT = int(os.getenv("PORT", 10000))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")  # اختیاری ولی توصیه می‌شود

if not WEBHOOK_URL.endswith("/webhook"):
    logger.warning("⚠️ WEBHOOK_URL بهتر است با /webhook ختم شود: %s", WEBHOOK_URL)

# ------------------------------------ Bot & Dispatcher ------------------------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ------------------------------------ لود دیتای پروژه‌ها ------------------------------------
DATA_PATH = Path("data.json")
if not DATA_PATH.exists():
    raise RuntimeError("❌ فایل data.json یافت نشد")

try:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        DATA = json.load(f)
    if not isinstance(DATA, dict):
        raise ValueError("فرمت data.json باید دیکشنری باشد")
    logger.info("📦 Loaded categories: %s", ", ".join(DATA.keys()))
except Exception as e:
    raise RuntimeError(f"❌ خطا در لود data.json: {e}")

# ------------------------------------ دسته‌ها ------------------------------------
CATEGORY_NAMES = {
    "robotics": "🤖 رباتیک",
    "iot": "🌐 IoT",
    "py_libs": "📚 کتابخانه‌های پایتون",
}

# ------------------------------------ متن‌ها ------------------------------------
WELCOME_TEXT = "سلام 👋\nیکی از دسته‌ها رو انتخاب کن:"

# ------------------------------------ توابع کمکی ------------------------------------
def build_main_menu():
    kb = InlineKeyboardBuilder()
    for key, title in CATEGORY_NAMES.items():
        kb.button(text=title, callback_data=f"cat:{key}")
    kb.adjust(1)
    return kb.as_markup()


def build_back_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 بازگشت", callback_data="back:main")
    return kb.as_markup()


def build_projects_menu(category: str):
    kb = InlineKeyboardBuilder()
    for p in DATA.get(category, []):
        title = p.get("title", "بدون عنوان")
        pid = p.get("id")
        if pid is not None:
            kb.button(text=str(title), callback_data=f"proj:{category}:{pid}")
    kb.button(text="🔙 بازگشت", callback_data="back:main")
    kb.adjust(1)
    return kb.as_markup()


def _csv(items):
    if not isinstance(items, list):
        return "—"
    safe = [html.escape(str(x)) for x in items if x is not None]
    return ", ".join(safe) if safe else "—"


async def project_detail(project: dict) -> str:
    """ساخت متن نمایش جزئیات پروژه (با escape برای HTML)"""
    title_h = html.escape(str(project.get("title", "بدون عنوان")))
    desc = html.escape(str(project.get("description", "—")))
    boards = _csv(project.get("boards", []))
    parts = _csv(project.get("parts", []))

    return (
        f"📌 <b>{title_h}</b>\n\n"
        f"{desc}\n\n"
        f"⚡️ بوردها: {boards}\n"
        f"🧩 قطعات: {parts}"
    )


# ------------------------------------ هندلرها ------------------------------------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=build_main_menu())


@dp.callback_query(F.data.startswith("cat:"))
async def category_handler(callback: CallbackQuery):
    cat = callback.data.split(":", 1)[1]
    if cat not in CATEGORY_NAMES:
        await callback.answer("چنین دسته‌ای وجود ندارد.", show_alert=True)
        return
    name = CATEGORY_NAMES[cat]
    await callback.message.edit_text(f"📂 دسته: {name}", reply_markup=build_projects_menu(cat))
    await callback.answer()


@dp.callback_query(F.data.startswith("proj:"))
async def project_handler(callback: CallbackQuery):
    try:
        _, cat, pid = callback.data.split(":", 2)
    except ValueError:
        await callback.answer("داده‌ی نامعتبر", show_alert=True)
        return

    project = next((p for p in DATA.get(cat, []) if str(p.get("id")) == pid), None)

    if not project:
        await callback.message.edit_text("❌ پروژه موردنظر پیدا نشد.", reply_markup=build_back_menu())
        await callback.answer()
        return

    text = await project_detail(project)
    await callback.message.edit_text(text, reply_markup=build_back_menu())
    await callback.answer()


@dp.callback_query(F.data == "back:main")
async def back_main(callback: CallbackQuery):
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=build_main_menu())
    await callback.answer()


# ------------------------------------ وب‌هوک و وب‌سرور ------------------------------------
async def on_startup(app: web.Application):
    await bot.set_webhook(
        WEBHOOK_URL,
        drop_pending_updates=True,
        secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
    )
    logger.info("✅ Webhook set: %s", WEBHOOK_URL)


async def on_shutdown(app: web.Application):
    try:
        await bot.delete_webhook()
    finally:
        await bot.session.close()
    logger.info("🧹 Webhook deleted and session closed")


async def handle_webhook(request: web.Request):
    # تلگرام درخواست JSON می‌فرستد
    try:
        body = await request.json()
    except Exception:
        # در صورت خطا، برای دیباگ متن خام را می‌خوانیم
        raw = await request.text()
        logger.error("❌ Invalid JSON body: %s", raw[:500])
        return web.Response(status=400, text="bad request")

    logger.info("📩 Update received: %s", str(body)[:500])

    try:
        await dp.feed_webhook_update(bot, body, request.headers)
    except Exception as e:
        logger.exception("❌ Error while processing update: %s", e)
        # همواره 200 بده تا تلگرام دوباره سعی نکند؛ خطا را لاگ کردیم
    return web.Response(text="ok")


async def root_get(request: web.Request):
    return web.Response(text="AI Tech Bot is running!")


def build_app():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/", root_get)

    # ثبت استارتاپ/شات‌داون (async صحیح)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


if __name__ == "__main__":
    try:
        app = build_app()
        web.run_app(app, host="0.0.0.0", port=PORT)
    except Exception as e:
        logger.exception("❌ Server crashed: %s", e)

"""
نمونه‌ی data.json (در کنار فایل اصلی ذخیره کنید):
{
  "robotics": [
    {
      "id": 1,
      "title": "بازوی رباتیک ساده",
      "description": "کنترل سروو با آردوینو",
      "boards": ["Arduino UNO"],
      "parts": ["SG90", "Potentiometer"]
    }
  ],
  "iot": [
    {
      "id": "esp-01",
      "title": "دماسنج آنلاین",
      "description": "ارسال دما به MQTT",
      "boards": ["ESP8266"],
      "parts": ["DHT22"]
    }
  ],
  "py_libs": [
    {
      "id": 101,
      "title": "نمونه‌ی FastAPI",
      "description": "REST ساده برای دمو",
      "boards": [],
      "parts": []
    }
  ]
}
"""
