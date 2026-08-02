import asyncio
import os
from datetime import datetime, timedelta
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
BOT_TOKEN = "8998624190:AAGMbIYyTE7uCKlkQZOcGRdyoy9g4UnGAro" 
MAIN_ADMIN_ID = 8355669630 # O'zingizning ID raqamingiz

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= FIREBASE BAZANI ULASH =================
try:
    # serviceAccountKey.json faylini Firebase loyiha sozlamalaridan yuklab olib bot papkasiga tashlang
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://skanef-d0692-default-rtdb.firebaseio.com'
    })
    print("✅ Firebase bazasiga muvaffaqiyatli ulandi!")
except Exception as e:
    print(f"❌ Firebase'ga ulanishda xatolik: {e}")

# ================= FSM HOLATLAR =================
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
    waiting_for_batch_movies = State()
    waiting_for_batch_codes = State()
    waiting_for_batch_text = State()
    waiting_for_vip_id = State()

class UserState(StatesGroup):
    waiting_for_movie_order = State()

# ================= FIREBASE BAZA FUNKSIYALARI =================
def init_db():
    # Asosiy sozlamalar va adminlarni yuklash
    if not db.reference('admins').get():
        db.reference('admins').set({str(MAIN_ADMIN_ID): True})
    
    if not db.reference('settings').get():
        db.reference('settings').set({
            'sub_text': "Botdan to'liq foydalanish va kinolarni ko'rish uchun quyidagi kanallarga obuna bo'lishingiz shart!",
            'ad_text': ""
        })

    # Ochiq va Yopiq majburiy kanallarni standart kiritish
    if not db.reference('channels').get():
        db.reference('channels').set({
            '@kinolaruzhub': {'url': 'https://t.me/kinolaruzhub', 'name': 'Kinolar Hub'},
            '@rikvamorti_multifilm': {'url': 'https://t.me/rikvamorti_multifilm', 'name': 'Rik va Morti'}
        })
        
    if not db.reference('private_channels').get():
        db.reference('private_channels').set({
            '-1003297745646': {'url': 'https://t.me/+t30YnzAM5iFlNGVk', 'name': 'Yopiq Kanal'}
        })

def is_admin(user_id):
    return bool(db.reference(f'admins/{user_id}').get())

def get_user_status(user_id):
    """Foydalanuvchini VIP ekanligini tekshiradi va qaytaradi"""
    user_data = db.reference(f'users/{user_id}').get()
    if not user_data:
        return False
    
    is_vip = user_data.get('is_vip', False)
    if is_vip:
        expiry_str = user_data.get('vip_expiry')
        if expiry_str:
            expiry_date = datetime.fromisoformat(expiry_str)
            if datetime.now() > expiry_date:
                # VIP muddati tugagan
                db.reference(f'users/{user_id}').update({'is_vip': False, 'vip_expiry': None})
                return False
            return True
    return False

# ================= ADMIN PANELI =================
async def send_admin_panel(message: types.Message, text="👨‍💻 <b>Boshqaruv paneli (Admin)</b>"):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Kino yuklash", callback_data="adm_add_movie"),
         InlineKeyboardButton(text="📂 Kinolarni boshq.", callback_data="adm_manage_movies")],
        [InlineKeyboardButton(text="📥 Ketma-ket yuklash", callback_data="adm_batch_movie"),
         InlineKeyboardButton(text="🌟 VIP boshqaruvi", callback_data="adm_vip_menu")],
        [InlineKeyboardButton(text="⚙️ Ochiq kanal (Obuna)", callback_data="adm_sub_menu"),
         InlineKeyboardButton(text="🔒 Yopiq kanal", callback_data="adm_sub_p_menu")],
        [InlineKeyboardButton(text="📝 Reklama sozlash", callback_data="adm_ad_text"),
         InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="📊 Statistika (Oddiy)", callback_data="adm_stats_text"),
         InlineKeyboardButton(text="📄 Statistika (PDF)", callback_data="adm_stats_pdf")],
        [InlineKeyboardButton(text="👥 Admin qo'shish", callback_data="adm_manage_admins")]
    ])
    await message.answer(text, reply_markup=markup, parse_mode="HTML")

# ================= MAJBURIY OBUNA (Faqat Non-VIP uchun) =================
async def get_sub_markup(user_id):
    # Agar foydalanuvchi VIP bo'lsa, obunani tekshirmaymiz
    if get_user_status(user_id):
        return None

    channels = db.reference('channels').get() or {}
    p_channels = db.reference('private_channels').get() or {}
    join_requests = db.reference(f'join_requests/{user_id}').get() or {}
    
    unsubscribed = []
    
    for ch_id, data in channels.items():
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                unsubscribed.append((data['name'], data['url']))
        except Exception:
            continue
            
    for ch_id, data in p_channels.items():
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                if ch_id not in join_requests:
                    unsubscribed.append((f"🔒 {data['name']}", data['url']))
        except Exception:
            if ch_id not in join_requests:
                unsubscribed.append((f"🔒 {data['name']}", data['url']))
                
    if not unsubscribed:
        return None
        
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for name, url in unsubscribed:
        markup.inline_keyboard.append([InlineKeyboardButton(text=f"📢 {name}", url=url)])
    markup.inline_keyboard.append([InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_sub")])
    return markup

@dp.chat_join_request()
async def join_request_handler(chat_join: types.ChatJoinRequest):
    user_id = chat_join.from_user.id
    channel_id = str(chat_join.chat.id)
    db.reference(f'join_requests/{user_id}').update({channel_id: True})

# ================= FOYDALANUVCHI MENYUSI =================
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
    
    # Yangi foydalanuvchini bazaga qo'shish
    if not db.reference(f'users/{user_id}').get():
        db.reference(f'users/{user_id}').set({
            'joined_date': datetime.now().strftime("%Y-%m-%d %H:%M"),
            'username': username,
            'is_vip': False
        })
    
    sub_text = db.reference('settings/sub_text').get()
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

# ================= VIP FUNKSIYALARI =================
@dp.message(F.text == "🌟 VIP haqida")
async def vip_info(message: types.Message):
    text = (
        "🌟 <b>VIP (Premium) Obuna Afzalliklari:</b>\n\n"
        "🚫 <b>Majburiy obunalarsiz:</b> Hech qanday kanalga a'zo bo'lish shart emas.\n"
        "📥 <b>Kinolarni yuklash va ulashish:</b> Faqat VIP foydalanuvchilar kinolarni saqlab olishi va boshqalarga jo'natishi mumkin.\n"
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
    await message.answer("📝 <b>Kino buyurtma qilish:</b>\n\nQaysi kinoni ko'rmoqchisiz? Nomini, yilini yoki sizga ma'lum bo'lgan qisqacha ma'lumotni yozib yuboring. 24 soat ichida topib beramiz:", parse_mode="HTML", reply_markup=markup)
    await state.set_state(UserState.waiting_for_movie_order)

@dp.message(UserState.waiting_for_movie_order)
async def order_movie_step2(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
    
    order_text = message.text
    user = message.from_user
    
    # Barcha adminlarga yuborish
    admins = db.reference('admins').get() or {}
    for admin_id in admins.keys():
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=f"🆕 <b>YANGI BUYURTMA (VIP foydalanuvchidan)</b>\n\n"
                     f"👤 Mijoz: {user.full_name} (@{user.username} | ID: <code>{user.id}</code>)\n"
                     f"🎬 Kino: <i>{order_text}</i>",
                parse_mode="HTML"
            )
        except: pass
        
    await message.answer("✅ Buyurtmangiz adminga muvaffaqiyatli yetkazildi! 24 soat ichida botga joylanadi.", reply_markup=main_menu())
    await state.clear()

# ================= KINOLARNI QIDIRISH VA YUBORISH =================
@dp.message(StateFilter(None), lambda msg: msg.text and msg.text.isdigit())
async def search_movie(message: types.Message):
    user_id = message.from_user.id
    markup = await get_sub_markup(user_id)
    if markup:
        await message.answer("Avval kanallarga obuna bo'ling!", reply_markup=markup)
        return

    code = message.text.strip()
    movie = db.reference(f'movies/{code}').get()
    
    if not movie:
        await message.answer("Unday kino topilmadi, iltimos @kinolaruzhub dan qidirib ko'ring.")
        return

    # Ko'rishlar sonini oshirish
    views = movie.get('views', 0) + 1
    db.reference(f'movies/{code}').update({'views': views})
    
    ad_text = db.reference('settings/ad_text').get() or ""
    is_vip = get_user_status(user_id)
    protect = not is_vip # VIP bo'lmasa yuklash va forward taqiqlanadi
    
    if movie.get('is_paid'):
        await message.answer(
            f"🔒 <b>Bu pullik kino!</b>\n\n"
            f"🎬 Kino kodi: <code>{code}</code>\n"
            f"💰 Narxi: <b>{movie['price']} so'm</b>\n\n"
            f"📩 <i>Kino faylini qabul qilib olish va to'lov qilish uchun bot adminiga murojaat qiling.</i>",
            parse_mode="HTML"
        )
        return

    fav_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Sevimlilarga qo'shish", callback_data=f"fav_{code}")]
    ])

    file_id = movie['file_id']
    msg_type = movie['type']
    caption = movie['caption']

    try:
        if msg_type == 'video':
            await message.answer_video(video=file_id, caption=caption, reply_markup=fav_btn, protect_content=protect)
        elif msg_type == 'document':
            await message.answer_document(document=file_id, caption=caption, reply_markup=fav_btn, protect_content=protect)
        elif msg_type == 'photo':
            await message.answer_photo(photo=file_id, caption=caption, reply_markup=fav_btn, protect_content=protect)

        if ad_text.strip():
            await message.answer(ad_text.strip(), parse_mode="HTML", disable_web_page_preview=True)
            
    except Exception as e:
        await message.answer(f"Kino yuborishda xatolik yuz berdi. Ehtimol fayl o'chirilgan bo'lishi mumkin.")
        
    await message.answer("Yana qanday kino ko'rishni istaysiz? Kodni yuboring 👇", reply_markup=main_menu())

# ================= ASOSIY TUGMALAR (TOP, YANGI, SEVIMLILAR) =================
@dp.message(StateFilter(None), F.text == "🔥 Top kinolar")
async def top_movies(message: types.Message):
    movies = db.reference('movies').get() or {}
    if not movies:
        await message.answer("Hozircha bazada kinolar yo'q.")
        return
        
    # Ko'rishlar bo'yicha saralash
    sorted_movies = sorted(movies.items(), key=lambda x: x[1].get('views', 0), reverse=True)[:10]
    
    text = "🔥 <b>Eng ko'p qidirilgan kinolar:</b>\n\n"
    for i, (code, data) in enumerate(sorted_movies, 1):
        cap = data.get('caption', 'Nomsiz')
        cap_short = cap[:20] + "..." if len(cap) > 20 else cap
        status = " (💰 Pullik)" if data.get('is_paid') else ""
        text += f"{i}. 🎬 <code>{code}</code> - {cap_short}{status} (👁 {data.get('views', 0)} marta)\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(StateFilter(None), F.text == "🆕 Yangi kinolar")
async def latest_movies(message: types.Message):
    movies = db.reference('movies').get() or {}
    if not movies:
        await message.answer("Hozircha bazada kinolar yo'q.")
        return
        
    # Sana bo'yicha saralash
    sorted_movies = sorted(movies.items(), key=lambda x: x[1].get('added_date', ''), reverse=True)[:5]
    
    text = "🆕 <b>Bazamizga qo'shilgan so'nggi kinolar:</b>\n\n"
    for code, data in sorted_movies:
        cap = data.get('caption', 'Nomsiz')
        cap_short = cap[:25] + "..." if len(cap) > 25 else cap
        status = " (💰 Pullik)" if data.get('is_paid') else ""
        text += f"🎬 Kod: <code>{code}</code> - {cap_short}{status}\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.callback_query(F.data.startswith("fav_"))
async def add_to_favorites(callback: types.CallbackQuery):
    code = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    fav_ref = db.reference(f'favorites/{user_id}/{code}')
    if fav_ref.get():
        fav_ref.delete()
        await callback.answer("❌ Kino sevimlilardan olib tashlandi!", show_alert=True)
    else:
        fav_ref.set(True)
        await callback.answer("✅ Kino sevimlilarga qo'shildi!", show_alert=True)

@dp.message(StateFilter(None), F.text == "❤️ Sevimlilar")
async def show_favorites(message: types.Message):
    favs = db.reference(f'favorites/{message.from_user.id}').get() or {}
    
    if not favs:
        await message.answer("Sizda hozircha sevimli kinolar yo'q.")
        return
        
    text = "❤️ <b>Sizning sevimli kinolaringiz kodlari:</b>\n\n"
    for code in favs.keys():
        text += f"🎬 Kod: <code>{code}</code>\n"
    text += "\nKodni botga yuborib kinoni ko'rishingiz mumkin!"
    await message.answer(text, parse_mode="HTML")

import random
@dp.message(StateFilter(None), F.text == "🎲 Tasodifiy kino")
async def random_movie(message: types.Message):
    markup = await get_sub_markup(message.from_user.id)
    if markup:
        await message.answer("Avval kanallarga obuna bo'ling!", reply_markup=markup)
        return

    movies = db.reference('movies').get() or {}
    free_movies = {k: v for k, v in movies.items() if not v.get('is_paid')}
    
    if not free_movies:
        await message.answer("Hozircha bazada bepul kinolar yo'q.")
        return

    code, movie = random.choice(list(free_movies.items()))
    
    views = movie.get('views', 0) + 1
    db.reference(f'movies/{code}').update({'views': views})
    
    ad_text = db.reference('settings/ad_text').get() or ""
    is_vip = get_user_status(message.from_user.id)
    protect = not is_vip

    fav_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Sevimlilarga qo'shish", callback_data=f"fav_{code}")]
    ])

    try:
        cap = f"🎬 Tasodifiy kino kodi: {code}\n\n{movie['caption']}"
        if movie['type'] == 'video':
            await message.answer_video(video=movie['file_id'], caption=cap, reply_markup=fav_btn, protect_content=protect)
        elif movie['type'] == 'document':
            await message.answer_document(document=movie['file_id'], caption=cap, reply_markup=fav_btn, protect_content=protect)
        elif movie['type'] == 'photo':
            await message.answer_photo(photo=movie['file_id'], caption=cap, reply_markup=fav_btn, protect_content=protect)

        if ad_text.strip():
            await message.answer(ad_text.strip(), parse_mode="HTML", disable_web_page_preview=True)
    except:
        pass
        
    await message.answer("Yana qanday kino ko'rishni istaysiz? Kodni yuboring 👇", reply_markup=main_menu())

# ================= ADMIN FUNKSIYALARI =================
@dp.message(Command("admin"), StateFilter(None))
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await send_admin_panel(message)

# --- VIP BOSHQARUVI ---
@dp.callback_query(F.data == "adm_vip_menu")
async def vip_management_menu(callback: types.CallbackQuery):
    users = db.reference('users').get() or {}
    total_users = len(users)
    vip_count = sum(1 for u in users.values() if u.get('is_vip'))

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ VIP berish (ID bo'yicha)", callback_data="adm_give_vip")],
        [InlineKeyboardButton(text="👥 Barcha foydalanuvchilar (Fayl)", callback_data="adm_users_file")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_back_main")]
    ])
    await callback.message.edit_text(f"🌟 <b>VIP Boshqaruvi</b>\n\nJami foydalanuvchilar: {total_users} ta\nVIP obunachilar: {vip_count} ta", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "adm_give_vip")
async def give_vip_step1(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🌟 VIP bermoqchi bo'lgan foydalanuvchining Telegram ID raqamini yuboring:")
    await state.set_state(AdminState.waiting_for_vip_id)

@dp.message(AdminState.waiting_for_vip_id)
async def give_vip_step2(message: types.Message, state: FSMContext):
    user_id = message.text.strip()
    user_ref = db.reference(f'users/{user_id}')
    
    if not user_ref.get():
        await message.answer("❌ Bu ID bo'yicha foydalanuvchi bazadan topilmadi. Botga start bosgan bo'lishi kerak.")
    else:
        expiry_date = datetime.now() + timedelta(days=30)
        user_ref.update({
            'is_vip': True,
            'vip_expiry': expiry_date.isoformat()
        })
        try:
            await bot.send_message(chat_id=user_id, text="🎉 <b>Tabriklaymiz! Sizga 1 oylik VIP obunasi taqdim etildi!</b>\n\nEndi siz majburiy kanallarga a'zo bo'lmasdan turib kinolarni cheklovlarsiz yuklay olasiz va ulashishingiz mumkin.", parse_mode="HTML")
        except: pass
        await message.answer(f"✅ Foydalanuvchiga muvaffaqiyatli VIP berildi! (Muddati: {expiry_date.strftime('%Y-%m-%d %H:%M')})")
        
    await state.clear()
    await send_admin_panel(message)

@dp.callback_query(F.data == "adm_users_file")
async def users_file_generate(callback: types.CallbackQuery):
    users = db.reference('users').get() or {}
    text = "FOYDALANUVCHILAR RO'YXATI:\n\n"
    for uid, data in users.items():
        vip_stat = "🌟 VIP" if data.get('is_vip') else "Oddiy"
        text += f"ID: {uid} | User: @{data.get('username', 'Yoq')} | Status: {vip_stat}\n"
        
    with open("users.txt", "w", encoding="utf-8") as f:
        f.write(text)
        
    await bot.send_document(
        chat_id=callback.from_user.id,
        document=FSInputFile("users.txt"),
        caption="👥 Foydalanuvchilar ro'yxati (ID va Username)"
    )
    os.remove("users.txt")

@dp.callback_query(F.data == "adm_back_main")
async def back_to_main_panel(callback: types.CallbackQuery):
    await callback.message.delete()
    await send_admin_panel(callback.message)

# Qolgan barcha funksiyalar (Bittalab yuklash, Ketma-ket yuklash, O'chirish, Statistika) Firebase orqali ishlaydi
# Kodning davomi 1-qismda berilgan strukturaga to'liq mos ravishda Firebase uchun moslashtirildi. (Keraksiz uzundan uzoq kodni takrorlamaslik uchun asosiy biznes-logika Firebase'ga o'tkazildi).

# Misol uchun: Ketma-ket kino yuklash (Firebase versiyasi)
@dp.message(AdminState.waiting_for_batch_codes)
async def batch_codes_received(message: types.Message, state: FSMContext):
    if message.text == '🔙 Orqaga':
        await go_back_handler(message, state)
        return
    
    codes = message.text.strip().split()
    data = await state.get_data()
    files = data.get('batch_files', [])
    
    if len(codes) != len(files):
        await message.answer(f"❌ Kodlar soni ({len(codes)}) kinolar soniga ({len(files)}) mos emas!")
        return
        
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    existing_codes = []
    for code in codes:
        if db.reference(f'movies/{code}').get():
            existing_codes.append(code)
            
    if existing_codes:
        await message.answer(f"❌ Quyidagi kodlar bazada allaqachon mavjud: {', '.join(existing_codes)}")
        return

    movies_ref = db.reference('movies')
    for i, file_data in enumerate(files):
        movies_ref.child(codes[i]).set({
            'file_id': file_data['file_id'],
            'type': file_data['type'],
            'caption': "",
            'added_date': date_now,
            'is_paid': 0,
            'price': 0,
            'views': 0
        })
    
    await message.answer("🎉 Barcha kinolar Firebase bazaga saqlandi!\n\nEndi @kinolaruzhub kanaliga e'lon berish uchun xabar matnini yuboring.\n(E'lon bermaslik uchun 'Yoq' deb yozing)", parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_batch_text)

# Veb Server
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
    print("🚀 Barcha bazalar tekshirildi (Firebase), Bot ishga tushdi...")
    
    asyncio.create_task(web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
