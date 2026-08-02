import asyncio
import os
import sqlite3
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ================= SOZLAMALAR =================
BOT_TOKEN = "8998624190:AAGMbIYyTE7uCKlkQZOcGRdyoy9g4UnGAro" 
MAIN_ADMIN_ID = 8355669630 # O'zingizning ID raqamingiz

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= SQLITE BAZANI ULASH VA YARATISH =================
def get_db():
    conn = sqlite3.connect('kino_bot.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Foydalanuvchilar jadvali
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    joined_date TEXT,
                    is_vip INTEGER DEFAULT 0,
                    vip_expiry TEXT
                )''')
    # Kinolar jadvali
    c.execute('''CREATE TABLE IF NOT EXISTS movies (
                    code TEXT PRIMARY KEY,
                    file_id TEXT,
                    type TEXT,
                    caption TEXT,
                    added_date TEXT,
                    is_paid INTEGER DEFAULT 0,
                    price INTEGER DEFAULT 0,
                    views INTEGER DEFAULT 0
                )''')
    # Kanallar jadvali (ochiq va yopiq)
    c.execute('''CREATE TABLE IF NOT EXISTS channels (
                    channel_id TEXT PRIMARY KEY,
                    url TEXT,
                    name TEXT,
                    is_private INTEGER DEFAULT 0
                )''')
    # Yopiq kanallarga so'rovlar
    c.execute('''CREATE TABLE IF NOT EXISTS join_requests (
                    user_id INTEGER,
                    channel_id TEXT,
                    PRIMARY KEY (user_id, channel_id)
                )''')
    # Sevimlilar jadvali
    c.execute('''CREATE TABLE IF NOT EXISTS favorites (
                    user_id INTEGER,
                    movie_code TEXT,
                    PRIMARY KEY (user_id, movie_code)
                )''')
    # Adminlar va sozlamalar
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    
    # Standart ma'lumotlarni kiritish
    c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (MAIN_ADMIN_ID,))
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('sub_text', 'Botdan to''liq foydalanish va kinolarni ko''rish uchun quyidagi kanallarga obuna bo''lishingiz shart!')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('ad_text', '')")
    
    # Standart yopiq kanalni kiritish (Admin panel orqali ID'sini to'g'irlashingiz mumkin)
    c.execute("INSERT OR IGNORE INTO channels (channel_id, url, name, is_private) VALUES (?, ?, ?, ?)",
              ("-1003297745646", "https://t.me/+t30YnzAM5iFlNGVk", "Yopiq Kanal", 1))
    
    conn.commit()
    conn.close()

# ================= FSM HOLATLAR =================
class AdminState(StatesGroup):
    waiting_for_movie = State()
    waiting_for_movie_code = State()
    waiting_for_channel_id = State()
    waiting_for_channel_url = State()
    waiting_for_channel_name = State()
    waiting_for_vip_id = State()
    waiting_for_del_channel = State()

class UserState(StatesGroup):
    waiting_for_movie_order = State()

# ================= YORDAMCHI FUNKSIYALAR =================
def is_admin(user_id):
    conn = get_db()
    admin = conn.cursor().execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return bool(admin)

def get_user_status(user_id):
    conn = get_db()
    c = conn.cursor()
    user = c.execute("SELECT is_vip, vip_expiry FROM users WHERE user_id = ?", (user_id,)).fetchone()
    
    if not user:
        conn.close()
        return False
        
    is_vip = bool(user['is_vip'])
    if is_vip and user['vip_expiry']:
        expiry_date = datetime.fromisoformat(user['vip_expiry'])
        if datetime.now() > expiry_date:
            # VIP muddati tugadi
            c.execute("UPDATE users SET is_vip = 0, vip_expiry = NULL WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            return False
        conn.close()
        return True
        
    conn.close()
    return False

# ================= MAJBURIY OBUNA =================
async def get_sub_markup(user_id):
    if get_user_status(user_id): # VIP obunachilar obuna bo'lishi shart emas
        return None

    conn = get_db()
    c = conn.cursor()
    channels = c.execute("SELECT * FROM channels").fetchall()
    
    unsubscribed = []
    
    for ch in channels:
        ch_id = ch['channel_id']
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                if ch['is_private']:
                    req = c.execute("SELECT 1 FROM join_requests WHERE user_id = ? AND channel_id = ?", (user_id, ch_id)).fetchone()
                    if not req:
                        unsubscribed.append((f"🔒 {ch['name']}", ch['url']))
                else:
                    unsubscribed.append((f"📢 {ch['name']}", ch['url']))
        except Exception:
            if ch['is_private']:
                req = c.execute("SELECT 1 FROM join_requests WHERE user_id = ? AND channel_id = ?", (user_id, ch_id)).fetchone()
                if not req:
                    unsubscribed.append((f"🔒 {ch['name']}", ch['url']))
            else:
                unsubscribed.append((f"📢 {ch['name']}", ch['url']))
                
    conn.close()
    if not unsubscribed:
        return None
        
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for name, url in unsubscribed:
        markup.inline_keyboard.append([InlineKeyboardButton(text=name, url=url)])
    markup.inline_keyboard.append([InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_sub")])
    return markup

@dp.chat_join_request()
async def join_request_handler(chat_join: types.ChatJoinRequest):
    user_id = chat_join.from_user.id
    channel_id = str(chat_join.chat.id)
    conn = get_db()
    conn.cursor().execute("INSERT OR IGNORE INTO join_requests (user_id, channel_id) VALUES (?, ?)", (user_id, channel_id))
    conn.commit()
    conn.close()
    # Yopiq kanal so'rovi tasdiqlanadi va botdan foydalana oladi

# ================= ASOSIY MENYU VA START =================
def main_menu():
    markup = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔥 Top kinolar"), KeyboardButton(text="🆕 Yangi kinolar")],
            [KeyboardButton(text="🎲 Tasodifiy kino"), KeyboardButton(text="❤️ Sevimlilar")],
            [KeyboardButton(text="🌟 VIP haqida"), KeyboardButton(text="📝 Kino buyurtma qilish")]
        ],
        resize_keyboard=True
    )
    return markup

@dp.message(F.text == "🔙 Orqaga")
async def go_back_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Bosh sahifaga qaytdingiz. \nKino kodini yuboring 👇", reply_markup=main_menu())

@dp.message(CommandStart(), StateFilter(None))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Mavjud emas"
    
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, joined_date) VALUES (?, ?, ?)", 
              (user_id, username, datetime.now().strftime("%Y-%m-%d %H:%M")))
    sub_text = c.execute("SELECT value FROM settings WHERE key = 'sub_text'").fetchone()['value']
    conn.commit()
    conn.close()
    
    markup = await get_sub_markup(user_id)
    if markup:
        await message.answer(sub_text, reply_markup=markup)
        return

    await message.answer("Assalomu aleykum, kino kodini orqali qidiring 👇", reply_markup=main_menu())

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery):
    markup = await get_sub_markup(callback.from_user.id)
    if markup:
        await callback.answer("Siz hamma kanallarga obuna bo'lmagansiz yoki yopiq kanalga so'rov yubormagansiz!", show_alert=True)
    else:
        await callback.message.delete()
        await callback.message.answer("Assalomu aleykum, kino kodini orqali qidiring 👇", reply_markup=main_menu())

# ================= VIP TIZIMI =================
@dp.message(F.text == "🌟 VIP haqida")
async def vip_info(message: types.Message):
    text = (
        "🌟 <b>VIP (Premium) Obuna Afzalliklari:</b>\n\n"
        "🚫 <b>Majburiy obunalarsiz:</b> Hech qanday kanalga a'zo bo'lish shart emas.\n"
        "📥 <b>Kinolarni saqlash va ulashish:</b> Faqat VIP foydalanuvchilar kinolarni (forward qilib) saqlab olishi va boshqalarga jo'natishi mumkin.\n"
        "📝 <b>Kino buyurtma qilish:</b> Istalgan kinoni maxsus tugma orqali buyurtma qiling va 24 soat ichida topib beramiz.\n\n"
        "💰 <b>Narxi:</b> 1 oy uchun 10,000 so'm\n"
        "💳 <b>Sotib olish uchun adminga yozing:</b> @smart_gemini"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(StateFilter(None), F.text == "📝 Kino buyurtma qilish")
async def order_movie_step1(message: types.Message, state: FSMContext):
    if not get_user_status(message.from_user.id):
        await message.answer("❌ Ushbu funksiya faqat <b>VIP</b> obunachilar uchun mavjud.\nVIP sotib olish uchun: @smart_gemini", parse_mode="HTML")
        return
    
    markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Orqaga")]], resize_keyboard=True)
    await message.answer("📝 <b>Kino buyurtma qilish:</b>\n\nQaysi kinoni ko'rmoqchisiz? Nomini yozib yuboring. 24 soat ichida topib beramiz:", parse_mode="HTML", reply_markup=markup)
    await state.set_state(UserState.waiting_for_movie_order)

@dp.message(UserState.waiting_for_movie_order)
async def order_movie_step2(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
    
    await bot.send_message(
        chat_id=MAIN_ADMIN_ID,
        text=f"🆕 <b>YANGI BUYURTMA (VIP foydalanuvchidan)</b>\n\n👤 Mijoz ID: <code>{message.from_user.id}</code>\n🎬 Kino: <i>{message.text}</i>",
        parse_mode="HTML"
    )
    await message.answer("✅ Buyurtmangiz adminga muvaffaqiyatli yetkazildi!", reply_markup=main_menu())
    await state.clear()

# ================= KINO YUBORISH (ANTI-PIRACY) =================
@dp.message(StateFilter(None), lambda msg: msg.text and msg.text.isdigit())
async def search_movie(message: types.Message):
    user_id = message.from_user.id
    markup = await get_sub_markup(user_id)
    if markup:
        await message.answer("Avval kanallarga obuna bo'ling!", reply_markup=markup)
        return

    code = message.text.strip()
    conn = get_db()
    c = conn.cursor()
    movie = c.execute("SELECT * FROM movies WHERE code = ?", (code,)).fetchone()
    
    if not movie:
        conn.close()
        await message.answer("Kino topilmadi.")
        return

    # Ko'rishlarni oshirish
    c.execute("UPDATE movies SET views = views + 1 WHERE code = ?", (code,))
    conn.commit()
    conn.close()
    
    is_vip = get_user_status(user_id)
    protect = not is_vip # VIP Emaslarga Forward qilib bo'lmasligi ta'minlanadi
    
    try:
        cap = movie['caption'] or ""
        if movie['type'] == 'video':
            await message.answer_video(video=movie['file_id'], caption=cap, protect_content=protect)
        elif movie['type'] == 'document':
            await message.answer_document(document=movie['file_id'], caption=cap, protect_content=protect)
    except Exception:
        await message.answer("Fayl o'chirilgan yoki xatolik yuz berdi.")

# ================= ADMIN PANEL VA KANALLAR BOSHQARUVI =================
async def send_admin_panel(message: types.Message):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 VIP boshqaruvi", callback_data="adm_vip_menu")],
        [InlineKeyboardButton(text="📢 Kanallarni boshqarish", callback_data="adm_channels_menu")],
        [InlineKeyboardButton(text="🎬 Kino qo'shish (Tezkor)", callback_data="adm_fast_movie")]
    ])
    await message.answer("👨‍💻 <b>Boshqaruv paneli (Admin)</b>", reply_markup=markup, parse_mode="HTML")

@dp.message(Command("admin"), StateFilter(None))
async def admin_panel(message: types.Message):
    if is_admin(message.from_user.id):
        await send_admin_panel(message)

# Kanallar boshqaruvi
@dp.callback_query(F.data == "adm_channels_menu")
async def channels_menu(callback: types.CallbackQuery):
    conn = get_db()
    channels = conn.cursor().execute("SELECT * FROM channels").fetchall()
    conn.close()
    
    text = "📢 <b>Majburiy Kanallar Ro'yxati:</b>\n\n"
    for ch in channels:
        type_ch = "🔒 Yopiq" if ch['is_private'] else "📢 Ochiq"
        text += f"ID: <code>{ch['channel_id']}</code> | Nomi: {ch['name']} ({type_ch})\n"

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ochiq kanal qo'shish", callback_data="add_ch_pub"),
         InlineKeyboardButton(text="➕ Yopiq kanal qo'shish", callback_data="add_ch_priv")],
        [InlineKeyboardButton(text="🗑 Kanal o'chirish", callback_data="del_channel")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_back_main")]
    ])
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data.in_(["add_ch_pub", "add_ch_priv"]))
async def add_channel_step1(callback: types.CallbackQuery, state: FSMContext):
    is_priv = 1 if callback.data == "add_ch_priv" else 0
    await state.update_data(is_private=is_priv)
    await callback.message.answer("Kanalning ID raqamini (yoki @username) yuboring:\nMisol: -1001234567890 yoki @kanalim")
    await state.set_state(AdminState.waiting_for_channel_id)

@dp.message(AdminState.waiting_for_channel_id)
async def add_channel_step2(message: types.Message, state: FSMContext):
    await state.update_data(ch_id=message.text.strip())
    await message.answer("Kanal nomini yuboring:")
    await state.set_state(AdminState.waiting_for_channel_name)

@dp.message(AdminState.waiting_for_channel_name)
async def add_channel_step3(message: types.Message, state: FSMContext):
    await state.update_data(ch_name=message.text.strip())
    await message.answer("Kanal manzilini (URL/Invite Link) yuboring:")
    await state.set_state(AdminState.waiting_for_channel_url)

@dp.message(AdminState.waiting_for_channel_url)
async def add_channel_step4(message: types.Message, state: FSMContext):
    data = await state.get_data()
    url = message.text.strip()
    
    conn = get_db()
    conn.cursor().execute("INSERT OR REPLACE INTO channels (channel_id, url, name, is_private) VALUES (?, ?, ?, ?)",
                          (data['ch_id'], url, data['ch_name'], data['is_private']))
    conn.commit()
    conn.close()
    
    await message.answer("✅ Kanal muvaffaqiyatli qo'shildi!")
    await state.clear()
    await send_admin_panel(message)

@dp.callback_query(F.data == "del_channel")
async def del_channel_step1(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("O'chirilishi kerak bo'lgan kanal ID'sini yuboring:")
    await state.set_state(AdminState.waiting_for_del_channel)

@dp.message(AdminState.waiting_for_del_channel)
async def del_channel_step2(message: types.Message, state: FSMContext):
    ch_id = message.text.strip()
    conn = get_db()
    conn.cursor().execute("DELETE FROM channels WHERE channel_id = ?", (ch_id,))
    conn.commit()
    conn.close()
    
    await message.answer("✅ Kanal olib tashlandi!")
    await state.clear()
    await send_admin_panel(message)

# VIP BOSHQARUVI
@dp.callback_query(F.data == "adm_vip_menu")
async def vip_management_menu(callback: types.CallbackQuery):
    conn = get_db()
    c = conn.cursor()
    total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    vip_count = c.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1").fetchone()[0]
    conn.close()

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ VIP berish (1 oy)", callback_data="adm_give_vip")],
        [InlineKeyboardButton(text="👥 Barcha obunachilar", callback_data="adm_users_file")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_back_main")]
    ])
    await callback.message.edit_text(f"🌟 <b>VIP Boshqaruvi</b>\n\nJami foydalanuvchilar: {total_users} ta\nVIP obunachilar: {vip_count} ta", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "adm_give_vip")
async def give_vip_step1(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("VIP bermoqchi bo'lgan mijozingizning Telegram ID raqamini yuboring:")
    await state.set_state(AdminState.waiting_for_vip_id)

@dp.message(AdminState.waiting_for_vip_id)
async def give_vip_step2(message: types.Message, state: FSMContext):
    user_id = message.text.strip()
    expiry_date = (datetime.now() + timedelta(days=30)).isoformat()
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET is_vip = 1, vip_expiry = ? WHERE user_id = ?", (expiry_date, user_id))
    if c.rowcount == 0:
        await message.answer("❌ Bu foydalanuvchi bazada yo'q (Start bosmagan)!")
    else:
        conn.commit()
        await message.answer("✅ Foydalanuvchiga 1 oylik VIP berildi!")
        try:
            await bot.send_message(chat_id=user_id, text="🎉 <b>Sizga 1 oylik VIP obunasi taqdim etildi!</b>", parse_mode="HTML")
        except: pass
    conn.close()
    await state.clear()

@dp.callback_query(F.data == "adm_users_file")
async def users_file_generate(callback: types.CallbackQuery):
    conn = get_db()
    users = conn.cursor().execute("SELECT * FROM users").fetchall()
    conn.close()
    
    text = "FOYDALANUVCHILAR:\n\n"
    for u in users:
        vip_stat = "VIP" if u['is_vip'] else "Oddiy"
        text += f"ID: {u['user_id']} | User: @{u['username']} | Status: {vip_stat}\n"
        
    with open("users.txt", "w", encoding="utf-8") as f:
        f.write(text)
        
    await bot.send_document(
        chat_id=callback.from_user.id,
        document=FSInputFile("users.txt"),
        caption="👥 Barcha foydalanuvchilar (ID ro'yxati)"
    )
    os.remove("users.txt")

@dp.callback_query(F.data == "adm_back_main")
async def back_to_main_panel(callback: types.CallbackQuery):
    await callback.message.delete()
    await send_admin_panel(callback.message)

# ================= SERVER VA ISHGA TUSHIRISH =================
async def handle(request):
    return web.Response(text="KINO HUB Bot Server is Running Perfectly!")

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
    print("🚀 Baza SQLITE ga muvaffaqiyatli o'tdi, Bot ishga tushdi...")
    asyncio.create_task(web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
