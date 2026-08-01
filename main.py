import asyncio
import sqlite3
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from fpdf import FPDF

# ================= SOZLAMALAR =================
BOT_TOKEN = "8998624190:AAGMbIYyTE7uCKlkQZOcGRdyoy9g4UnGAro" 
MAIN_ADMIN_ID = 8355669630

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= FSM HOLATLAR (KUTISH) =================
class AdminState(StatesGroup):
    waiting_for_movie = State()
    waiting_for_movie_code = State()
    waiting_for_is_paid = State()
    waiting_for_price = State()
    waiting_for_movie_caption = State()
    waiting_for_broadcast = State()
    waiting_for_channel_id = State()
    waiting_for_channel_url = State()
    waiting_for_sub_text = State()
    waiting_for_new_admin = State()
    waiting_for_delete_movie = State()

# ================= MA'LUMOTLAR BAZASI =================
def init_db():
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, joined_date TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY)''')
    
    # KINOLAR JADVALI (YANGI QATORLAR QO'SHILDI: is_paid, price)
    cursor.execute('''CREATE TABLE IF NOT EXISTS movies (
        code TEXT PRIMARY KEY, 
        file_id TEXT, 
        type TEXT, 
        caption TEXT, 
        views INTEGER DEFAULT 0, 
        added_date TEXT,
        is_paid INTEGER DEFAULT 0,
        price INTEGER DEFAULT 0
    )''')
    
    # Eski baza mavjud bo'lsa, xato bermasligi uchun yangi ustunlarni qo'shib tekshiramiz
    try:
        cursor.execute("ALTER TABLE movies ADD COLUMN is_paid INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE movies ADD COLUMN price INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    cursor.execute('''CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY, url TEXT, name TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER, movie_code TEXT, UNIQUE(user_id, movie_code))''')
    
    cursor.execute("INSERT OR IGNORE INTO admins (id) VALUES (?)", (MAIN_ADMIN_ID,))
    
    default_text = "Botdan to'liq foydalanish va kinolarni ko'rish uchun quyidagi kanallarga obuna bo'lishingiz shart!"
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('sub_text', ?)", (default_text,))
    
    conn.commit()
    conn.close()

def is_admin(user_id):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM admins WHERE id=?", (user_id,))
    admin = cursor.fetchone()
    conn.close()
    return bool(admin)

# ================= MAJBURIY OBUNA =================
async def get_sub_markup(user_id):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, url, name FROM channels")
    channels = cursor.fetchall()
    conn.close()
    
    unsubscribed = []
    for ch_id, url, name in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                unsubscribed.append((name, url))
        except Exception:
            continue
            
    if not unsubscribed:
        return None
        
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for name, url in unsubscribed:
        markup.inline_keyboard.append([InlineKeyboardButton(text=f"📢 {name}", url=url)])
    markup.inline_keyboard.append([InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_sub")])
    return markup

# ================= ASOSIY MENYU =================
def main_menu():
    markup = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔥 Top kinolar"), KeyboardButton(text="🆕 Yangi kinolar")],
            [KeyboardButton(text="🎲 Tasodifiy kino"), KeyboardButton(text="❤️ Sevimlilar")],
        ],
        resize_keyboard=True
    )
    return markup

# ================= FOYDALANUVCHI QISMI =================
@dp.message(CommandStart(), StateFilter(None))
async def start_cmd(message: types.Message):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (id, joined_date) VALUES (?, ?)", 
                   (message.from_user.id, datetime.now().strftime("%Y-%m-%d %H:%M")))
    
    cursor.execute("SELECT value FROM settings WHERE key='sub_text'")
    sub_text = cursor.fetchone()[0]
    conn.commit()
    conn.close()

    markup = await get_sub_markup(message.from_user.id)
    if markup:
        await message.answer(sub_text, reply_markup=markup)
        return

    await message.answer("Assalomu aleykum, kino kodini orqali qidiring 👇", reply_markup=main_menu())

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery):
    markup = await get_sub_markup(callback.from_user.id)
    if markup:
        await callback.answer("Siz hamma kanallarga obuna bo'lmagansiz!", show_alert=True)
    else:
        await callback.message.delete()
        await callback.message.answer("Assalomu aleykum, kino kodini orqali qidiring 👇", reply_markup=main_menu())

# --- KINO QIDIRISH ---
@dp.message(StateFilter(None), lambda msg: msg.text and msg.text.isdigit())
async def search_movie(message: types.Message):
    markup = await get_sub_markup(message.from_user.id)
    if markup:
        await message.answer("Avval kanallarga obuna bo'ling!", reply_markup=markup)
        return

    code = message.text.strip()
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT file_id, type, caption, is_paid, price FROM movies WHERE code=?", (code,))
    movie = cursor.fetchone()
    
    if not movie:
        conn.close()
        await message.answer("Unday kino topilmadi iltimos @kinolaruzhub dan qidirb ko'ring.")
        return

    cursor.execute("UPDATE movies SET views = views + 1 WHERE code=?", (code,))
    conn.commit()
    conn.close()

    file_id, msg_type, caption, is_paid, price = movie
    
    # PULLIK KINO TEKSHIRUVI
    if is_paid:
        await message.answer(
            f"🔒 <b>Bu pullik kino!</b>\n\n"
            f"🎬 Kino kodi: <code>{code}</code>\n"
            f"💰 Narxi: <b>{price} so'm</b>\n\n"
            f"📩 <i>Kino faylini qabul qilib olish va to'lov qilish uchun bot adminiga murojaat qiling.</i>",
            parse_mode="HTML"
        )
        return

    fav_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Sevimlilarga qo'shish", callback_data=f"fav_{code}")]
    ])

    if msg_type == 'video':
        await message.answer_video(video=file_id, caption=caption, reply_markup=fav_btn)
    elif msg_type == 'document':
        await message.answer_document(document=file_id, caption=caption, reply_markup=fav_btn)
    elif msg_type == 'photo':
        await message.answer_photo(photo=file_id, caption=caption, reply_markup=fav_btn)

# --- YANGI FUNKSIYALAR: TOP VA YANGI KINOLAR ---
@dp.message(StateFilter(None), F.text == "🔥 Top kinolar")
async def top_movies(message: types.Message):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code, caption, views, is_paid FROM movies ORDER BY views DESC LIMIT 10")
    movies = cursor.fetchall()
    conn.close()

    if not movies:
        await message.answer("Hozircha bazada kinolar yo'q.")
        return
        
    text = "🔥 <b>Eng ko'p qidirilgan kinolar:</b>\n\n"
    for i, (code, caption, views, is_paid) in enumerate(movies, 1):
        cap_short = caption[:20] + "..." if caption and len(caption) > 20 else (caption or "Nomsiz")
        status = " (💰 Pullik)" if is_paid else ""
        text += f"{i}. 🎬 <code>{code}</code> - {cap_short}{status} (👁 {views} marta)\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(StateFilter(None), F.text == "🆕 Yangi kinolar")
async def latest_movies(message: types.Message):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code, caption, is_paid FROM movies ORDER BY added_date DESC LIMIT 5")
    movies = cursor.fetchall()
    conn.close()

    if not movies:
        await message.answer("Hozircha bazada kinolar yo'q.")
        return
        
    text = "🆕 <b>Bazamizga qo'shilgan so'nggi kinolar:</b>\n\n"
    for code, caption, is_paid in movies:
        cap_short = caption[:25] + "..." if caption and len(caption) > 25 else (caption or "Nomsiz")
        status = " (💰 Pullik)" if is_paid else ""
        text += f"🎬 Kod: <code>{code}</code> - {cap_short}{status}\n"
    
    await message.answer(text, parse_mode="HTML")

# --- SEVIMLILAR VA TASODIFIY ---
@dp.callback_query(F.data.startswith("fav_"))
async def add_to_favorites(callback: types.CallbackQuery):
    code = callback.data.split("_")[1]
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO favorites (user_id, movie_code) VALUES (?, ?)", (callback.from_user.id, code))
        conn.commit()
        await callback.answer("✅ Kino sevimlilarga qo'shildi!", show_alert=True)
    except sqlite3.IntegrityError:
        cursor.execute("DELETE FROM favorites WHERE user_id=? AND movie_code=?", (callback.from_user.id, code))
        conn.commit()
        await callback.answer("❌ Kino sevimlilardan olib tashlandi!", show_alert=True)
    conn.close()

@dp.message(StateFilter(None), F.text == "❤️ Sevimlilar")
async def show_favorites(message: types.Message):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT movie_code FROM favorites WHERE user_id=?", (message.from_user.id,))
    favs = cursor.fetchall()
    conn.close()

    if not favs:
        await message.answer("Sizda hozircha sevimli kinolar yo'q.")
        return
        
    text = "❤️ <b>Sizning sevimli kinolaringiz kodlari:</b>\n\n"
    for (code,) in favs:
        text += f"🎬 Kod: <code>{code}</code>\n"
    text += "\nKodni botga yuborib kinoni ko'rishingiz mumkin!"
    await message.answer(text, parse_mode="HTML")

@dp.message(StateFilter(None), F.text == "🎲 Tasodifiy kino")
async def random_movie(message: types.Message):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code FROM movies WHERE is_paid=0 ORDER BY RANDOM() LIMIT 1")
    movie = cursor.fetchone()
    conn.close()
    
    if movie:
        message.text = str(movie[0])
        await search_movie(message)
    else:
        await message.answer("Hozircha bazada bepul kinolar yo'q.")

# ================= ADMIN PANEL =================
@dp.message(Command("admin"), StateFilter(None))
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        return
        
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Kino yuklash", callback_data="adm_add_movie"),
         InlineKeyboardButton(text="📂 Kinolarni boshqarish", callback_data="adm_manage_movies")],
        [InlineKeyboardButton(text="⚙️ Majburiy obuna sozlash", callback_data="adm_sub_menu")],
        [InlineKeyboardButton(text="📊 Statistika (Oddiy)", callback_data="adm_stats_text"),
         InlineKeyboardButton(text="📄 Statistika (PDF)", callback_data="adm_stats_pdf")],
        [InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="👥 Admin qo'shish", callback_data="adm_manage_admins")]
    ])
    await message.answer("👨‍💻 <b>Boshqaruv paneli (Admin)</b>", reply_markup=markup, parse_mode="HTML")

# --- KINO YUKLASH (PULLIK/BEPUL) ---
@dp.callback_query(F.data == "adm_add_movie")
async def add_movie_step1(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("1️⃣ <b>Kinoni yuboring</b> (Boshqa kanaldan forward qilsangiz ham bo'ladi):", parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_movie)

@dp.message(AdminState.waiting_for_movie, F.video | F.document | F.photo)
async def add_movie_step2(message: types.Message, state: FSMContext):
    file_id, msg_type = "", ""
    if message.video:
        file_id, msg_type = message.video.file_id, "video"
    elif message.document:
        file_id, msg_type = message.document.file_id, "document"
    elif message.photo:
        file_id, msg_type = message.photo[-1].file_id, "photo"

    await state.update_data(file_id=file_id, type=msg_type)
    await message.answer("2️⃣ <b>Kino kodini kiriting</b> (Faqat raqamlar, masalan: 125):", parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_movie_code)

@dp.message(AdminState.waiting_for_movie_code)
async def add_movie_step3(message: types.Message, state: FSMContext):
    code = message.text.strip()
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code FROM movies WHERE code=?", (code,))
    if cursor.fetchone():
        await message.answer("❌ Bu kod bazada bor. Boshqa kod kiriting:")
        conn.close()
        return
    conn.close()

    await state.update_data(code=code)
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆓 Bepul kino", callback_data="type_free"),
         InlineKeyboardButton(text="💰 Pullik kino", callback_data="type_paid")]
    ])
    await message.answer("3️⃣ <b>Kino turini belgilang:</b>\nBu kino bepul bo'ladimi yoki pullik?", reply_markup=markup, parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_is_paid)

@dp.callback_query(AdminState.waiting_for_is_paid, F.data.in_(["type_free", "type_paid"]))
async def add_movie_is_paid(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "type_free":
        await state.update_data(is_paid=0, price=0)
        markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="O'tkazib yuborish")]], resize_keyboard=True)
        await callback.message.answer("4️⃣ <b>Kino tavsifini yozing</b> (Yoki \"O'tkazib yuborish\" ni bosing):", parse_mode="HTML", reply_markup=markup)
        await state.set_state(AdminState.waiting_for_movie_caption)
    else:
        await state.update_data(is_paid=1)
        await callback.message.answer("💸 <b>Kino narxini kiriting</b> (Faqat raqamlarda, masalan: 5000):", parse_mode="HTML")
        await state.set_state(AdminState.waiting_for_price)

@dp.message(AdminState.waiting_for_price)
async def add_movie_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Iltimos, narxni faqat raqamlarda kiriting!")
        return
        
    await state.update_data(price=int(message.text))
    markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="O'tkazib yuborish")]], resize_keyboard=True)
    await message.answer("4️⃣ <b>Kino tavsifini yozing</b> (Yoki \"O'tkazib yuborish\" ni bosing):", parse_mode="HTML", reply_markup=markup)
    await state.set_state(AdminState.waiting_for_movie_caption)

@dp.message(AdminState.waiting_for_movie_caption)
async def add_movie_step4(message: types.Message, state: FSMContext):
    data = await state.get_data()
    caption = "" if message.text == "O'tkazib yuborish" else message.text
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO movies (code, file_id, type, caption, added_date, is_paid, price) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                   (data['code'], data['file_id'], data['type'], caption, date_now, data['is_paid'], data.get('price', 0)))
    conn.commit()
    conn.close()

    status_text = f"💰 Pullik ({data.get('price', 0)} so'm)" if data['is_paid'] else "🆓 Bepul"
    await message.answer(f"🎉 Kino bazaga muvaffaqiyatli saqlandi!\nKodi: <code>{data['code']}</code>\nStatusi: {status_text}", parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())
    await state.clear()

# --- KINOLARNI BOSHQARISH VA O'CHIRISH ---
@dp.callback_query(F.data == "adm_manage_movies")
async def manage_movies(callback: types.CallbackQuery, state: FSMContext):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code, caption, is_paid, price FROM movies ORDER BY added_date DESC")
    movies = cursor.fetchall()
    conn.close()

    if not movies:
        await callback.answer("Bazada kinolar yo'q!", show_alert=True)
        return

    text = "Barcha kinolar ro'yxati:\n\n"
    for code, caption, is_paid, price in movies:
        status = f"Pullik ({price} so'm)" if is_paid else "Bepul"
        cap = caption.replace('\n', ' ') if caption else "Nomsiz"
        text += f"KOD: {code} | STATUS: {status} | TAVSIF: {cap[:30]}...\n"

    with open("kinolar_royxati.txt", "w", encoding="utf-8") as f:
        f.write(text)

    await bot.send_document(
        chat_id=callback.from_user.id,
        document=FSInputFile("kinolar_royxati.txt"),
        caption="📂 <b>Barcha kinolar ro'yxati faylda.</b>\n\n🗑 Kino o'chirish uchun uning KODINI yuboring.\n<i>(Bekor qilish uchun /cancel deb yozing)</i>",
        parse_mode="HTML"
    )
    os.remove("kinolar_royxati.txt")
    await state.set_state(AdminState.waiting_for_delete_movie)

@dp.message(AdminState.waiting_for_delete_movie)
async def delete_movie(message: types.Message, state: FSMContext):
    if message.text == '/cancel':
        await message.answer("Boshqaruv bekor qilindi.")
        await state.clear()
        return

    code = message.text.strip()
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code FROM movies WHERE code=?", (code,))
    
    if cursor.fetchone():
        cursor.execute("DELETE FROM movies WHERE code=?", (code,))
        conn.commit()
        await message.answer(f"✅ <b>{code}</b> kodli kino bazadan o'chirildi!", parse_mode="HTML")
    else:
        await message.answer("❌ Bunday kodli kino topilmadi. Qaytadan urinib ko'ring yoki /cancel ni bosing.")
    conn.close()
    await state.clear()

# --- MAJBURIY OBUNA ---
@dp.callback_query(F.data == "adm_sub_menu")
async def sub_menu(callback: types.CallbackQuery):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM channels")
    count = cursor.fetchone()[0]
    conn.close()

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_sub_channel")],
        [InlineKeyboardButton(text="📝 Obuna matnini tahrirlash", callback_data="edit_sub_text")]
    ])
    await callback.message.edit_text(f"⚙️ <b>Majburiy obuna</b>\n\nUlangan kanallar: {count}/15 ta", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "edit_sub_text")
async def edit_sub_text_step1(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Yangi majburiy obuna matnini yuboring:")
    await state.set_state(AdminState.waiting_for_sub_text)

@dp.message(AdminState.waiting_for_sub_text)
async def edit_sub_text_step2(message: types.Message, state: FSMContext):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value=? WHERE key='sub_text'", (message.text,))
    conn.commit()
    conn.close()
    await message.answer("✅ Matn yangilandi!")
    await state.clear()

@dp.callback_query(F.data == "add_sub_channel")
async def add_channel_step1(callback: types.CallbackQuery, state: FSMContext):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM channels")
    if cursor.fetchone()[0] >= 15:
        await callback.answer("Maksimal limit (15 ta) to'lgan!", show_alert=True)
        conn.close()
        return
    conn.close()
    await callback.message.answer("Kanal ID raqamini (yoki @username) yuboring:")
    await state.set_state(AdminState.waiting_for_channel_id)

@dp.message(AdminState.waiting_for_channel_id)
async def add_channel_step2(message: types.Message, state: FSMContext):
    await state.update_data(ch_id=message.text)
    await message.answer("Kanal nomini va manzilini kiriting (Masalan: Tarjima Kinolar|https://t.me/kanal_link):")
    await state.set_state(AdminState.waiting_for_channel_url)

@dp.message(AdminState.waiting_for_channel_url)
async def add_channel_step3(message: types.Message, state: FSMContext):
    try:
        name, url = message.text.split("|")
        data = await state.get_data()
        
        conn = sqlite3.connect("kino_bot.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO channels (channel_id, url, name) VALUES (?, ?, ?)", (data['ch_id'], url.strip(), name.strip()))
        conn.commit()
        conn.close()
        
        await message.answer("✅ Kanal qo'shildi! Bot shu kanalda admin ekanligini unutmang.")
    except Exception:
        await message.answer("❌ Xato! Format: Nomi|Link bo'lishi kerak.")
    await state.clear()

# --- STATISTIKA ---
@dp.callback_query(F.data == "adm_stats_text")
async def show_stats(callback: types.CallbackQuery):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    users_count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    movies_count = cursor.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    conn.close()
    await callback.message.answer(f"📊 Foydalanuvchilar: {users_count}\n🎬 Kinolar: {movies_count}")

@dp.callback_query(F.data == "adm_stats_pdf")
async def show_stats_pdf(callback: types.CallbackQuery):
    await callback.message.answer("⏳ PDF shakllantirilmoqda...")
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    users_count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    movies_count = cursor.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    conn.close()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=15)
    pdf.cell(200, 10, txt="Kino Bot - Rasmiy Statistika", ln=True, align='C')
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Foydalanuvchilar: {users_count}", ln=True)
    pdf.cell(200, 10, txt=f"Bazada jami kinolar: {movies_count}", ln=True)
    
    pdf_name = f"statistika_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    pdf.output(pdf_name)
    
    await bot.send_document(chat_id=callback.from_user.id, document=FSInputFile(pdf_name))
    os.remove(pdf_name)

# --- XABAR TARQATISH ---
@dp.callback_query(F.data == "adm_broadcast")
async def broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 Tarqatmoqchi bo'lgan xabarni yuboring (Rasm, matn, video, ovozli xabar):")
    await state.set_state(AdminState.waiting_for_broadcast)

@dp.message(AdminState.waiting_for_broadcast)
async def broadcast_send(message: types.Message, state: FSMContext):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    users = cursor.execute("SELECT id FROM users").fetchall()
    conn.close()

    success, fail = 0, 0
    msg = await message.answer("⏳ Tarqatilmoqda...")
    
    for (user_id,) in users:
        try:
            # message.copy_to() funksiyasi har qanday turdagi xabarni xatosiz yetkazib beradi
            await message.copy_to(chat_id=user_id)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1

    await msg.edit_text(f"✅ Yakunlandi!\nBordi: {success}\nBlok qilganlar: {fail}")
    await state.clear()

# --- ADMIN QO'SHISH ---
@dp.callback_query(F.data == "adm_manage_admins")
async def manage_admins(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != MAIN_ADMIN_ID:
        await callback.answer("Faqat Bosh Admin qila oladi!", show_alert=True)
        return
    await callback.message.answer("Yangi admin Telegram ID raqamini yuboring:")
    await state.set_state(AdminState.waiting_for_new_admin)

@dp.message(AdminState.waiting_for_new_admin)
async def add_new_admin(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("ID faqat raqamlardan iborat bo'ladi!")
        return
        
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO admins (id) VALUES (?)", (int(message.text),))
    conn.commit()
    conn.close()
    
    await message.answer("✅ Yangi admin tizimga muvaffaqiyatli qo'shildi!")
    await state.clear()

# ================= ASOSIY ISHGA TUSHIRISH =================
async def main():
    init_db()
    print("🚀 Barcha bazalar tekshirildi, Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
