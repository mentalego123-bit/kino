import asyncio
import sqlite3
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# ================= SOZLAMALAR =================
BOT_TOKEN = "8998624190:AAGMbIYyTE7uCKlkQZOcGRdyoy9g4UnGAro"
MAIN_ADMIN_ID = 8355669630
ADMIN_USERNAME = "smart_gemini"
DB_PATH = "kino_bot.db"   # eski baza fayli shu nom bilan bo'lsa, o'sha bilan ishlaydi

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= SQLITE BAZA =================
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()


def db_exec(query, params=()):
    cur.execute(query, params)
    conn.commit()
    return cur


def db_one(query, params=()):
    cur.execute(query, params)
    return cur.fetchone()


def db_all(query, params=()):
    cur.execute(query, params)
    return cur.fetchall()


def init_db():
    db_exec("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        is_vip INTEGER DEFAULT 0,
        vip_expiry TEXT,
        joined_at TEXT
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS admins(
        user_id INTEGER PRIMARY KEY
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS movies(
        code TEXT PRIMARY KEY,
        file_id TEXT,
        caption TEXT,
        views INTEGER DEFAULT 0,
        added_at TEXT
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS channels(
        chat_id TEXT PRIMARY KEY,
        url TEXT,
        name TEXT,
        is_private INTEGER DEFAULT 0
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        query TEXT,
        created_at TEXT
    )""")

    # boshlang'ich adminlar
    if not db_one("SELECT 1 FROM admins WHERE user_id=?", (MAIN_ADMIN_ID,)):
        db_exec("INSERT INTO admins(user_id) VALUES(?)", (MAIN_ADMIN_ID,))

    # boshlang'ich sozlamalar
    defaults = {
        "vip_price": "10000",
        "sub_text": "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling!",
        "channels_required": "1",  # 1 = majburiy obuna yoqilgan, 0 = ochirilgan
    }
    for k, v in defaults.items():
        if not db_one("SELECT 1 FROM settings WHERE key=?", (k,)):
            db_exec("INSERT INTO settings(key, value) VALUES(?,?)", (k, v))

    # standart yopiq (maxfiy) kanal - foydalanuvchi bergan link
    if not db_one("SELECT 1 FROM channels"):
        db_exec(
            "INSERT INTO channels(chat_id, url, name, is_private) VALUES(?,?,?,?)",
            ("-1003297745646", "https://t.me/+t30YnzAM5iFlNGVk", "Yopiq VIP kanal", 1),
        )


def get_setting(key, default=None):
    row = db_one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key, value):
    db_exec(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def is_admin(user_id):
    return bool(db_one("SELECT 1 FROM admins WHERE user_id=?", (user_id,)))


def ensure_user(user: types.User):
    row = db_one("SELECT 1 FROM users WHERE user_id=?", (user.id,))
    if not row:
        db_exec(
            "INSERT INTO users(user_id, username, full_name, joined_at) VALUES(?,?,?,?)",
            (user.id, user.username or "", user.full_name, datetime.now().isoformat()),
        )
    else:
        db_exec(
            "UPDATE users SET username=?, full_name=? WHERE user_id=?",
            (user.username or "", user.full_name, user.id),
        )


def is_vip(user_id) -> bool:
    row = db_one("SELECT is_vip, vip_expiry FROM users WHERE user_id=?", (user_id,))
    if not row or not row["is_vip"]:
        return False
    expiry = row["vip_expiry"]
    if expiry:
        try:
            if datetime.now() > datetime.fromisoformat(expiry):
                db_exec("UPDATE users SET is_vip=0, vip_expiry=NULL WHERE user_id=?", (user_id,))
                return False
        except ValueError:
            pass
    return True


def set_vip(user_id, days=30):
    expiry = (datetime.now() + timedelta(days=days)).isoformat()
    db_exec("UPDATE users SET is_vip=1, vip_expiry=? WHERE user_id=?", (expiry, user_id))


def remove_vip(user_id):
    db_exec("UPDATE users SET is_vip=0, vip_expiry=NULL WHERE user_id=?", (user_id,))


# ================= FSM HOLATLAR =================
class AdminState(StatesGroup):
    waiting_movie_code = State()
    waiting_movie_file = State()
    waiting_movie_caption = State()
    waiting_broadcast = State()
    waiting_channel_id = State()
    waiting_channel_url = State()
    waiting_channel_name = State()
    waiting_remove_channel = State()
    waiting_new_admin = State()
    waiting_delete_movie = State()
    waiting_vip_id = State()
    waiting_vip_price = State()
    waiting_sub_text = State()


class UserState(StatesGroup):
    waiting_order = State()


# ================= KLAVIATURALAR =================
def main_menu(user_id):
    kb = [
        [KeyboardButton(text="🎬 Kino kodini yozish")],
        [KeyboardButton(text="🌟 VIP haqida"), KeyboardButton(text="📝 Kino buyurtma qilish")],
    ]
    if is_admin(user_id):
        kb.append([KeyboardButton(text="👨‍💻 Admin panel")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def admin_panel_markup():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Kino qo'shish", callback_data="adm_add_movie")],
        [InlineKeyboardButton(text="🗑 Kino o'chirish", callback_data="adm_del_movie")],
        [InlineKeyboardButton(text="📢 Xabar yuborish (broadcast)", callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="📡 Kanallar", callback_data="adm_channels_menu")],
        [InlineKeyboardButton(text="🌟 VIP boshqaruvi", callback_data="adm_vip_menu")],
        [InlineKeyboardButton(text="👤 Foydalanuvchilar", callback_data="adm_users_list")],
        [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="adm_add_admin")],
        [InlineKeyboardButton(text="💰 VIP narxini o'zgartirish", callback_data="adm_set_price")],
    ])


def channels_menu_markup():
    required = get_setting("channels_required", "1") == "1"
    toggle_text = "🔴 Majburiy obunani o'chirish" if required else "🟢 Majburiy obunani yoqish"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data="adm_toggle_channels")],
        [InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="adm_add_channel")],
        [InlineKeyboardButton(text="➖ Kanal o'chirish", callback_data="adm_remove_channel")],
        [InlineKeyboardButton(text="📋 Kanallar ro'yxati", callback_data="adm_list_channels")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_back_main")],
    ])


async def get_sub_markup(user_id):
    """Majburiy kanallar uchun tugmalar. VIP bo'lsa None qaytaradi (shart emas)."""
    if is_vip(user_id):
        return None
    if get_setting("channels_required", "1") != "1":
        return None
    channels = db_all("SELECT * FROM channels")
    if not channels:
        return None
    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(text=f"📢 {ch['name']}", url=ch["url"])])
    buttons.append([InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def check_user_subscription(user_id) -> bool:
    if is_vip(user_id):
        return True
    if get_setting("channels_required", "1") != "1":
        return True
    channels = db_all("SELECT * FROM channels")
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=int(ch["chat_id"]), user_id=user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            # kanalni tekshirib bo'lmasa (bot admin emas va h.k.) o'tkazib yuboramiz
            continue
    return True


# ================= START =================
@dp.message(CommandStart(), StateFilter(None))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    ensure_user(message.from_user)
    ok = await check_user_subscription(message.from_user.id)
    if not ok:
        markup = await get_sub_markup(message.from_user.id)
        await message.answer(
            f"👋 Salom, {message.from_user.full_name}!\n\n"
            f"{get_setting('sub_text')}\n\n"
            f"Obuna bo'lgach, pastdagi tugmani bosing.",
            reply_markup=markup,
        )
        return
    await message.answer(
        "🎬 <b>Premium Kino Botga xush kelibsiz!</b>\n\n"
        "Kino kodini yuboring yoki tugmalardan foydalaning.",
        reply_markup=main_menu(message.from_user.id),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery):
    ok = await check_user_subscription(callback.from_user.id)
    if ok:
        await callback.message.delete()
        await callback.message.answer(
            "✅ Obuna tasdiqlandi! Endi botdan foydalanishingiz mumkin.",
            reply_markup=main_menu(callback.from_user.id),
        )
    else:
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)


@dp.message(F.text == "🔙 Orqaga")
async def go_back_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Bosh menyu", reply_markup=main_menu(message.from_user.id))


# ================= VIP HAQIDA =================
@dp.message(StateFilter(None), F.text == "🌟 VIP haqida")
async def vip_info(message: types.Message):
    price = get_setting("vip_price", "10000")
    vip_status = "✅ Faol" if is_vip(message.from_user.id) else "❌ Yo'q"
    text = (
        "🌟 <b>VIP OBUNA</b>\n\n"
        f"💰 Narxi: <b>{price} so'm</b> / 1 oy\n\n"
        "✨ <b>VIP imtiyozlari:</b>\n"
        "• Majburiy kanallarga obuna bo'lish shart emas\n"
        "• Kinolarni forward qilish mumkin\n"
        "• Kinolarni yuklab olish (download) mumkin\n"
        "• Kinolarni tez va cheklovsiz olish\n\n"
        f"👤 Sizning VIP holatingiz: {vip_status}\n\n"
        f"VIP olish uchun adminga yozing: @{ADMIN_USERNAME}"
    )
    await message.answer(text, parse_mode="HTML")


# ================= KINO BUYURTMA =================
@dp.message(StateFilter(None), F.text == "📝 Kino buyurtma qilish")
async def order_movie_step1(message: types.Message, state: FSMContext):
    if not await check_user_subscription(message.from_user.id):
        await start_cmd(message, state)
        return
    await message.answer("🎬 Qidirayotgan kino nomini yozing:")
    await state.set_state(UserState.waiting_order)


@dp.message(UserState.waiting_order)
async def order_movie_step2(message: types.Message, state: FSMContext):
    db_exec(
        "INSERT INTO requests(user_id, query, created_at) VALUES(?,?,?)",
        (message.from_user.id, message.text, datetime.now().isoformat()),
    )
    await message.answer(
        "✅ So'rovingiz qabul qilindi!\n"
        "Kino 24 soat ichida qidirilib, sizga topib beriladi.",
        reply_markup=main_menu(message.from_user.id),
    )
    await state.clear()
    try:
        await bot.send_message(
            MAIN_ADMIN_ID,
            f"🆕 Yangi kino so'rovi!\n"
            f"👤 @{message.from_user.username} (ID: {message.from_user.id})\n"
            f"🎬 So'rov: {message.text}",
        )
    except Exception:
        pass


# ================= KINO QIDIRISH (KOD ORQALI) =================
@dp.message(StateFilter(None), F.text == "🎬 Kino kodini yozish")
async def ask_code(message: types.Message):
    await message.answer("🔢 Kino kodini kiriting:")


@dp.message(StateFilter(None), lambda msg: msg.text and not msg.text.startswith("/"))
async def search_movie(message: types.Message):
    text = message.text.strip()
    # Menyudagi tugma matnlariga tegmaslik uchun
    menu_texts = {"🎬 Kino kodini yozish", "🌟 VIP haqida", "📝 Kino buyurtma qilish", "👨‍💻 Admin panel", "🔙 Orqaga"}
    if text in menu_texts:
        return

    if not await check_user_subscription(message.from_user.id):
        await start_cmd(message, FSMContext.__new__(FSMContext))  # fallback, holat yo'q
        return

    movie = db_one("SELECT * FROM movies WHERE code=?", (text,))
    if not movie:
        await message.answer(
            "❌ Bunday kodli kino topilmadi.\n"
            "Agar kino nomi bilan qidirmoqchi bo'lsangiz, \"📝 Kino buyurtma qilish\" tugmasidan foydalaning."
        )
        return

    user_vip = is_vip(message.from_user.id)
    db_exec("UPDATE movies SET views = views + 1 WHERE code=?", (text,))
    try:
        await bot.send_video(
            chat_id=message.chat.id,
            video=movie["file_id"],
            caption=movie["caption"] or f"🎬 Kod: {text}",
            protect_content=not user_vip,  # faqat VIP forward/yuklab olishi mumkin
        )
        if not user_vip:
            await message.answer(
                "ℹ️ Bu kinoni forward qilish va yuklab olish faqat VIP a'zolar uchun ochiq.\n"
                f"VIP olish uchun: @{ADMIN_USERNAME}"
            )
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")


# ================= ADMIN PANEL =================
@dp.message(Command("admin"), StateFilter(None))
@dp.message(StateFilter(None), F.text == "👨‍💻 Admin panel")
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("👨‍💻 <b>Boshqaruv paneli</b>", reply_markup=admin_panel_markup(), parse_mode="HTML")


@dp.callback_query(F.data == "adm_back_main")
async def adm_back_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("👨‍💻 <b>Boshqaruv paneli</b>", reply_markup=admin_panel_markup(), parse_mode="HTML")


# ---- Kino qo'shish ----
@dp.callback_query(F.data == "adm_add_movie")
async def adm_add_movie(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🔢 Kino uchun kod kiriting (masalan: 1001):")
    await state.set_state(AdminState.waiting_movie_code)


@dp.message(AdminState.waiting_movie_code)
async def adm_movie_code(message: types.Message, state: FSMContext):
    await state.update_data(code=message.text.strip())
    await message.answer("🎥 Endi kino faylini (video) yuboring:")
    await state.set_state(AdminState.waiting_movie_file)


@dp.message(AdminState.waiting_movie_file, F.video)
async def adm_movie_file(message: types.Message, state: FSMContext):
    await state.update_data(file_id=message.video.file_id)
    await message.answer("✍️ Kino uchun tavsif (caption) yozing (yoki '-' deb yozing):")
    await state.set_state(AdminState.waiting_movie_caption)


@dp.message(AdminState.waiting_movie_caption)
async def adm_movie_caption(message: types.Message, state: FSMContext):
    data = await state.get_data()
    caption = "" if message.text.strip() == "-" else message.text.strip()
    db_exec(
        "INSERT INTO movies(code, file_id, caption, added_at) VALUES(?,?,?,?) "
        "ON CONFLICT(code) DO UPDATE SET file_id=excluded.file_id, caption=excluded.caption",
        (data["code"], data["file_id"], caption, datetime.now().isoformat()),
    )
    await message.answer(f"✅ Kino saqlandi! Kod: <b>{data['code']}</b>", parse_mode="HTML")
    await state.clear()


# ---- Kino o'chirish ----
@dp.callback_query(F.data == "adm_del_movie")
async def adm_del_movie(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🗑 O'chiriladigan kino kodini kiriting:")
    await state.set_state(AdminState.waiting_delete_movie)


@dp.message(AdminState.waiting_delete_movie)
async def adm_del_movie_step2(message: types.Message, state: FSMContext):
    db_exec("DELETE FROM movies WHERE code=?", (message.text.strip(),))
    await message.answer("✅ O'chirildi (agar mavjud bo'lsa).")
    await state.clear()


# ---- Broadcast ----
@dp.callback_query(F.data == "adm_broadcast")
async def adm_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 Barcha foydalanuvchilarga yuboriladigan xabarni yozing:")
    await state.set_state(AdminState.waiting_broadcast)


@dp.message(AdminState.waiting_broadcast)
async def adm_broadcast_step2(message: types.Message, state: FSMContext):
    users = db_all("SELECT user_id FROM users")
    sent, failed = 0, 0
    await message.answer(f"⏳ {len(users)} foydalanuvchiga yuborilmoqda...")
    for u in users:
        try:
            await message.copy_to(u["user_id"])
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await message.answer(f"✅ Yuborildi: {sent} | ❌ Xato: {failed}")
    await state.clear()


# ---- Kanallar menyusi ----
@dp.callback_query(F.data == "adm_channels_menu")
async def adm_channels_menu(callback: types.CallbackQuery):
    await callback.message.edit_text("📡 <b>Kanallar boshqaruvi</b>", reply_markup=channels_menu_markup(), parse_mode="HTML")


@dp.callback_query(F.data == "adm_toggle_channels")
async def adm_toggle_channels(callback: types.CallbackQuery):
    cur_val = get_setting("channels_required", "1")
    new_val = "0" if cur_val == "1" else "1"
    set_setting("channels_required", new_val)
    status = "yoqildi ✅" if new_val == "1" else "o'chirildi ❌"
    await callback.answer(f"Majburiy obuna {status}", show_alert=True)
    await callback.message.edit_text("📡 <b>Kanallar boshqaruvi</b>", reply_markup=channels_menu_markup(), parse_mode="HTML")


@dp.callback_query(F.data == "adm_add_channel")
async def adm_add_channel(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📡 Kanal chat_id sini kiriting.\n"
        "(Oddiy kanal uchun @username yoki -100... ID, yopiq kanal uchun -100... ID kerak)"
    )
    await state.set_state(AdminState.waiting_channel_id)


@dp.message(AdminState.waiting_channel_id)
async def adm_add_channel_id(message: types.Message, state: FSMContext):
    await state.update_data(chat_id=message.text.strip())
    await message.answer("🔗 Kanal linkini kiriting (masalan https://t.me/... yoki https://t.me/+... yopiq kanal uchun):")
    await state.set_state(AdminState.waiting_channel_url)


@dp.message(AdminState.waiting_channel_url)
async def adm_add_channel_url(message: types.Message, state: FSMContext):
    await state.update_data(url=message.text.strip())
    await message.answer("📝 Kanal nomini kiriting:")
    await state.set_state(AdminState.waiting_channel_name)


@dp.message(AdminState.waiting_channel_name)
async def adm_add_channel_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    is_private = 1 if "+t30YnzAM5iFlNGVk" in data["url"] or "+" in data["url"] else 0
    db_exec(
        "INSERT INTO channels(chat_id, url, name, is_private) VALUES(?,?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET url=excluded.url, name=excluded.name, is_private=excluded.is_private",
        (data["chat_id"], data["url"], message.text.strip(), is_private),
    )
    await message.answer("✅ Kanal qo'shildi!")
    await state.clear()


@dp.callback_query(F.data == "adm_remove_channel")
async def adm_remove_channel(callback: types.CallbackQuery, state: FSMContext):
    channels = db_all("SELECT * FROM channels")
    if not channels:
        await callback.answer("Kanallar mavjud emas", show_alert=True)
        return
    text = "\n".join([f"{c['chat_id']} — {c['name']}" for c in channels])
    await callback.message.answer(f"📋 Kanallar:\n{text}\n\nO'chirish uchun chat_id kiriting:")
    await state.set_state(AdminState.waiting_remove_channel)


@dp.message(AdminState.waiting_remove_channel)
async def adm_remove_channel_step2(message: types.Message, state: FSMContext):
    db_exec("DELETE FROM channels WHERE chat_id=?", (message.text.strip(),))
    await message.answer("✅ Kanal o'chirildi (agar mavjud bo'lsa).")
    await state.clear()


@dp.callback_query(F.data == "adm_list_channels")
async def adm_list_channels(callback: types.CallbackQuery):
    channels = db_all("SELECT * FROM channels")
    if not channels:
        await callback.answer("Kanallar yo'q", show_alert=True)
        return
    text = "📋 <b>Kanallar ro'yxati:</b>\n\n"
    for c in channels:
        tur = "🔒 Yopiq" if c["is_private"] else "🔓 Ochiq"
        text += f"{tur} | {c['name']} | <code>{c['chat_id']}</code>\n{c['url']}\n\n"
    await callback.message.answer(text, parse_mode="HTML")


# ---- VIP boshqaruvi ----
@dp.callback_query(F.data == "adm_vip_menu")
async def adm_vip_menu(callback: types.CallbackQuery):
    price = get_setting("vip_price", "10000")
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ VIP berish", callback_data="adm_give_vip")],
        [InlineKeyboardButton(text="➖ VIP olib tashlash", callback_data="adm_take_vip")],
        [InlineKeyboardButton(text="📋 VIP a'zolar ro'yxati", callback_data="adm_vip_list")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_back_main")],
    ])
    await callback.message.edit_text(f"🌟 <b>VIP boshqaruvi</b>\nNarx: {price} so'm", reply_markup=markup, parse_mode="HTML")


@dp.callback_query(F.data == "adm_give_vip")
async def adm_give_vip(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("👤 VIP beriladigan foydalanuvchi ID sini kiriting:")
    await state.update_data(vip_action="give")
    await state.set_state(AdminState.waiting_vip_id)


@dp.callback_query(F.data == "adm_take_vip")
async def adm_take_vip(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("👤 VIP olib tashlanadigan foydalanuvchi ID sini kiriting:")
    await state.update_data(vip_action="take")
    await state.set_state(AdminState.waiting_vip_id)


@dp.message(AdminState.waiting_vip_id)
async def adm_vip_id_step(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Noto'g'ri ID.")
        return
    if not db_one("SELECT 1 FROM users WHERE user_id=?", (uid,)):
        await message.answer("❌ Bunday foydalanuvchi botda ro'yxatdan o'tmagan.")
        await state.clear()
        return
    if data.get("vip_action") == "give":
        set_vip(uid, days=30)
        await message.answer(f"✅ {uid} foydalanuvchiga 1 oylik VIP berildi!")
        try:
            await bot.send_message(uid, "🎉 Tabriklaymiz! Sizga 1 oylik VIP obuna berildi.")
        except Exception:
            pass
    else:
        remove_vip(uid)
        await message.answer(f"✅ {uid} foydalanuvchidan VIP olib tashlandi.")
        try:
            await bot.send_message(uid, "ℹ️ Sizning VIP obunangiz bekor qilindi.")
        except Exception:
            pass
    await state.clear()


@dp.callback_query(F.data == "adm_vip_list")
async def adm_vip_list(callback: types.CallbackQuery):
    rows = db_all("SELECT * FROM users WHERE is_vip=1")
    if not rows:
        await callback.answer("VIP a'zolar yo'q", show_alert=True)
        return
    text = "🌟 <b>VIP a'zolar:</b>\n\n"
    for r in rows:
        text += f"👤 @{r['username']} | ID: <code>{r['user_id']}</code> | tugaydi: {r['vip_expiry']}\n"
    await callback.message.answer(text, parse_mode="HTML")


# ---- Foydalanuvchilar ro'yxati ----
@dp.callback_query(F.data == "adm_users_list")
async def adm_users_list(callback: types.CallbackQuery):
    rows = db_all("SELECT * FROM users ORDER BY joined_at DESC LIMIT 50")
    if not rows:
        await callback.answer("Foydalanuvchilar yo'q", show_alert=True)
        return
    text = "👤 <b>Foydalanuvchilar (oxirgi 50 ta):</b>\n\n"
    for r in rows:
        vip_mark = "🌟" if r["is_vip"] else ""
        text += f"{vip_mark} @{r['username'] or '-'} | ID: <code>{r['user_id']}</code>\n"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.message.answer(
        "VIP belgilash uchun 'VIP boshqaruvi' bo'limidan foydalaning va kerakli ID kiriting."
    )


# ---- Admin qo'shish ----
@dp.callback_query(F.data == "adm_add_admin")
async def adm_add_admin(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != MAIN_ADMIN_ID:
        await callback.answer("Faqat asosiy admin qo'sha oladi!", show_alert=True)
        return
    await callback.message.answer("👤 Yangi admin ID sini kiriting:")
    await state.set_state(AdminState.waiting_new_admin)


@dp.message(AdminState.waiting_new_admin)
async def adm_add_admin_step2(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        db_exec("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (uid,))
        await message.answer(f"✅ {uid} admin qilib tayinlandi.")
    except ValueError:
        await message.answer("❌ Noto'g'ri ID.")
    await state.clear()


# ---- VIP narxini o'zgartirish ----
@dp.callback_query(F.data == "adm_set_price")
async def adm_set_price(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("💰 Yangi VIP narxini kiriting (faqat son, so'mda):")
    await state.set_state(AdminState.waiting_vip_price)


@dp.message(AdminState.waiting_vip_price)
async def adm_set_price_step2(message: types.Message, state: FSMContext):
    if message.text.strip().isdigit():
        set_setting("vip_price", message.text.strip())
        await message.answer(f"✅ VIP narxi {message.text.strip()} so'mga o'zgartirildi.")
    else:
        await message.answer("❌ Faqat son kiriting.")
    await state.clear()


# ---- Forward himoyasi: har qanday forward qilingan xabar (video/rasm/fayl) ----
@dp.message(F.forward_date | F.forward_from | F.forward_from_chat)
async def block_forward_content_upload(message: types.Message):
    # Bu asosan userlardan botga forward qilingan kontentni bloklaydi (admin bo'lmasa)
    if is_admin(message.from_user.id):
        return
    if not is_vip(message.from_user.id):
        await message.answer(
            "🚫 Forward qilingan kontentlarni yuborish faqat VIP a'zolar uchun ruxsat etilgan.\n"
            f"VIP olish uchun: @{ADMIN_USERNAME}"
        )


# ================= ISHGA TUSHIRISH =================
async def main():
    init_db()
    print("✅ SQLite bazasi tayyor:", DB_PATH)
    print("🤖 Bot ishga tushmoqda...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
