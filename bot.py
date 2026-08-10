import asyncio
import logging
import re
import sys
import time
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import json
import os
from datetime import date
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from config import BOT_TOKEN, SECRET_GROUP_ID
from ai_service import is_taxi_order

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# Bot tokenini tekshirish
if not BOT_TOKEN:
    logging.error("BOT_TOKEN topilmadi! Iltimos, .env faylini to'ldiring.")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Bo'lib-bo'lib yozgan xabarlarni birlashtirish uchun buffer
# Kalit: (chat_id, user_id) → {"texts": [...], "task": asyncio.Task, "message": ...}
_pending: dict = {}

# Dublikat xabarlarni bloklash uchun kesh
# Kalit: (chat_id, user_id, xabar_boshlanmasi) → vaqt (timestamp)
_seen_hashes: dict = {}
SEEN_TTL = 120  # soniya — shu vaqt ichida bir xil xabar kelsa, o'tkazib yuboriladi
COMBINE_DELAY = 1.5  # soniya — xabarlarni birlashtirish kutish vaqti

# Yo'nalishlar bo'yicha guruhlar xaritasi (Routing)
# Masalan: "toshkent-samarqand" yo'nalishi uchun qaysi guruh ID siga tashlash kerakligi
ROUTES = {
    # "toshkent-samarqand": "-1001234567890",
    # "farg'ona-toshkent": "-1000987654321",
}

GROUPS_FILE = "groups.json"
GROUPS_CACHE = None

def load_groups():
    global GROUPS_CACHE
    if GROUPS_CACHE is not None:
        return GROUPS_CACHE
    if os.path.exists(GROUPS_FILE):
        try:
            with open(GROUPS_FILE, "r", encoding="utf-8") as f:
                GROUPS_CACHE = json.load(f)
                return GROUPS_CACHE
        except Exception:
            GROUPS_CACHE = {}
            return GROUPS_CACHE
    GROUPS_CACHE = {}
    return GROUPS_CACHE

def save_group(chat_id, title):
    groups = load_groups()
    chat_id_str = str(chat_id)
    if chat_id_str not in groups or groups[chat_id_str] != title:
        groups[chat_id_str] = title
        try:
            with open(GROUPS_FILE, "w", encoding="utf-8") as f:
                json.dump(groups, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logging.error(f"Guruh saqlashda xatolik: {e}")

ADMINS_FILE = "admins.json"
ADMINS_CACHE = None

def load_admins():
    global ADMINS_CACHE
    if ADMINS_CACHE is not None:
        return ADMINS_CACHE
    if os.path.exists(ADMINS_FILE):
        try:
            with open(ADMINS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Eski format (list) ni yangi formatga (dict) o'tkazish
                if isinstance(data, list):
                    ADMINS_CACHE = {str(uid): {"name": str(uid), "username": None} for uid in data}
                else:
                    ADMINS_CACHE = data
                return ADMINS_CACHE
        except Exception:
            ADMINS_CACHE = {}
            return ADMINS_CACHE
    ADMINS_CACHE = {}
    return ADMINS_CACHE

def save_admins(admins: dict):
    global ADMINS_CACHE
    ADMINS_CACHE = admins
    try:
        with open(ADMINS_FILE, "w", encoding="utf-8") as f:
            json.dump(admins, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Adminlarni saqlashda xatolik: {e}")

STATS_FILE = "stats.json"
STATS_CACHE = None

def load_stats():
    global STATS_CACHE
    if STATS_CACHE is not None:
        return STATS_CACHE
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                STATS_CACHE = json.load(f)
                return STATS_CACHE
        except Exception:
            STATS_CACHE = {}
            return STATS_CACHE
    STATS_CACHE = {}
    return STATS_CACHE

def increment_group_stat(chat_id, title):
    stats = load_stats()
    chat_id_str = str(chat_id)
    today = str(date.today())  # masalan: "2026-08-10"
    
    if chat_id_str not in stats:
        stats[chat_id_str] = {"title": title, "total": 0, "daily": {}}
    
    # Eski formatdan yangi formatga o'tkazish
    if "count" in stats[chat_id_str] and "total" not in stats[chat_id_str]:
        stats[chat_id_str]["total"] = stats[chat_id_str].pop("count")
        stats[chat_id_str]["daily"] = {}
    
    stats[chat_id_str]["total"] = stats[chat_id_str].get("total", 0) + 1
    stats[chat_id_str]["title"] = title
    
    if "daily" not in stats[chat_id_str]:
        stats[chat_id_str]["daily"] = {}
    stats[chat_id_str]["daily"][today] = stats[chat_id_str]["daily"].get(today, 0) + 1
    
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Statistikani saqlashda xatolik: {e}")

class AdminStates(StatesGroup):
    waiting_for_admin_id = State()
    waiting_for_group_input = State()

admin_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👥 Guruhlar"), KeyboardButton(text="👮 Adminlar")],
        [KeyboardButton(text="➕ Admin qo'shish"), KeyboardButton(text="➕ Guruh qo'shish")],
        [KeyboardButton(text="❌ Guruhni o'chirish"), KeyboardButton(text="❌ Adminni o'chirish")],
        [KeyboardButton(text="📊 Statistika")]
    ],
    resize_keyboard=True
)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.chat.type == "private":
        await message.answer(
            "🚕 <b>Taksi Bot - Admin Panel</b>\n\n"
            "👋 Xush kelibsiz! Men taksi buyurtmalarini avtomatik saralovchi botman.\n\n"
            "<b>Nima qila olaman?</b>\n"
            "👥 Guruhlarni boshqarish\n"
            "👮 Adminlarni boshqarish\n"
            "📊 Statistikani ko'rish\n\n"
            "Quyidagi menyudan foydalaning ⬇️",
            reply_markup=admin_menu
        )
    else:
        await message.answer("🚕 Assalomu alaykum! Men taksi buyurtmalarini saralovchi botman.")

@dp.message(F.text == "👥 Guruhlar", F.chat.type == "private")
async def show_groups(message: types.Message):
    groups = load_groups()
    if not groups:
        await message.answer("Bot hozircha hech qanday guruhda xabar o'qimagan yoki qo'shilmagan.")
        return
        
    msg = await message.answer("Guruhlar ro'yxati yuklanmoqda, kuting...")
    
    async def fetch_group_info(chat_id_str, title):
        try:
            chat = await bot.get_chat(chat_id_str)
            if chat.username:
                url = f"https://t.me/{chat.username}"
            else:
                url = chat.invite_link or await bot.export_chat_invite_link(chat_id_str)
            return f"<b>{title}</b>\n   🔗 {url}"
        except Exception as e:
            logging.error(f"Guruh linkini olishda xatolik ({chat_id_str}): {e}")
            return f"<b>{title}</b>\n   🔒 <i>Link olish uchun bot guruhda admin emas</i>"

    tasks = [fetch_group_info(cid, title) for cid, title in groups.items()]
    results = await asyncio.gather(*tasks)

    text = "👥 <b>Guruhlar ro'yxati:</b>\n\n"
    for i, res in enumerate(results, 1):
        text += f"{i}. {res}\n\n"
            
    await msg.edit_text(text, disable_web_page_preview=True)

@dp.message(F.text == "👮 Adminlar", F.chat.type == "private")
async def show_admins(message: types.Message):
    admins = load_admins()
    if not admins:
        await message.answer("Adminlar ro'yxati bo'sh.")
        return
    
    text = "👑 <b>Adminlar ro'yxati:</b>\n\n"
    for i, (admin_id, info) in enumerate(admins.items(), 1):
        name = info.get("name", admin_id)
        username = info.get("username")
        username_str = f" (@{username})" if username else ""
        text += f"{i}. {name}{username_str}\n   🔑 ID: <code>{admin_id}</code>\n\n"
        
    await message.answer(text)

@dp.message(F.text == "➕ Admin qo'shish", F.chat.type == "private")
async def add_admin_start(message: types.Message, state: FSMContext):
    await message.answer("Yangi adminning Telegram ID raqamini yuboring:")
    await state.set_state(AdminStates.waiting_for_admin_id)

@dp.message(AdminStates.waiting_for_admin_id, F.chat.type == "private")
async def add_admin_finish(message: types.Message, state: FSMContext):
    if not message.text:
        return
        
    # Agar foydalanuvchi boshqa tugmani bossa, holatdan chiqaramiz
    if not message.text.isdigit():
        await state.clear()
        await message.answer("Admin qo'shish bekor qilindi. Boshqa menyuga o'tdingiz.", reply_markup=admin_menu)
        return
    
    new_admin_id = int(message.text)
    
    # ID ni tekshirish
    try:
        user = await bot.get_chat(new_admin_id)
        if user.type != "private":
            await message.answer("Xatolik: Bu ID shaxsiy foydalanuvchiga tegishli emas (kanal yoki guruh ID si). Boshqa ID kiriting:")
            return
        name = user.full_name
        username = user.username  # @username yoki None
    except Exception:
        await message.answer("Xatolik: Bunday ID topilmadi. Yoki bu ID noto'g'ri, yoki foydalanuvchi botga hali '/start' bosmagan. Iltimos, tekshirib qaytadan kiriting:")
        return

    admins = load_admins()
    admin_id_str = str(new_admin_id)
    if admin_id_str not in admins:
        admins[admin_id_str] = {"name": name, "username": username}
        save_admins(admins)
        username_str = f" (@{username})" if username else ""
        await message.answer(f"✅ Yangi admin qo'shildi:\n👤 {name}{username_str}\n🔑 ID: <code>{new_admin_id}</code>")
    else:
        await message.answer("Bu foydalanuvchi allaqachon admin.")
    
    await state.clear()

@dp.message(F.text == "➕ Guruh qo'shish", F.chat.type == "private")
async def add_group_start(message: types.Message):
    await message.answer(
        "➕ <b>Yangi guruh qo'shish</b>\n\n"
        "Guruhga bot qo'shish uchun:\n\n"
        "1️⃣ Guruhingizni oching\n"
        "2️⃣ <b>A'zolar → A'zo qo'shish</b>\n"
        "3️⃣ <code>@orderataxibot</code> ni qidirib qo'shing\n\n",
        parse_mode="HTML",
        reply_markup=admin_menu
    )

@dp.message(AdminStates.waiting_for_group_input, F.chat.type == "private")
async def add_group_finish(message: types.Message, state: FSMContext):
    if not message.text:
        return
        
    text_input = message.text.strip()
    
    # Bekor qilish yoki boshqa menyu bosilsa
    if text_input in ["👥 Guruhlar", "👮 Adminlar", "➕ Admin qo'shish", "➕ Guruh qo'shish", "❌ Guruhni o'chirish", "❌ Adminni o'chirish", "📊 Statistika"]:
        await state.clear()
        await message.answer("Guruh qo'shish bekor qilindi.", reply_markup=admin_menu)
        return
        
    # ID yoki Username parse qilish
    target = text_input
    if "t.me/" in text_input:
        target = "@" + text_input.split("t.me/")[-1].replace("/", "")

    if target.startswith("-100") and target[4:].isdigit():
        target = int(target)
    elif target.replace("-", "").isdigit():
        target = int(target)

    try:
        chat = await bot.get_chat(target)
        if chat.type not in ["group", "supergroup", "channel"]:
            await message.answer("⚠️ Xatolik: Bu ID yoki link shaxsiy foydalanuvchiga tegishli. Iltimos, guruh ID si yoki linkini yuboring:")
            return
            
        save_group(chat.id, chat.title)
        await state.clear()
        await message.answer(
            f"✅ <b>Guruh muvaffaqiyatli qo'shildi!</b>\n\n"
            f"📌 <b>Nomi:</b> {chat.title}\n"
            f"🔑 <b>ID:</b> <code>{chat.id}</code>",
            reply_markup=admin_menu
        )
    except Exception as e:
        logging.error(f"Guruh qo'shishda xatolik ({target}): {e}")
        await message.answer(
            f"⚠️ <b>Xatolik:</b> Guruh topilmadi yoki bot u yerda mavjud emas.\n\n"
            f"<b>Sababi:</b> Bot ushbu guruhga qo'shilmagan bo'lishi mumkin. Iltimos, avval botni guruhga qo'shing so'ngra qayta urinib ko'ring:",
            reply_markup=admin_menu
        )

@dp.message(F.text == "❌ Guruhni o'chirish", F.chat.type == "private")
async def delete_groups_menu(message: types.Message):
    groups = load_groups()
    if not groups:
        await message.answer("O'chirish uchun guruhlar yo'q.")
        return
    
    inline_keyboard = []
    for chat_id_str, title in groups.items():
        inline_keyboard.append([InlineKeyboardButton(text=f"❌ {title}", callback_data=f"del_grp_{chat_id_str}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.answer("O'chirmoqchi bo'lgan guruhni tanlang:", reply_markup=markup)

@dp.callback_query(F.data.startswith("del_grp_"))
async def delete_group_callback(call: types.CallbackQuery):
    chat_id_str = call.data.replace("del_grp_", "")
    groups = load_groups()
    
    if chat_id_str in groups:
        title = groups.pop(chat_id_str)
        with open(GROUPS_FILE, "w", encoding="utf-8") as f:
            json.dump(groups, f, ensure_ascii=False, indent=4)
        
        # Botni guruhdan chiqarish
        try:
            await bot.leave_chat(int(chat_id_str))
            await call.answer(f"✅ {title} o'chirildi va botni guruhdan chiqardim", show_alert=True)
        except Exception as e:
            logging.warning(f"Guruhdan chiqishda xatolik ({chat_id_str}): {e}")
            await call.answer(f"✅ {title} ro'yxatdan o'chirildi (guruhdan chiqishda xatolik)", show_alert=True)
        
        if not groups:
            await call.message.edit_text("Hamma guruhlar o'chirildi.")
            return
        
        # Ro'yxatni link + o'chirish formatida yangilash
        inline_keyboard = []
        for cid, t in groups.items():
            try:
                chat = await bot.get_chat(cid)
                if chat.username:
                    url = f"https://t.me/{chat.username}"
                else:
                    url = chat.invite_link or await bot.export_chat_invite_link(cid)
                inline_keyboard.append([
                    InlineKeyboardButton(text=f"💬 {t}", url=url),
                    InlineKeyboardButton(text="🗑", callback_data=f"del_grp_{cid}")
                ])
            except Exception:
                inline_keyboard.append([
                    InlineKeyboardButton(text=f"🔒 {t}", callback_data="dummy"),
                    InlineKeyboardButton(text="🗑", callback_data=f"del_grp_{cid}")
                ])
            
        markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        await call.message.edit_text("Bot qo'shilgan guruhlar:", reply_markup=markup)
    else:
        await call.answer("Guruh topilmadi.", show_alert=True)

@dp.callback_query(F.data == "dummy")
async def dummy_callback(call: types.CallbackQuery):
    await call.answer("Bot bu guruhda admin emas, shuning uchun linkini ololmaydi.", show_alert=True)

@dp.message(F.text == "❌ Adminni o'chirish", F.chat.type == "private")
async def delete_admins_menu(message: types.Message):
    admins = load_admins()
    if not admins:
        await message.answer("O'chirish uchun adminlar yo'q.")
        return
    
    inline_keyboard = []
    for admin_id_str, info in admins.items():
        name = info.get("name", admin_id_str)
        username = info.get("username")
        label = f"{name} (@{username})" if username else f"{name} ({admin_id_str})"
        inline_keyboard.append([InlineKeyboardButton(text=f"❌ {label}", callback_data=f"del_adm_{admin_id_str}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.answer("O'chirmoqchi bo'lgan adminni tanlang:", reply_markup=markup)

@dp.callback_query(F.data.startswith("del_adm_"))
async def delete_admin_callback(call: types.CallbackQuery):
    admin_id_str = call.data.replace("del_adm_", "")
    admins = load_admins()
    
    if admin_id_str in admins:
        removed = admins.pop(admin_id_str)
        save_admins(admins)
        await call.answer(f"{removed.get('name', admin_id_str)} o'chirildi", show_alert=True)
        
        # Tugmalarni yangilash
        inline_keyboard = []
        for aid_str, info in admins.items():
            name = info.get("name", aid_str)
            username = info.get("username")
            label = f"{name} (@{username})" if username else f"{name} ({aid_str})"
            inline_keyboard.append([InlineKeyboardButton(text=f"❌ {label}", callback_data=f"del_adm_{aid_str}")])
            
        if inline_keyboard:
            markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
            await call.message.edit_text("O'chirmoqchi bo'lgan adminni tanlang:", reply_markup=markup)
        else:
            await call.message.edit_text("Hamma adminlar o'chirildi.")
    else:
        await call.answer("Admin topilmadi.", show_alert=True)

@dp.message(F.text == "📊 Statistika", F.chat.type == "private")
async def show_stats(message: types.Message):
    stats = load_stats()
    if not stats:
        await message.answer("Hali hech qanday buyurtma qayd etilmagan.")
        return
    
    today = str(date.today())
    
    # Jami buyurtmalar soni bo'yicha saralash
    def get_total(item):
        d = item[1]
        return d.get("total", d.get("count", 0))
    
    sorted_stats = sorted(stats.items(), key=get_total, reverse=True)
    
    text = "📊 <b>Guruhlar bo'yicha statistika:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (chat_id_str, data) in enumerate(sorted_stats):
        medal = medals[i] if i < 3 else f"{i+1}."
        total = data.get("total", data.get("count", 0))
        today_count = data.get("daily", {}).get(today, 0)
        text += f"{medal} <b>{data['title']}</b>\n"
        text += f"   📅 Bugun: <b>{today_count}</b> | 📊 Jami: <b>{total}</b>\n\n"
    
    total_all = sum(d.get("total", d.get("count", 0)) for d in stats.values())
    today_all = sum(d.get("daily", {}).get(today, 0) for d in stats.values())
    text += f"──────────\n📅 <b>Bugungi jami:</b> {today_all} ta\n📊 <b>Umumiy jami:</b> {total_all} ta"
    
    await message.answer(text)

@dp.message(F.chat.type.in_({"group", "supergroup"}) & (F.chat.id != SECRET_GROUP_ID))
async def handle_public_group_messages(message: types.Message):
    # Guruh ID sini terminalga chiqarib turamiz (foydalanuvchi bilib olishi uchun)
    logging.info(f"Guruhdan xabar keldi. Guruh ID: {message.chat.id}, Nomi: {message.chat.title}")
    
    # Guruhni ro'yxatga saqlab qo'yamiz
    save_group(message.chat.id, message.chat.title)
    
    # 1. from_user None bo'lishi mumkin (Anonymous Admin yoki tizim xabari)
    if not message.from_user:
        return

    # 2. Boshqa botlardan kelgan xabarlarni o'tkazib yuboramiz
    if message.from_user.is_bot:
        return

    # 3. Forward qilingan xabarlarni o'tkazib yuboramiz (boshqa guruhdan ko'chirilgan)
    if message.forward_from or message.forward_from_chat or message.forward_date:
        return

    # 4. Faqat matnli xabarlarni tahlil qilamiz (rasm, video, stikerlar o'tkazib yuboriladi)
    if not message.text:
        return

    text = message.text.strip()

    # 5. Juda qisqa xabarlarni o'tkazib yuboramiz
    if len(text) < 4:
        return

    # 6. Faqat raqamdan iborat xabarlarni bloklash (masalan: "100", "998901234567")
    if re.fullmatch(r'[\d\s\+\-\(\)]+', text):
        return

    # 7. Dublikat xabar filtri (SEEN_TTL soniya ichida bir xil xabar kelsa bloklash)
    user_id = message.from_user.id
    chat_id = message.chat.id
    hash_key = (chat_id, user_id, text[:40])
    now_ts = time.time()
    
    # Eskirgan yozuvlarni kesh to'lganda tozalaymiz
    if len(_seen_hashes) > 200:
        expired = [k for k, v in _seen_hashes.items() if now_ts - v > SEEN_TTL]
        for k in expired:
            _seen_hashes.pop(k, None)
            
    if hash_key in _seen_hashes:
        return
    _seen_hashes[hash_key] = now_ts

    # 8. Bo'lib-bo'lib yozgan xabarlarni birlashtirish (COMBINE_DELAY soniya kutamiz)
    buf_key = (chat_id, user_id)

    async def process_combined():
        try:
            await asyncio.sleep(COMBINE_DELAY)
            entry = _pending.pop(buf_key, None)
            if not entry:
                return
            combined_text = " ".join(entry["texts"])
            first_msg = entry["message"]
            logging.info(f"Birlashtirilgan xabar ({len(entry['texts'])} qism): {combined_text[:80]}")
            ai_data = await asyncio.to_thread(is_taxi_order, combined_text)
            await send_order(first_msg, ai_data, combined_text)
        except Exception as exc:
            # Xatolik bo'lsa ham buffer tozalansin (memory leak oldini olish)
            _pending.pop(buf_key, None)
            logging.error(f"process_combined xatolik: {exc}")

    if buf_key in _pending:
        # Mavjud bufferga qo'shib ketamiz
        _pending[buf_key]["texts"].append(text)
    else:
        # Yangi entry va taymer boshlaymiz
        task = asyncio.create_task(process_combined())
        _pending[buf_key] = {"texts": [text], "task": task, "message": message}


async def send_order(message: types.Message, ai_data: dict, display_text: str):
    """Tasdiqlangan buyurtmani maxfiy guruhga yuboradi."""
    if not ai_data.get("is_taxi", False):
        return

    # Statistikani yangilash
    increment_group_stat(message.chat.id, message.chat.title)
    
    # Asl xabarga ssilka (Direct Message Link)
    if message.chat.username:
        msg_link = f"https://t.me/{message.chat.username}/{message.message_id}"
    else:
        clean_id = str(message.chat.id).replace("-100", "")
        msg_link = f"https://t.me/c/{clean_id}/{message.message_id}"
        
    profile_url = f"https://t.me/{message.from_user.username}" if message.from_user.username else f"tg://user?id={message.from_user.id}"

    # Maxfiy guruhga jo'natish uchun tugmalar
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Mijoz profili", url=profile_url),
                InlineKeyboardButton(text="💬 Asl xabarga o'tish", url=msg_link)
            ]
        ]
    )
    
    client_name = message.from_user.full_name
    
    from_loc = ai_data.get("from_location", "Noma'lum")
    to_loc = ai_data.get("to_location", "Noma'lum")
    time_val = ai_data.get("time", "Noma'lum")
    passengers = ai_data.get("passenger_count", "Noma'lum")
    price = ai_data.get("price", "Noma'lum")
    phone = ai_data.get("phone_number", "Noma'lum")
    is_package = ai_data.get("is_package", False)
    
    forward_text = (
        f"🚕 <b>Yangi buyurtma!</b>\n\n"
        f"👤 <b>Mijoz:</b> {client_name}\n"
        f"📍 <b>Qayerdan:</b> {from_loc}\n"
        f"🏁 <b>Qayerga:</b> {to_loc}\n"
        f"🕒 <b>Vaqti:</b> {time_val}\n"
    )
    
    if is_package:
        forward_text += f"📦 <b>Turi:</b> Posilka\n"
    else:
        forward_text += f"👥 <b>Necha kishi:</b> {passengers}\n"
        
    forward_text += (
        f"💰 <b>Narxi:</b> {price}\n"
        f"📞 <b>Telefon:</b> {phone}\n\n"
        f"📝 <b>Asl xabar:</b>\n{display_text}"
    )
    
    route_key = ai_data.get("route", "")
    target_group_id = ROUTES.get(route_key, SECRET_GROUP_ID)
    
    try:
        await bot.send_message(
            chat_id=target_group_id,
            text=forward_text,
            reply_markup=keyboard
        )
        logging.info(f"Yangi buyurtma ({route_key}) guruhga yuborildi: {target_group_id}")
    except Exception as e:
        logging.error(f"Xabarni guruhga yuborishda xatolik ({target_group_id}): {e}")
        # Adminlarga xatolik haqida xabar yuboramiz
        admins = load_admins()
        error_msg = (
            f"⚠️ <b>Bot xatoligi!</b>\n\n"
            f"Buyurtma maqsad guruhga yuborilmadi.\n"
            f"🎯 Guruh: <code>{target_group_id}</code>\n"
            f"❌ Sabab: <code>{e}</code>\n\n"
            f"Bot maqsad guruhda admin ekanligini tekshiring."
        )
        for admin_id in admins:
            try:
                await bot.send_message(chat_id=int(admin_id), text=error_msg)
            except Exception:
                pass


from aiohttp import web

async def handle_ping(request):
    return web.Response(text="🚕 Taxi Bot Active & Running 24/7!", content_type="text/html")

async def start_web_server():
    """Render.com va UptimeRobot uchun HTTP server (15-minutlik uyquni oldini olish uchun)"""
    try:
        app = web.Application()
        app.router.add_get("/", handle_ping)
        app.router.add_get("/health", handle_ping)
        port = int(os.getenv("PORT", 8080))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logging.info(f"🌐 HTTP Ping-server {port}-portda ishga tushdi!")
    except Exception as e:
        logging.error(f"HTTP serverni ishga tushirishda xatolik: {e}")

async def main():
    logging.info("Bot ishga tushdi...")
    # Render va UptimeRobot uchun HTTP serverni yoqamiz
    await start_web_server()
    retry_delay = 2
    while True:
        try:
            logging.info("Telegram polling boshlanmoqda...")
            await dp.start_polling(bot, drop_pending_updates=True, handle_signals=False)
            retry_delay = 2
        except Exception as e:
            logging.error(f"⚠️ Telegram ulanishda xatolik ({e}). {retry_delay} soniyadan keyin qayta ulanmoqda...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi!")

