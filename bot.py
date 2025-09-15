import json
import logging
import os
import html as _html
from typing import Iterable

from aiogram import Dispatcher, F
from aiogram.client.bot import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv

# ------------------- تنظیمات -------------------
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-tech-bot")


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"❌ {name} is missing (set in Render env)")
    return v

BOT_TOKEN = _require_env("BOT_TOKEN")
PUBLIC_URL = _require_env("PUBLIC_URL")
WEBHOOK_SECRET = _require_env("WEBHOOK_SECRET")
PORT = int(os.getenv("PORT", "10000"))

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# ------------------- لود دیتابیس ساده -------------------

def _load_db(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except FileNotFoundError:
        logger.warning("projects.json not found; using empty dataset")
        return {}
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in projects.json: %s", e)
        return {}


db = _load_db("projects.json")
robotics = db.get("robotics", [])
iot = db.get("iot", [])
py_libs = db.get("py_libs", [])

# ------------------- Helpers -------------------

MAX_MSG = 4096  # Telegram limit


def _chunks(s: str, n: int) -> Iterable[str]:
    for i in range(0, len(s), n):
        yield s[i : i + n]


async def safe_edit_text(message: Message, text: str, **kwargs):
    if len(text) <= MAX_MSG:
        return await message.edit_text(text, **kwargs)
    parts = list(_chunks(text, MAX_MSG))
    await message.edit_text(parts[0], **kwargs)
    for p in parts[1:]:
        await message.answer(p, **kwargs)


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
        kb.button(text=p.get("title", "بدون عنوان"), callback_data=f"proj_{category}_{p.get('id','')}")
    kb.button(text="🔙 بازگشت", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()


def list_libs():
    kb = InlineKeyboardBuilder()
    for lib in py_libs:
        name = lib.get("name", "—")
        kb.button(text=name, callback_data=f"lib_{name}")
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

@dp.message(CommandStart())
async def start_cmd(msg: Message):
    await msg.answer(
        "سلام 👋\nبه ربات آموزشی خوش اومدی!\nیک دسته‌بندی انتخاب کن:",
        reply_markup=main_menu(),
    )


@dp.message(F.text)
async def fallback(msg: Message):
    # هر پیام متنی را به منوی اصلی هدایت می‌کنیم
    await msg.answer("برای شروع از منوی زیر استفاده کن:", reply_markup=main_menu())


@dp.callback_query(F.data.startswith("cat_"))
async def open_category(cb: CallbackQuery):
    cat = cb.data.split("_", 1)[1]
    if cat == "robotics":
        await safe_edit_text(cb.message, "🤖 پروژه‌های رباتیک:", reply_markup=list_projects("robotics"))
    elif cat == "iot":
        await safe_edit_text(cb.message, "🌐 پروژه‌های اینترنت اشیا:", reply_markup=list_projects("iot"))
    elif cat == "libs":
        await safe_edit_text(cb.message, "🐍 کتابخانه‌های پایتون:", reply_markup=list_libs())
    await cb.answer()


@dp.callback_query(F.data.startswith("proj_"))
async def project_detail(cb: CallbackQuery):
    _, cat, proj_id = cb.data.split("_", 2)
    items = robotics if cat == "robotics" else iot
    proj = next((p for p in items if p.get("id") == proj_id), None)
    if not proj:
        await cb.answer("❌ پروژه پیدا نشد")
        return

    title_h = _html.escape(proj.get("title", ""))
    desc_h = _html.escape(proj.get("description", ""))
    boards_h = _html.escape(", ".join(proj.get("boards", [])))
    parts_h = _html.escape(", ".join(proj.get("parts", [])))
    text = f"📌 <b>{title_h}</b>

{desc_h}

⚡️ بوردها: {boards_h}
🧩 قطعات: {parts_h if parts_h else '—'}"

    await safe_edit_text(cb.message, text, reply_markup=code_options(cat, proj_id))
    await cb.answer()


@dp.callback_query(F.data.startswith("code_"))
async def send_code(cb: CallbackQuery):
    _, cat, proj_id, lang = cb.data.split("_", 3)
    items = robotics if cat == "robotics" else iot
    proj = next((p for p in items if p.get("id") == proj_id), None)
    if not proj:
        await cb.answer("❌ پروژه پیدا نشد")
        return

    code_raw = proj.get("code", {}).get(lang)
    if not code_raw:
        await cb.answer("کدی برای این زبان موجود نیست")
        return

    title_h = _html.escape(proj.get("title", ""))
    code_h = _html.escape(code_raw)

    preview = f"📌 <b>{title_h}</b> - {lang.upper()}\n\n"
    html_block = f"<pre><code>{code_h}</code></pre>"
    text = preview + html_block

    # اگر متن طولانی شد به‌صورت فایل ارسال می‌کنیم
    if len(text) <= 4000:
        await safe_edit_text(cb.message, text, reply_markup=code_options(cat, proj_id))
    else:
        filename = f"{proj.get('title','project')}_{lang}.txt".replace(" ", "_")
        doc = BufferedInputFile(code_raw.encode("utf-8"), filename=filename)
        await cb.message.answer_document(
            doc,
            caption=f"📌 {proj.get('title','')} - {lang.upper()}",
            reply_markup=code_options(cat, proj_id),
        )
    await cb.answer()


@dp.callback_query(F.data.startswith("lib_"))
async def lib_detail(cb: CallbackQuery):
    lib_name = cb.data.split("_", 1)[1]
    lib = next((l for l in py_libs if l.get("name") == lib_name), None)
    if not lib:
        await cb.answer("❌ کتابخانه پیدا نشد")
        return

    name_h = _html.escape(lib.get("name", ""))
    cat_h = _html.escape(lib.get("category", ""))
    desc_h = _html.escape(lib.get("description", ""))
    install_h = _html.escape(lib.get("install", ""))
    example_h = _html.escape(lib.get("example", ""))

    text = (
        f"🐍 <b>{name_h}</b>\n"
        f"📂 دسته: {cat_h}\n\n"
        f"{desc_h}\n\n"
        f"📦 نصب:\n<code>{install_h}</code>\n\n"
        f"💡 مثال:\n<pre><code>{example_h}</code></pre>"
    )
    await safe_edit_text(cb.message, text, reply_markup=back_to_libs())
    await cb.answer()


# ------------------- بازگشت -------------------

@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery):
    await safe_edit_text(cb.message, "🔙 بازگشت به منوی اصلی:", reply_markup=main_menu())
    await cb.answer()


@dp.callback_query(F.data.startswith("back_projlist_"))
async def back_projlist(cb: CallbackQuery):
    cat = cb.data.split("_", 2)[2]
    await safe_edit_text(
        cb.message,
        f"🔙 بازگشت به لیست پروژه‌های {cat}:",
        reply_markup=list_projects(cat),
    )
    await cb.answer()


# ------------------- وبهوک -------------------

async def on_startup(app: web.Application):
    await bot.set_webhook(f"{PUBLIC_URL}/webhook", secret_token=WEBHOOK_SECRET)
    logger.info(f"✅ Webhook set: {PUBLIC_URL}/webhook")


async def on_shutdown(app: web.Application):
    # برای جلوگیری از قطع اضافی وبهوک در رولینگ ری‌استارت، فقط سشن را می‌بندیم
    await bot.session.close()
    logger.info("Session closed")


def build_app():
    app = web.Application()

    async def root_get(_):
        return web.Response(text="Bot is running!")
    app.router.add_get("/", root_get)  # GET and HEAD (auto)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    ).register(app, path="/webhook")

    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
