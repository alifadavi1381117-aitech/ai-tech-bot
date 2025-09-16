import os
import json
import html as _html
import logging
from typing import Iterable, List, Dict, Any

from aiohttp import web
from aiogram import Dispatcher, F
from aiogram.client.bot import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# ---------------------------- Logging ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ai-tech-bot")

# ---------------------------- ENV ----------------------------
def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"❌ {name} is missing (set it in Render env)")
    return v

BOT_TOKEN      = _require_env("BOT_TOKEN")
PUBLIC_URL     = _require_env("PUBLIC_URL")  # e.g. https://your-app.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret123")
PORT           = int(os.getenv("PORT", "10000"))

# ---------------------------- Bot / Dispatcher ----------------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ---------------------------- DB ----------------------------
DB_PATH = os.getenv("DB_PATH", "projects.json")
if not os.path.exists(DB_PATH):
    raise RuntimeError("❌ فایل projects.json یافت نشد")

with open(DB_PATH, "r", encoding="utf-8") as f:
    db: Dict[str, Any] = json.load(f) or {}
logger.info("Loaded %s with keys: %s", DB_PATH, list(db.keys()))

robotics: List[Dict[str, Any]] = db.get("robotics", [])
iot: List[Dict[str, Any]]      = db.get("iot", [])
py_libs: List[Dict[str, Any]]  = db.get("py_libs", [])

# ---------------------------- Simple in-memory state ----------------------------
USER_STATE: Dict[int, str] = {}  # user_id -> 'search' when waiting for query
CURRENT_LIB: Dict[int, str] = {}  # user_id -> lib_name (for contextual download)

# ---------------------------- Helpers ----------------------------
TG_MAX = 4096

def chunk_text(s: str, n: int) -> Iterable[str]:
    for i in range(0, len(s), n):
        yield s[i:i+n]

def safe_get_items_by_cat(category: str) -> List[Dict[str, Any]]:
    if category == "robotics":
        return robotics
    if category == "iot":
        return iot
    return []

async def safe_edit(message: Message, text: str, **kwargs):
    """Edit if possible; otherwise send a new message."""
    try:
        await message.edit_text(text, **kwargs)
    except Exception:
        await message.answer(text, **kwargs)

# ---------------------------- Keyboards ----------------------------
def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🤖 رباتیک", callback_data="cat_robotics")
    kb.button(text="🌐 اینترنت اشیا (IoT)", callback_data="cat_iot")
    kb.button(text="🐍 کتابخانه‌های پایتون", callback_data="cat_libs")
    kb.button(text="🔎 جستجو", callback_data="search_start")
    kb.adjust(1)
    return kb.as_markup()


def list_projects(category: str):
    items = safe_get_items_by_cat(category)
    kb = InlineKeyboardBuilder()
    for p in items:
        kb.button(text=p.get("title", "—"), callback_data=f"proj_{category}_{p.get('id','')}")
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


def code_menu(category: str, proj_id: str, proj: Dict[str, Any], current_lang: str | None = None):
    """Language switcher; shows Download only for the currently open language."""
    kb = InlineKeyboardBuilder()

    # language switchers
    for lang in ("c", "cpp", "micropython"):
        kb.button(text=lang.upper(), callback_data=f"code_{category}_{proj_id}_{lang}")

    # contextual download only for current language
    if current_lang and (proj.get("code") or {}).get(current_lang):
        kb.button(text=f"⬇️ دانلود {current_lang.upper()}", callback_data=f"dls_{category}_{proj_id}_{current_lang}")

    # back
    kb.button(text="🔙 بازگشت", callback_data=f"back_projlist_{category}")
    kb.adjust(3)
    return kb.as_markup()


def back_to_libs():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬇️ دانلود مثال", callback_data="dllib_example")
    kb.button(text="⬇️ JSON کتابخانه", callback_data="dllib_json")
    kb.button(text="🔙 بازگشت", callback_data="cat_libs")
    kb.adjust(2)
    return kb.as_markup()

# ---------------------------- Search ----------------------------
def _norm(s: str) -> str:
    return (s or "").strip().lower()

def search_all(query: str):
    q = _norm(query)
    if not q:
        return []

    results = []  # (kind, key, title)
    # robotics / iot projects
    for cat, items in (("robotics", robotics), ("iot", iot)):
        for p in items:
            hay = " ".join([
                str(p.get("title", "")),
                str(p.get("description", "")),
                ",".join(p.get("boards", []) or []),
                ",".join(p.get("parts", []) or []),
            ]).lower()
            if q in hay:
                results.append(("proj", f"{cat}_{p.get('id','')}", p.get("title", "(بدون عنوان)")))
    # python libs
    for lib in py_libs:
        hay = " ".join([
            str(lib.get("name", "")),
            str(lib.get("category", "")),
            str(lib.get("description", "")),
        ]).lower()
        if q in hay:
            results.append(("lib", lib.get("name", ""), lib.get("name", "(lib)")))

    return results[:50]


def search_results_kb(results):
    kb = InlineKeyboardBuilder()
    for kind, key, title in results:
        if kind == "proj":
            cat, pid = key.split("_", 1)
            kb.button(text=f"📁 {title}", callback_data=f"proj_{cat}_{pid}")
        elif kind == "lib":
            kb.button(text=f"🐍 {title}", callback_data=f"lib_{key}")
    kb.button(text="🔙 بازگشت", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()

# ---------------------------- Handlers ----------------------------
@dp.message(CommandStart())
async def start_cmd(msg: Message):
    await msg.answer("سلام 👋\nاز منو یکی از دسته‌بندی‌ها رو انتخاب کن:", reply_markup=main_menu())

@dp.message(F.text)
async def on_text(msg: Message):
    # If user is in search mode, treat this as query
    if USER_STATE.get(msg.from_user.id) == "search":
        USER_STATE.pop(msg.from_user.id, None)
        results = search_all(msg.text)
        if not results:
            await msg.answer("چیزی پیدا نشد. عبارت دقیق‌تری امتحان کن.", reply_markup=main_menu())
            return
        await msg.answer("نتایج جستجو:", reply_markup=search_results_kb(results))
        return
    # fallback
    await msg.answer("برای شروع از منوی زیر استفاده کن:", reply_markup=main_menu())

@dp.callback_query(F.data == "search_start")
async def search_start(cb: CallbackQuery):
    USER_STATE[cb.from_user.id] = "search"
    await safe_edit(cb.message, "🔎 عبارت جستجو رو بفرست (عنوان، توضیح، قطعه، برد و ...)")
    await cb.answer()

@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery):
    await safe_edit(cb.message, "🔙 بازگشت به منوی اصلی:", reply_markup=main_menu())
    await cb.answer()

@dp.callback_query(F.data.startswith("back_projlist_"))
async def back_projlist(cb: CallbackQuery):
    cat = cb.data.split("_", 2)[2]
    await safe_edit(cb.message, f"🔙 بازگشت به لیست پروژه‌های {cat}:", reply_markup=list_projects(cat))
    await cb.answer()

@dp.callback_query(F.data.startswith("cat_"))
async def open_category(cb: CallbackQuery):
    cat = cb.data.split("_", 1)[1]
    if cat == "robotics":
        await safe_edit(cb.message, "🤖 پروژه‌های رباتیک:", reply_markup=list_projects("robotics"))
    elif cat == "iot":
        await safe_edit(cb.message, "🌐 پروژه‌های اینترنت اشیا:", reply_markup=list_projects("iot"))
    elif cat == "libs":
        await safe_edit(cb.message, "🐍 کتابخانه‌های پایتون:", reply_markup=list_libs())
    await cb.answer()

@dp.callback_query(F.data.startswith("proj_"))
async def project_detail(cb: CallbackQuery):
    _, cat, proj_id = cb.data.split("_", 2)
    items = safe_get_items_by_cat(cat)
    proj = next((p for p in items if str(p.get("id")) == proj_id), None)
    if not proj:
        await cb.answer("❌ پروژه پیدا نشد", show_alert=True)
        return

    title_h = _html.escape(proj.get("title", ""))
    desc_h  = _html.escape(proj.get("description", ""))
    boards_h = _html.escape(", ".join(proj.get("boards", []) or []))
    parts_h  = _html.escape(", ".join(proj.get("parts", []) or []))

    text = f"""📌 <b>{title_h}</b>

{desc_h}

⚡️ بوردها: {boards_h or '—'}
🧩 قطعات: {parts_h or '—'}"""

    await safe_edit(cb.message, text, reply_markup=code_menu(cat, proj_id, proj, current_lang=None))
    await cb.answer()

@dp.callback_query(F.data.startswith("code_"))
async def send_code(cb: CallbackQuery):
    # robust parsing: allow proj_id to contain underscores
    prefix, lang = cb.data.rsplit("_", 1)        # e.g. code_robotics_rb_line_follower_c -> prefix, 'c'
    _, cat, proj_id = prefix.split("_", 2)       # -> cat='robotics', proj_id='rb_line_follower'

    items = safe_get_items_by_cat(cat)
    proj  = next((p for p in items if str(p.get("id")) == proj_id), None)
    if not proj:
        await cb.answer("❌ پروژه پیدا نشد", show_alert=True)
        return

    code_raw = (proj.get("code") or {}).get(lang)
    if not code_raw:
        await cb.answer("کدی برای این زبان موجود نیست", show_alert=True)
        return

    title_h = _html.escape(proj.get("title", ""))
    code_h  = _html.escape(code_raw)

    header = f"📌 <b>{title_h}</b> - {lang.upper()}\n\n"
    html_block = f"<pre><code>{code_h}</code></pre>"
    text = header + html_block

    if len(text) <= 3500:
        await safe_edit(cb.message, text, reply_markup=code_menu(cat, proj_id, proj, current_lang=lang))
    else:
        # اگر خیلی بلند بود، مستقیم فایل بده و پیام کوتاه بماند
        filename = f"{proj.get('title','project')}_{lang}.txt".replace(" ", "_")
        doc = BufferedInputFile(code_raw.encode("utf-8"), filename=filename)
        await cb.message.answer_document(
            document=doc,
            caption=f"📌 {proj.get('title','')} - {lang.upper()}",
            reply_markup=code_menu(cat, proj_id, proj, current_lang=lang),
        )
    await cb.answer()

# ---------------------------- Downloads (single lang ONLY when viewing) ----------------------------
def _lang_filename(title: str, lang: str) -> str:
    base = (title or "project").replace(" ", "_")
    ext = {"c": ".c", "cpp": ".cpp", "micropython": ".py"}.get(lang, ".txt")
    return f"{base}{ext}"

@dp.callback_query(F.data.startswith("dls_"))
async def download_single(cb: CallbackQuery):
    # robust parsing: allow proj_id to contain underscores
    prefix, lang = cb.data.rsplit("_", 1)        # e.g. dls_robotics_rb_line_follower_c -> prefix, 'c'
    _, cat, proj_id = prefix.split("_", 2)

    items = safe_get_items_by_cat(cat)
    proj  = next((p for p in items if str(p.get("id")) == proj_id), None)
    if not proj:
        await cb.answer("❌ پروژه پیدا نشد", show_alert=True)
        return

    code_raw = (proj.get("code") or {}).get(lang)
    if not code_raw:
        await cb.answer("برای این زبان کدی موجود نیست", show_alert=True)
        return

    filename = _lang_filename(proj.get("title", "project"), lang)
    file = BufferedInputFile(code_raw.encode("utf-8"), filename=filename)
    await cb.message.answer_document(file, caption=f"⬇️ {proj.get('title','')} — {lang.upper()}")
    await cb.answer()

# ---------------------------- Libraries: details + downloads ----------------------------
@dp.callback_query(F.data.startswith("lib_"))
async def lib_detail(cb: CallbackQuery):
    lib_name = cb.data.split("_", 1)[1]
    lib = next((l for l in py_libs if l.get("name") == lib_name), None)
    if not lib:
        await cb.answer("❌ کتابخانه پیدا نشد", show_alert=True)
        return

    CURRENT_LIB[cb.from_user.id] = lib_name

    name_h    = _html.escape(lib.get("name", ""))
    cat_h     = _html.escape(lib.get("category", ""))
    desc_h    = _html.escape(lib.get("description", ""))
    install_h = _html.escape(lib.get("install", ""))
    example_h = _html.escape(lib.get("example", ""))

    text = (
        f"🐍 <b>{name_h}</b>\n"
        f"📂 دسته: {cat_h}\n\n"
        f"{desc_h}\n\n"
        f"📦 نصب:\n<code>{install_h}</code>\n\n"
        f"💡 مثال:\n<pre><code>{example_h}</code></pre>"
    )
    await safe_edit(cb.message, text, reply_markup=back_to_libs())
    await cb.answer()

@dp.callback_query(F.data == "dllib_example")
async def dllib_example(cb: CallbackQuery):
    name = CURRENT_LIB.get(cb.from_user.id)
    lib = next((l for l in py_libs if l.get("name") == name), None)
    if not lib:
        await cb.answer("❌ پیدا نشد", show_alert=True)
        return
    example = lib.get("example") or ""
    file = BufferedInputFile(example.encode("utf-8"), filename=f"{name}_example.py")
    await cb.message.answer_document(file, caption=f"⬇️ مثال {name}")
    await cb.answer()

@dp.callback_query(F.data == "dllib_json")
async def dllib_json(cb: CallbackQuery):
    name = CURRENT_LIB.get(cb.from_user.id)
    lib = next((l for l in py_libs if l.get("name") == name), None)
    if not lib:
        await cb.answer("❌ پیدا نشد", show_alert=True)
        return
    data = json.dumps(lib, ensure_ascii=False, indent=2)
    file = BufferedInputFile(data.encode("utf-8"), filename=f"{name}.json")
    await cb.message.answer_document(file, caption=f"🧾 JSON — {name}")
    await cb.answer()

# ---------------------------- Webhook lifecycle ----------------------------
async def on_startup(app: web.Application):
    await bot.set_webhook(f"{PUBLIC_URL}/webhook", secret_token=WEBHOOK_SECRET)
    logger.info("✅ Webhook set: %s/webhook", PUBLIC_URL)

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("🧹 Webhook deleted and session closed")

# ---------------------------- WebApp ----------------------------
def build_app():
    app = web.Application()

    async def root_get(_):
        return web.Response(text="Bot is running!")

    app.router.add_get("/", root_get)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    ).register(app, path="/webhook")

    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

# ---------------------------- Run ----------------------------
if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=PORT)
