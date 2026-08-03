import asyncio
import sqlite3
import os
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from fpdf import FPDF

# ================= FIREBASE UCHUN QO'SHILDI =================
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db

# ================= SOZLAMALAR =================
BOT_TOKEN = "8998624190:AAHWIIJW4pr3Hk2jRw_d0Ll6fVF4lwr7_4s" 
MAIN_ADMIN_ID = 8355669630

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= FIREBASE BAZANI ULAHS =================
try:
    cred = credentials.Certificate("path/to/serviceAccountKey.json")
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://dowload-6c855-default-rtdb.firebaseio.com'
    })
    print("✅ Firebase bazasiga muvaffaqiyatli ulandi!")
except Exception as e:
    print(f"❌ Firebase'ga ulanishda xatolik: {e}")

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
    waiting_for_ad_text = State()
    waiting_for_p_channel_id = State()
    waiting_for_p_channel_url = State()
    # YANGI KETMA-KET YUKLASH HOLATLARI
    waiting_for_batch_movies = State()
    waiting_for_batch_codes = State()
    waiting_for_batch_text = State()

# ================= MA'LUMOTLAR BAZASI =================
def init_db():
    # Eski baza umuman ochilmaydi, boriga qoshadi, yoq bolsa yaratadi
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, joined_date TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY)''')
    
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
    
    try:
        cursor.execute("ALTER TABLE movies ADD COLUMN is_paid INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE movies ADD COLUMN price INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    cursor.execute('''CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY, url TEXT, name TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS private_channels (channel_id TEXT PRIMARY KEY, url TEXT, name TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS join_requests (user_id INTEGER, channel_id TEXT, UNIQUE(user_id, channel_id))''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER, movie_code TEXT, UNIQUE(user_id, movie_code))''')
    
    cursor.execute("INSERT OR IGNORE INTO admins (id) VALUES (?)", (MAIN_ADMIN_ID,))
    
    # Majburiy kanallarni standart qo'shish
    cursor.execute("INSERT OR IGNORE INTO channels (channel_id, url, name) VALUES ('@kinolaruzhub', 'https://t.me/kinolaruzhub', 'Kinolar Hub')")
    cursor.execute("INSERT OR IGNORE INTO channels (channel_id, url, name) VALUES ('@rikvamorti_multifilm', 'https://t.me/rikvamorti_multifilm', 'Rik va Morti')")
    cursor.execute("INSERT OR IGNORE INTO private_channels (channel_id, url, name) VALUES ('-1003297745646', 'https://t.me/+', 'Yopiq Kanal')")

    default_text = "Botdan to'liq foydalanish va kinolarni ko'rish uchun quyidagi kanallarga obuna bo'lishingiz shart!"
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('sub_text', ?)", (default_text,))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('ad_text', '')") 
    
    conn.commit()
    conn.close()

def is_admin(user_id):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM admins WHERE id=?", (user_id,))
    admin = cursor.fetchone()
    conn.close()
    return bool(admin)

# ================= ADMIN PANELI =================
async def send_admin_panel(message: types.Message, text="👨‍💻 <b>Boshqaruv paneli (Admin)</b>"):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Kino yuklash", callback_data="adm_add_movie"),
         InlineKeyboardButton(text="📂 Kinolarni boshq.", callback_data="adm_manage_movies")],
        [InlineKeyboardButton(text="📥 Ketma-ket kino yuklash", callback_data="adm_batch_movie")],
        [InlineKeyboardButton(text="⚙️ Ochiq kanal (Obuna)", callback_data="adm_sub_menu")],
        [InlineKeyboardButton(text="🔒 Yopiq kanal (Obuna)", callback_data="adm_sub_p_menu")],
        [InlineKeyboardButton(text="📝 Reklama sozlash", callback_data="adm_ad_text")],
        [InlineKeyboardButton(text="📊 Statistika (Oddiy)", callback_data="adm_stats_text"),
         InlineKeyboardButton(text="📄 Statistika (PDF)", callback_data="adm_stats_pdf")],
        [InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="👥 Admin qo'shish", callback_data="adm_manage_admins")]
    ])
    await message.answer(text, reply_markup=markup, parse_mode="HTML")

# ================= MAJBURIY OBUNA =================
async def get_sub_markup(user_id):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, url, name FROM channels")
    channels = cursor.fetchall()
    
    cursor.execute("SELECT channel_id, url, name FROM private_channels")
    p_channels = cursor.fetchall()
    
    unsubscribed = []
    
    for ch_id, url, name in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                unsubscribed.append((name, url))
        except Exception:
            continue
            
    for ch_id, url, name in p_channels:
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                cursor.execute("SELECT * FROM join_requests WHERE user_id=? AND channel_id=?", (user_id, str(ch_id)))
                if not cursor.fetchone():
                    unsubscribed.append((f"🔒 {name}", url))
        except Exception:
            cursor.execute("SELECT * FROM join_requests WHERE user_id=? AND channel_id=?", (user_id, str(ch_id)))
            if not cursor.fetchone():
                unsubscribed.append((f"🔒 {name}", url))
                
    conn.close()
    if not unsubscribed:
        return None
        
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for name, url in unsubscribed:
        markup.inline_keyboard.append([InlineKeyboardButton(text=f"📢 {name}", url=url)])
    markup.inline_keyboard.append([InlineKeyboardButton(text="✅ Obuna bo'ldim (Tasdiqlash)", callback_data="check_sub")])
    return markup

@dp.chat_join_request()
async def join_request_handler(chat_join: types.ChatJoinRequest):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO join_requests (user_id, channel_id) VALUES (?, ?)", (chat_join.from_user.id, str(chat_join.chat.id)))
    conn.commit()
    conn.close()

def main_menu():
    markup = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔥 Top kinolar"), KeyboardButton(text="🆕 Yangi kinolar")],
            [KeyboardButton(text="🎲 Tasodifiy kino"), KeyboardButton(text="❤️ Sevimlilar")],
            [KeyboardButton(text="🔙 Orqaga")]
        ],
        resize_keyboard=True
    )
    return markup

@dp.message(F.text == "🔙 Orqaga")
async def go_back_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Bosh sahifaga qaytdingiz. \nKino kodini yuboring 👇", reply_markup=main_menu())

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
        await callback.answer("Siz hamma kanallarga obuna bo'lmagansiz yoki so'rov yubormagansiz!", show_alert=True)
    else:
        await callback.message.delete()
        await callback.message.answer("Assalomu aleykum, kino kodini orqali qidiring 👇", reply_markup=main_menu())

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
        await message.answer("Unday kino topilmadi iltimos @kinolaruzhub dan qidirib ko'ring.")
        return

    cursor.execute("UPDATE movies SET views = views + 1 WHERE code=?", (code,))
    
    cursor.execute("SELECT value FROM settings WHERE key='ad_text'")
    ad_row = cursor.fetchone()
    conn.commit()
    conn.close()

    file_id, msg_type, caption, is_paid, price = movie
    
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

    if ad_row and ad_row[0].strip():
        await message.answer(ad_row[0].strip(), parse_mode="HTML", disable_web_page_preview=True)
        
    await message.answer("Yana qanday kino ko'rishni istaysiz? Kodni yuboring 👇", reply_markup=main_menu())

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
    markup = await get_sub_markup(message.from_user.id)
    if markup:
        await message.answer("Avval kanallarga obuna bo'ling!", reply_markup=markup)
        return

    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT code, file_id, type, caption FROM movies WHERE is_paid=0 ORDER BY RANDOM() LIMIT 1")
    movie = cursor.fetchone()
    
    if not movie:
        conn.close()
        await message.answer("Hozircha bazada bepul kinolar yo'q.")
        return

    code, file_id, msg_type, caption = movie
    cursor.execute("UPDATE movies SET views = views + 1 WHERE code=?", (code,))
    
    cursor.execute("SELECT value FROM settings WHERE key='ad_text'")
    ad_row = cursor.fetchone()
    conn.commit()
    conn.close()

    fav_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Sevimlilarga qo'shish", callback_data=f"fav_{code}")]
    ])

    if msg_type == 'video':
        await message.answer_video(video=file_id, caption=f"🎬 Tasodifiy kino kodi: {code}\n\n{caption}", reply_markup=fav_btn)
    elif msg_type == 'document':
        await message.answer_document(document=file_id, caption=f"🎬 Tasodifiy kino kodi: {code}\n\n{caption}", reply_markup=fav_btn)
    elif msg_type == 'photo':
        await message.answer_photo(photo=file_id, caption=f"🎬 Tasodifiy kino kodi: {code}\n\n{caption}", reply_markup=fav_btn)

    if ad_row and ad_row[0].strip():
        await message.answer(ad_row[0].strip(), parse_mode="HTML", disable_web_page_preview=True)
        
    await message.answer("Yana qanday kino ko'rishni istaysiz? Kodni yuboring 👇", reply_markup=main_menu())

# ================= ADMIN PANEL UCHUN BUYRUQ =================
@dp.message(Command("admin"), StateFilter(None))
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await send_admin_panel(message)

# ================= KETMA-KET KINO YUKLASH (YANGI FUNKSIYA) =================
@dp.callback_query(F.data == "adm_batch_movie")
async def batch_upload_start(callback: types.CallbackQuery, state: FSMContext):
    markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="✅ Kinolarni yukladim")], [KeyboardButton(text="🔙 Orqaga")]], resize_keyboard=True)
    await callback.message.answer("📥 <b>Ketma-ket kino yuklash</b>\n\nKinolarni botga bittalab yuboring (yoki forward qiling). Barcha kinolarni yuborib bo'lgach, pastdagi <b>✅ Kinolarni yukladim</b> tugmasini bosing.", reply_markup=markup, parse_mode="HTML")
    await state.update_data(batch_files=[])
    await state.set_state(AdminState.waiting_for_batch_movies)

@dp.message(AdminState.waiting_for_batch_movies, F.video | F.document | F.photo)
async def batch_upload_collect(message: types.Message, state: FSMContext):
    data = await state.get_data()
    files = data.get('batch_files', [])
    
    file_id, msg_type = "", ""
    if message.video: file_id, msg_type = message.video.file_id, "video"
    elif message.document: file_id, msg_type = message.document.file_id, "document"
    elif message.photo: file_id, msg_type = message.photo[-1].file_id, "photo"

    files.append({'file_id': file_id, 'type': msg_type})
    await state.update_data(batch_files=files)
    await message.answer(f"✅ Kino qabul qilindi. Jami: {len(files)} ta.\n<i>Yana yuboring yoki '✅ Kinolarni yukladim' tugmasini bosing.</i>", parse_mode="HTML")

@dp.message(AdminState.waiting_for_batch_movies, F.text == "✅ Kinolarni yukladim")
async def batch_upload_done(message: types.Message, state: FSMContext):
    data = await state.get_data()
    files = data.get('batch_files', [])
    if not files:
        await message.answer("❌ Siz hech qanday kino yubormadingiz!", reply_markup=main_menu())
        await state.clear()
        await send_admin_panel(message)
        return
    
    await message.answer(f"✅ Jami {len(files)} ta kino yubordingiz.\n\nEndi ularning KODLARINI ketma-ketlikda probel bilan ajratib yozing (Masalan: 1 2 3 4 5):", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Orqaga")]], resize_keyboard=True))
    await state.set_state(AdminState.waiting_for_batch_codes)

@dp.message(AdminState.waiting_for_batch_codes)
async def batch_codes_received(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
    
    codes = message.text.strip().split()
    data = await state.get_data()
    files = data.get('batch_files', [])
    
    if len(codes) != len(files):
        await message.answer(f"❌ Kodlar soni ({len(codes)}) kinolar soniga ({len(files)}) mos emas! Qaytadan kodlarni kiriting:")
        return
        
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    existing_codes = []
    for code in codes:
        if cursor.execute("SELECT code FROM movies WHERE code=?", (code,)).fetchone():
            existing_codes.append(code)
            
    if existing_codes:
        conn.close()
        await message.answer(f"❌ Quyidagi kodlar bazada allaqachon mavjud: {', '.join(existing_codes)}\nIltimos, boshqa kodlarni kiriting:")
        return

    for i, file_data in enumerate(files):
        cursor.execute("INSERT INTO movies (code, file_id, type, caption, added_date, is_paid, price) VALUES (?, ?, ?, ?, ?, ?, ?)", 
               (codes[i], file_data['file_id'], file_data['type'], "", date_now, 0, 0))
    conn.commit()
    conn.close()
    
    await message.answer("🎉 Barcha kinolar bazaga saqlandi!\n\nEndi @kinolaruzhub kanaliga e'lon berish uchun xabar matnini yuboring.\n(Masalan: 1-chisi bu, 2-chisi bu kino deb yozing)\n\n<i>E'lon bermaslik uchun shunchaki 'Yoq' deb yozing.</i>", parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_batch_text)

@dp.message(AdminState.waiting_for_batch_text)
async def batch_text_received(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() not in ["yo'q", "yoq", "yoq."]:
        try:
            await bot.send_message(chat_id="@kinolaruzhub", text=f"📢 <b>YANGI KINOLAR YUKLANDI!</b>\n\n{text}", parse_mode="HTML")
            await message.answer("✅ E'lon @kinolaruzhub kanaliga yuborildi!", reply_markup=main_menu())
        except Exception as e:
            await message.answer(f"❌ Kanalga yuborishda xato (Bot kanal admini ekanligini tekshiring): {e}", reply_markup=main_menu())
    else:
        await message.answer("🚫 E'lon kanalga yuborilmadi.", reply_markup=main_menu())
        
    await state.clear()
    await send_admin_panel(message)  # Har doim menyu qaytadi

# --- REKLAMA SOZLASH ---
@dp.callback_query(F.data == "adm_ad_text")
async def edit_ad_text_step1(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Kino yuborilgach, uning tagida chiqadigan reklama matnini yuboring:\n(O'chirib tashlash uchun 'ochirish' deb yozing, bekor qilish uchun '🔙 Orqaga' bosing)")
    await state.set_state(AdminState.waiting_for_ad_text)

@dp.message(AdminState.waiting_for_ad_text)
async def edit_ad_text_step2(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
        
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    if message.text.lower() == 'ochirish':
        cursor.execute("UPDATE settings SET value='' WHERE key='ad_text'")
        await message.answer("✅ Reklama matni o'chirildi!")
    else:
        cursor.execute("UPDATE settings SET value=? WHERE key='ad_text'", (message.text,))
        await message.answer("✅ Reklama matni yangilandi!")
    conn.commit()
    conn.close()
    await state.clear()
    await send_admin_panel(message)  

# --- YOPIQ KANAL QO'SHISH ---
@dp.callback_query(F.data == "adm_sub_p_menu")
async def sub_p_menu(callback: types.CallbackQuery):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM private_channels")
    count = cursor.fetchone()[0]
    conn.close()

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yopiq kanal qo'shish", callback_data="add_sub_p_channel")]
    ])
    await callback.message.edit_text(f"🔒 <b>Yopiq kanallar (Majburiy obuna)</b>\n\nUlangan yopiq kanallar: {count}/10 ta\n\n*Izoh: Bot yopiq kanallarga obuna bo'lish so'rovini yuborgan foydalanuvchilarni tekshiradi.*", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "add_sub_p_channel")
async def add_p_channel_step1(callback: types.CallbackQuery, state: FSMContext):
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM private_channels")
    if cursor.fetchone()[0] >= 10:
        await callback.answer("Maksimal limit (10 ta) to'lgan!", show_alert=True)
        conn.close()
        return
    conn.close()
    await callback.message.answer("Yopiq kanal ID raqamini yuboring (Masalan: -1001234567890):")
    await state.set_state(AdminState.waiting_for_p_channel_id)

@dp.message(AdminState.waiting_for_p_channel_id)
async def add_p_channel_step2(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
    await state.update_data(ch_id=message.text)
    await message.answer("Yopiq kanal nomini va manzilini kiriting (Masalan: Yopiq Kino|https://t.me/+joinlink):")
    await state.set_state(AdminState.waiting_for_p_channel_url)

@dp.message(AdminState.waiting_for_p_channel_url)
async def add_p_channel_step3(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
    try:
        text = message.text.strip()
        if "|" not in text:
            raise ValueError("Pipe not found")
            
        name, url = text.split("|", 1)
        data = await state.get_data()
        
        conn = sqlite3.connect("kino_bot.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO private_channels (channel_id, url, name) VALUES (?, ?, ?)", (data['ch_id'], url.strip(), name.strip()))
        conn.commit()
        conn.close()
        
        await message.answer("✅ Yopiq kanal qo'shildi! Bot shu kanalda obuna so'rovlarini ko'rish uchun ADMIN bo'lishi shart.")
    except Exception:
        await message.answer("❌ Xato! Iltimos, havolaga preview (ko'rinish) bermasdan shunchaki yuboring.\nFormat: <code>Nomi|https://t.me/+joinlink</code>", parse_mode="HTML")
    await state.clear()
    await send_admin_panel(message)

# --- BITTALAB KINO YUKLASH ---
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
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
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
        markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="O'tkazib yuborish")], [KeyboardButton(text="🔙 Orqaga")]], resize_keyboard=True)
        await callback.message.answer("4️⃣ <b>Kino tavsifini yozing</b> (Yoki \"O'tkazib yuborish\" ni bosing):", parse_mode="HTML", reply_markup=markup)
        await state.set_state(AdminState.waiting_for_movie_caption)
    else:
        await state.update_data(is_paid=1)
        await callback.message.answer("💸 <b>Kino narxini kiriting</b> (Faqat raqamlarda, masalan: 5000):", parse_mode="HTML")
        await state.set_state(AdminState.waiting_for_price)

@dp.message(AdminState.waiting_for_price)
async def add_movie_price(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
    if not message.text.isdigit():
        await message.answer("❌ Iltimos, narxni faqat raqamlarda kiriting!")
        return
        
    await state.update_data(price=int(message.text))
    markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="O'tkazib yuborish")], [KeyboardButton(text="🔙 Orqaga")]], resize_keyboard=True)
    await message.answer("4️⃣ <b>Kino tavsifini yozing</b> (Yoki \"O'tkazib yuborish\" ni bosing):", parse_mode="HTML", reply_markup=markup)
    await state.set_state(AdminState.waiting_for_movie_caption)

@dp.message(AdminState.waiting_for_movie_caption)
async def add_movie_step4(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
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
    await message.answer(f"🎉 Kino bazaga muvaffaqiyatli saqlandi!\nKodi: <code>{data['code']}</code>\nStatusi: {status_text}", parse_mode="HTML", reply_markup=main_menu())
    await state.clear()
    await send_admin_panel(message)

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
    if message.text == '/cancel' or message.text == '🔙 Orqaga':
        await message.answer("Boshqaruv bekor qilindi.", reply_markup=main_menu())
        await state.clear()
        await send_admin_panel(message)
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
    await send_admin_panel(message)

# --- MAJBURIY OBUNA (OCHIQ) ---
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
    await callback.message.edit_text(f"⚙️ <b>Majburiy obuna (Ochiq kanallar)</b>\n\nUlangan kanallar: {count}/15 ta", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "edit_sub_text")
async def edit_sub_text_step1(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Yangi majburiy obuna matnini yuboring:")
    await state.set_state(AdminState.waiting_for_sub_text)

@dp.message(AdminState.waiting_for_sub_text)
async def edit_sub_text_step2(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value=? WHERE key='sub_text'", (message.text,))
    conn.commit()
    conn.close()
    await message.answer("✅ Matn yangilandi!")
    await state.clear()
    await send_admin_panel(message)

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
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
    await state.update_data(ch_id=message.text)
    await message.answer("Kanal nomini va manzilini kiriting (Masalan: Tarjima Kinolar|https://t.me/kanal_link):")
    await state.set_state(AdminState.waiting_for_channel_url)

@dp.message(AdminState.waiting_for_channel_url)
async def add_channel_step3(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
    try:
        text = message.text.strip()
        if "|" not in text:
            raise ValueError("Pipe not found")
        
        name, url = text.split("|", 1) 
        data = await state.get_data()
        
        conn = sqlite3.connect("kino_bot.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO channels (channel_id, url, name) VALUES (?, ?, ?)", (data['ch_id'], url.strip(), name.strip()))
        conn.commit()
        conn.close()
        
        await message.answer("✅ Kanal qo'shildi! Bot shu kanalda admin ekanligini unutmang.")
    except Exception:
        await message.answer("❌ Xato! Iltimos, havolaga preview (ko'rinish) bermasdan shunchaki yuboring.\nFormat: <code>Nomi|https://t.me/kanal</code>", parse_mode="HTML")
    await state.clear()
    await send_admin_panel(message)

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
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
    conn = sqlite3.connect("kino_bot.db")
    cursor = conn.cursor()
    users = cursor.execute("SELECT id FROM users").fetchall()
    conn.close()

    success, fail = 0, 0
    msg = await message.answer("⏳ Tarqatilmoqda...")
    
    for (user_id,) in users:
        try:
            await message.copy_to(chat_id=user_id)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1

    await msg.edit_text(f"✅ Yakunlandi!\nBordi: {success}\nBlok qilganlar: {fail}")
    await state.clear()
    await send_admin_panel(message)

# --- ADMIN QO'SHISH (XATO TUZATILDI) ---
@dp.callback_query(F.data == "adm_manage_admins")
async def manage_admins(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != MAIN_ADMIN_ID:
        await callback.answer("Faqat Bosh Admin qila oladi!", show_alert=True)
        return
    await callback.message.answer("Yangi admin Telegram ID raqamini yuboring:")
    await state.set_state(AdminState.waiting_for_new_admin)

@dp.message(AdminState.waiting_for_new_admin)
async def add_new_admin(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
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
    await send_admin_panel(message)

# ================= ASOSIY ISHGA TUSHIRISH (VEB SERVER + BOT) =================
async def handle(request):
    return web.Response(text="Bot is running!")

async def web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    init_db()
    print("🚀 Barcha bazalar tekshirildi, Bot ishga tushdi...")
    
    asyncio.create_task(web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
