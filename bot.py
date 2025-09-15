import json
import logging
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web
from dotenv import load_dotenv
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# ------------------- تنظیمات -------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret123")
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ai-tech-bot")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not PUBLIC_URL:
    raise RuntimeError("PUBLIC_URL is missing")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
dp = Dispatcher()

# ------------------- لود پروژه‌ها -------------------
try:
    with open("projects.json", "r", encoding="utf-8") as f:
        db = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.error(f"❌ خطا در لود projects.json: {e}")
    db = {"robotics": [], "iot": [], "py_libs": []}

robotics = db.get("robotics", [])
iot = db.get("iot", [])
py_libs = db.get("py_libs", [])

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
    kb.button(text="📥 دانلود فایل", callback_data=f"codefile_{category}_{proj_id}")
    kb.button(text="🔙 بازگشت", callback_data=f"back_projlist_{category}")
    kb.adjust(2)
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
    cat = cb.data.split("_")[1]
    if cat == "robotics":
        await cb.message.edit_text("🤖 پروژه‌های رباتیک:", reply_markup=list_projects("robotics"))
    elif cat == "iot":
        await cb.message.edit_text("🌐 پروژه‌های اینترنت اشیا:", reply_markup=list_projects("iot"))
    elif cat == "libs":
        await cb.message.edit_text("🐍 کتابخانه‌های پایتون:", reply_markup=list_libs())
    await cb.answer()

@dp.callback_query(F.data.startswith("proj_"))
async def project_detail(cb: CallbackQuery):
    _, cat, proj_id = cb.data.split("_", 2)
    items = robotics if cat == "robotics" else iot
    proj = next((p for p in items if p["id"] == proj_id), None)
    if not proj:
        await cb.answer("❌ پیدا نشد")
        return
    text = f"📌 *{proj['title']}*\n\n{proj['description']}\n\n⚡️ بوردها: {', '.join(proj['boards'])}"
    await cb.message.edit_text(text, reply_markup=code_options(cat, proj_id))
    await cb.answer()

@dp.callback_query(F.data.startswith("code_"))
async def send_code(cb: CallbackQuery):
    _, cat, proj_id, lang = cb.data.split("_", 3)
    items = robotics if cat == "robotics" else iot
    proj = next((p for p in items if p["id"] == proj_id), None)
    if not proj:
        await cb.answer("❌ پیدا نشد")
        return
    code = proj["code"].get(lang, "// کد موجود نیست")
    text = f"📌 *{proj['title']}* - {lang.upper()}\n\n```{lang}\n{code}\n```"
    await cb.message.edit_text(text, reply_markup=code_options(cat, proj_id))
    await cb.answer()

@dp.callback_query(F.data.startswith("codefile_"))
async def send_code_file(cb: CallbackQuery):
    _, cat, proj_id = cb.data.split("_", 2)
    items = robotics if cat == "robotics" else iot
    proj = next((p for p in items if p["id"] == proj_id), None)
    if not proj:
        await cb.answer("❌ پیدا نشد")
        return
    if not proj.get("code"):
        await cb.answer("❌ کدی موجود نیست")
        return
    filename = f"{proj['id']}_code.txt"
    with open(filename, "w", encoding="utf-8") as f:
        for lang, code in proj["code"].items():
            f.write(f"// {lang.upper()}\n{code}\n\n")
    await cb.message.answer_document(FSInputFile(filename))
    os.remove(filename)
    await cb.answer("📥 فایل ارسال شد")

@dp.callback_query(F.data.startswith("lib_"))
async def lib_detail(cb: CallbackQuery):
    lib_name = cb.data.split("_", 1)[1]
    lib = next((l for l in py_libs if l["name"] == lib_name), None)
    if not lib:
        await cb.answer("❌ پیدا نشد")
        return
    text = (
        f"🐍 *{lib['name']}*\n"
        f"📂 دسته: {lib['category']}\n\n"
        f"{lib['description']}\n\n"
        f"📦 نصب:\n`{lib['install']}`\n\n"
        f"💡 مثال:\n```python\n{lib['example']}\n```"
    )
    await cb.message.edit_text(text, reply_markup=back_to_libs())
    await cb.answer()

# ------------------- بازگشت -------------------
@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery):
    await cb.message.edit_text("🔙 بازگشت به منوی اصلی:", reply_markup=main_menu())
    await cb.answer()

@dp.callback_query(F.data.startswith("back_projlist_"))
async def back_projlist(cb: CallbackQuery):
    cat = cb.data.split("_")[2]
    title = "🤖 پروژه‌های رباتیک:" if cat == "robotics" else "🌐 پروژه‌های اینترنت اشیا:"
    await cb.message.edit_text(title, reply_markup=list_projects(cat))
    await cb.answer()

# ------------------- وبهوک -------------------
async def on_startup(app: web.Application):
    await bot.set_webhook(f"{PUBLIC_URL}/webhook", secret_token=WEBHOOK_SECRET)
    logger.info(f"✅ Webhook set: {PUBLIC_URL}/webhook")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("🧹 Webhook deleted and session closed")

def build_app():
    app = web.Application()

    # health check
    async def root(_):
        return web.Response(text="Bot is running!")

    app.router.add_get("/", root)

    # ثبت وبهوک با هندلر رسمی aiogram
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET
    ).register(app, path="/webhook")

    # ادغام دیسپچر با اپ
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
