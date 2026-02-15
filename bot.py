"""
📥 Media Downloader Bot v3.0 (Optimized)
YouTube, Instagram, TikTok va boshqa platformalardan video/audio/rasm yuklab beruvchi bot
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Optional
from collections import defaultdict

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery, 
    InlineKeyboardButton, InlineKeyboardMarkup,
    BufferedInputFile, FSInputFile
)
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

class BroadcastState(StatesGroup):
    waiting_for_message = State()
    confirm_send = State()

from config import config, SUPPORTED_PLATFORMS
from downloader import (
    detect_platform, extract_url, download_media, DownloadResult
)
from database import (
    init_db, add_user, get_settings as db_get_settings, update_settings, 
    set_user_active, get_users_count, get_active_users_count, 
    get_new_users_today, get_all_users, get_last_users,
    add_cached_file, get_cached_file
)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- DNS MONKEY PATCH START ---
# Hugging Face Spaces da DNS muammosini hal qilish uchun
try:
    import dns.resolver
    import socket
    
    logger.info("🛠️ DNS Resolver Monkey Patching...")
    
    original_getaddrinfo = socket.getaddrinfo
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ['8.8.8.8', '1.1.1.1']
    # TCP ni yoqish (UDP bloklangan bo'lishi mumkin)
    resolver.use_tcp = True
    
    def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        # Faqat domen nomlarini resolve qilish (IP larni emas)
        if host is None:
             return original_getaddrinfo(host, port, family, type, proto, flags)

        try:
            # Agar host allaqachon IP bo'lsa, original funksiyani ishlatish
            socket.inet_aton(host)
            return original_getaddrinfo(host, port, family, type, proto, flags)
        except OSError:
            pass # IP emas (yoki IPv6)
            
        try:
            # IPv4 ni afzal ko'rish (A record)
            answers = resolver.resolve(host, 'A')
            ip = answers[0].to_text()
            # Asl manzilni IP bilan almashtirib chaqirish
            return original_getaddrinfo(ip, port, family, type, proto, flags)
        except Exception:
            # Fallback
            return original_getaddrinfo(host, port, family, type, proto, flags)
            
    socket.getaddrinfo = custom_getaddrinfo
    logger.info("✅ socket.getaddrinfo patched with Google DNS (TCP enabled)!")
    
except ImportError:
    logger.warning("⚠️ dnspython not found! DNS patching skipped.")
except Exception as e:
    logger.error(f"❌ DNS Patching error: {e}")
# --- DNS MONKEY PATCH END ---


# Bot va Router
# Bot initialization moved to main() to fix Event Loop error


# --- IPv4 Session (Singleton) ---
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import TCPConnector, ClientSession as AioHttpClientSession
from aiohttp.resolver import AsyncResolver

class IPv4Session(AiohttpSession):
    _singleton_session: Optional[AioHttpClientSession] = None

    async def create_session(self) -> AioHttpClientSession:
        if self._singleton_session is None or self._singleton_session.closed:
            logger.info("🔌 IPv4Session: Creating Singleton ClientSession (AsyncResolver + Google DNS)...")
            
            # Explicit Google DNS resolver for aiohttp
            resolver = AsyncResolver(nameservers=["8.8.8.8", "1.1.1.1"])
            
            connector = TCPConnector(
                family=socket.AF_INET,
                ssl=True,
                resolver=resolver,
                limit=100,
                ttl_dns_cache=300
            )
            self._singleton_session = AioHttpClientSession(connector=connector, json_serialize=self.json_dumps)
        else:
            logger.info("🔌 IPv4Session: Reusing Singleton ClientSession")

        return self._singleton_session

    async def close(self):
        if self._singleton_session and not self._singleton_session.closed:
            await self._singleton_session.close()
        await super().close()

dp = Dispatcher()
router = Router()
dp.include_router(router)

# User settings cache (Transient state + cached settings)
user_settings: Dict[int, dict] = {}

# Rate limiting
user_rate_limit: Dict[int, float] = defaultdict(float)
RATE_LIMIT_SECONDS = 1  # Har 1 sekundda 1 ta so'rov

# Concurrency Limiting (High Load Strategy)
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(100)


class DownloadState(StatesGroup):
    """Yuklash jarayoni holatlari"""
    waiting_for_choice = State()


async def system_startup_check():
    """Tizimni ishga tushirishdan oldin tekshirish"""
    logger.info("🛠️ System Startup Checks...")
    
    # 1. Config
    if not config.token:
        logger.error("❌ BOT_TOKEN is missing!")
        return False
    if not config.admin_ids:
        logger.warning("⚠️ No ADMIN_IDS configured!")
    
    # 2. Database
    try:
        from database import client
        await client.admin.command('ping')
        logger.info("✅ Database connection OK")
    except Exception as e:
        logger.error(f"❌ Database connection FAILED: {e}")
        return False
        
    return True


def generate_caption(result: DownloadResult, name: str, emoji: str) -> str:
    """Caption yaratish yordamchisi"""
    title = (result.title[:45] + "...") if result.title and len(result.title) > 45 else (result.title or name)
    caption = f"{emoji} *{escape_md(title)}*"
    
    if result.duration:
        mins = result.duration // 60
        secs = result.duration % 60
        caption += f"\n⏱ {mins}\\:{secs:02d}"
    
    caption += f"\n📦 {escape_md(f'{result.size_mb:.1f}')}MB"
    caption += f"\n\n🤖 @tguzsavebot"
    return caption


# ============== Utility Functions ==============

async def get_user_settings(user_id: int) -> dict:
    """Foydalanuvchi sozlamalarini olish (Faqat preferences)"""
    # Default settings
    settings = {
        'video_quality': config.default_video_quality,
        'audio_quality': config.default_audio_quality,
        'language': 'uz'
    }
    
    # DB dan olish
    user_data = await settings_col.find_one({"user_id": user_id})
    if user_data:
        settings.update(user_data)
        
    # Language ni alohida tekshirish (chunki u users collectionda ham bor)
    lang = await get_user_language(user_id)
    settings['language'] = lang
    
    return settings


def format_size(size_bytes: int) -> str:
    """Fayl hajmini chiroyli formatlash"""
    if not size_bytes:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(0)
    import math
    if size_bytes > 0:
        i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def escape_md(text: str) -> str:
    """MarkdownV2 uchun escape (optimized)"""
    if not text:
        return ""
    
    # Regex bilan tezroq
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


def main_keyboard():
    """Asosiy klaviatura"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="settings"),
            InlineKeyboardButton(text="❓ Yordam", callback_data="help")
        ]
    ])


def download_keyboard(url: str, platform: str, t):
    """Yuklash variantlari (to'liq)"""
    buttons = []
    
    platform_info = SUPPORTED_PLATFORMS.get(platform, {})
    supports = platform_info.get('supports', ['video'])
    
    # Video
    if 'video' in supports:
        buttons.append([InlineKeyboardButton(text=t("btn_video"), callback_data="dl:video")])
    
    # TikTok uchun no-watermark
    if platform == 'tiktok':
        buttons.append([InlineKeyboardButton(text=t("btn_video_nowm"), callback_data="dl:nowm")])
    
    # Audio (YouTube, TikTok, SoundCloud, VK, Spotify)
    if 'audio' in supports:
        buttons.append([InlineKeyboardButton(text=t("btn_audio"), callback_data="dl:audio")])
    
    buttons.append([InlineKeyboardButton(text=t("btn_cancel"), callback_data="cancel")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def quality_keyboard(t):
    """Sifat tanlash"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="360p", callback_data="q:360p"),
            InlineKeyboardButton(text="480p", callback_data="q:480p"),
        ],
        [
            InlineKeyboardButton(text="720p ✓", callback_data="q:720p"),
            InlineKeyboardButton(text="1080p", callback_data="q:1080p"),
        ],
        [InlineKeyboardButton(text=t("btn_back"), callback_data="back")]
    ])


def admin_keyboard():
    """Admin panel klaviaturasi"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="admin:stats"),
            InlineKeyboardButton(text="📢 Reklama", callback_data="admin:broadcast")
        ],
        [
            InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin:users"),
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin:refresh")
        ],
        [
            InlineKeyboardButton(text="📝 Reklama Matni", callback_data="admin:promo_text"),
            InlineKeyboardButton(text="🔒 Kanal", callback_data="admin:channels")
        ],
        [InlineKeyboardButton(text="❌ Yopish", callback_data="delete_msg")]
    ])


def admin_back_keyboard():
    """Admin panelga qaytish"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin:back")]
    ])


def broadcast_confirm_keyboard():
    """Broadcast tasdiqlash"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yuborish", callback_data="broadcast:send"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="broadcast:cancel")
        ]
    ])


# ============== Safe Message Operations ==============

async def safe_edit(msg: Message, text: str, **kwargs) -> bool:
    """Xabarni xavfsiz tahrirlash (retry bilan)"""
    for attempt in range(3):
        try:
            await msg.edit_text(text, **kwargs)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                logger.debug(f"Edit error: {e}")
            return False
        except Exception as e:
            logger.debug(f"Edit error attempt {attempt}: {e}")
            if attempt < 2:
                await asyncio.sleep(0.5)
    return False


async def safe_delete(msg: Message) -> bool:
    """Xabarni xavfsiz o'chirish"""
    try:
        await msg.delete()
        return True
    except Exception:
        return False


async def safe_send_media(message: Message, media_type: str, file: Any, **kwargs):
    """Media yuborish (xavfsiz va retry bilan)"""
    method = {
        'video': message.answer_video,
        'audio': message.answer_audio,
        'photo': message.answer_photo,
        'document': message.answer_document,
    }.get(media_type)
    
    if not method:
        return None

    for attempt in range(3):
        try:
            return await method(file, **kwargs)
        except TelegramRetryAfter as e:
            logger.warning(f"FloodWait: Sleeping {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
        except TelegramNetworkError:
            logger.warning(f"Network error, retrying... ({attempt+1}/3)")
            await asyncio.sleep(1)
        except TelegramEntityTooLarge:
            await message.answer("❌ Fayl hajmi Telegram limitidan katta (50MB/2GB).", parse_mode="Markdown")
            return None
        except Exception as e:
            logger.error(f"Send media error: {e}")
            if attempt < 2:
                await asyncio.sleep(0.5)
            else:
                await message.answer("❌ Media yuborishda xatolik yuz berdi.", parse_mode="Markdown")
    return None


# ============== Commands ==============

@router.message(Command("start"))
async def cmd_start(message: Message, t):
    """Start buyrug'i"""
    # Foydalanuvchini bazaga qo'shish
    await add_user(
        message.from_user.id, 
        message.from_user.username, 
        message.from_user.full_name
    )
    
    try:
        logo = FSInputFile("logo.png")
        await message.answer_photo(
            logo,
            caption=t("start_welcome", name=escape_md(message.from_user.full_name)),
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except:
        # Rasm topilmasa oddiy xabar
        await message.answer(
            t("start_welcome", name=escape_md(message.from_user.full_name)),
            parse_mode=ParseMode.MARKDOWN_V2
        )

@router.message(Command("lang"))
async def cmd_lang(message: Message, t):
    """Tilni o'zgartirish"""
    await message.answer(
        t("select_language"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang:uz"),
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="🇺🇸 English", callback_data="lang:en")
            ],
            [InlineKeyboardButton(text="❌", callback_data="delete_msg")]
        ])
    )

@router.callback_query(F.data.startswith("lang:"))
async def handle_lang_callback(callback: CallbackQuery):
    """Tilni tanlash"""
    lang_code = callback.data.split(":")[1]
    from database import set_user_language
    await set_user_language(callback.from_user.id, lang_code)
    
    # Manually load t for new language
    from i18n_middleware import t as get_t
    new_t = lambda key, **kwargs: get_t(key, lang_code, **kwargs)
    
    await callback.answer(new_t("language_selected"))
    await safe_delete(callback.message)
    
    try:
        logo = FSInputFile("logo.png")
        await callback.message.answer_photo(
            logo,
            caption=new_t("start_welcome", name=escape_md(callback.from_user.full_name)),
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except:
        await callback.message.answer(
            new_t("start_welcome", name=escape_md(callback.from_user.full_name)),
            parse_mode=ParseMode.MARKDOWN_V2
        )

@router.message(Command("help"))
async def cmd_help(message: Message, t):
    """Yordam"""
    await message.answer(
        t("help"),
        parse_mode=ParseMode.MARKDOWN_V2
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, t):
    """Sozlamalar"""
    settings = await get_user_settings(message.from_user.id)
    text = t("settings") + "\n\n" + \
           f"📹 Video: {settings['video_quality']}\n" + \
           f"🎵 Audio: {settings['audio_quality']}"

    await message.answer(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=quality_keyboard(t)
    )


# ============== Admin Commands ==============

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Admin panel"""
    if message.from_user.id not in config.admin_ids:
        return
    
    total = await get_users_count()
    active = await get_active_users_count()
    new_today = await get_new_users_today()
    
    text = (
        "👑 *Admin Panel*\n\n"
        f"👤 Jami foydalanuvchilar: {total}\n"
        f"✅ Aktiv foydalanuvchilar: {active}\n"
        f"🆕 Bugungi yangi: {new_today}\n\n"
        "Quyidagi bo'limlardan birini tanlang:"
    )
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_keyboard())


@router.callback_query(F.data == "delete_msg")
async def delete_msg(callback: CallbackQuery):
    """Xabarni o'chirish (barcha foydalanuvchilar uchun)"""
    await callback.answer()
    await safe_delete(callback.message)


@router.callback_query(F.data.startswith("admin:"))
async def handle_admin_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.admin_ids:
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return

    action = callback.data.split(":")[1]
    
    if action == "stats" or action == "refresh":
        total = await get_users_count()
        active = await get_active_users_count()
        new_today = await get_new_users_today()
        
        text = (
            "👑 *Admin Panel*\n\n"
            f"👤 Jami foydalanuvchilar: {total}\n"
            f"✅ Aktiv foydalanuvchilar: {active}\n"
            f"🆕 Bugungi yangi: {new_today}\n\n"
            f"📅 Yangilandi: {datetime.now().strftime('%H:%M:%S')}"
        )
        await safe_edit(callback.message, text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_keyboard())
    
    elif action == "broadcast":
        await safe_edit(
            callback.message,
            "📢 *Reklama yuborish*\n\n"
            "Xabar matnini, rasm yoki videoni yuboring:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_back_keyboard()
        )
        await state.set_state(BroadcastState.waiting_for_message)
        # await callback.answer() # safe_edit da answer shart emas agar message o'zgarsa
    
    elif action == "users":

        users = await get_last_users(10)
        text = "👥 *Oxirgi 10 ta foydalanuvchi:*\n\n"
        
        for u in users:
            uid, uname, fname, date = u
            user_link = f"@{uname}" if uname else f"[{escape_md(fname)}](tg://user?id={uid})"
            joined = str(date).split('.')[0]
            text += f"👤 {user_link} \\(`{uid}`\\)\n📅 {escape_md(joined)}\n\n"
            
        await safe_edit(callback.message, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=admin_back_keyboard())
    
    elif action == "channels":
        await callback.answer("Majburiy obuna funksiyasi hali o'chirilgan", show_alert=True)
    
    elif action == "promo_text":
        promo = (
            "🚀 *TG SAVE BOT* \\- Eng tez va qulay media yuklovchi\\!\n\n"
            "✨ *Qulayliklar:*\n"
            "├ 📥 16\\+ platformadan yuklash\n"
            "├ 🎬 Video, 🎵 Audio, 🖼 Rasm\n"
            "├ ⚡️ Tez va sifatli\n"
            "├ 🆓 Butunlay bepul\n"
            "└ 🌍 3 tilda ishlaydi\n\n"
            "📲 *Qo'llab\\-quvvatlanadi:*\n"
            "Instagram \\| TikTok \\| Twitter \\| Pinterest\n"
            "SoundCloud \\| Spotify \\| VK \\| Likee\n"
            "Dailymotion \\| Vimeo \\| Reddit \\| Twitch\n\n"
            "👇 *Hoziroq sinab ko'ring:*\n"
            "🤖 @tguzsavebot\n\n"
            "\\#mediadownloader \\#tgsavebot \\#yuklovchi"
        )
        await safe_edit(
            callback.message,
            f"📝 *Reklama Matni \\(nusxa olish uchun\\):*\n\n{promo}",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=admin_back_keyboard()
        )
    
    elif action == "back":
        await state.clear() # FSM holatini tozalash
        total = await get_users_count()
        active = await get_active_users_count()
        new_today = await get_new_users_today()
        
        text = (
            "👑 *Admin Panel*\n\n"
            f"👤 Jami foydalanuvchilar: {total}\n"
            f"✅ Aktiv foydalanuvchilar: {active}\n"
            f"🆕 Bugungi yangi: {new_today}\n\n"
            "Quyidagi bo'limlardan birini tanlang:"
        )
        await safe_edit(callback.message, text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_keyboard())


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Statistika (Admin)"""
    if message.from_user.id not in config.admin_ids:
        return
    
    total = await get_users_count()
    active = await get_active_users_count()
    new_today = await get_new_users_today()
    
    text = (
        "📊 *Bot Statistikasi*\n\n"
        f"👤 Jami foydalanuvchilar: {total}\n"
        f"✅ Aktiv foydalanuvchilar: {active}\n"
        f"🆕 Bugungi yangi: {new_today}\n"
        f"📅 Sana: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    """Xabar tarqatish (Admin)"""
    if message.from_user.id not in config.admin_ids:
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Xabar matnini kiriting!\nNamuna: `/broadcast Assalomu alaykum`", parse_mode=ParseMode.MARKDOWN)
        return
    
    text = parts[1]
    users = await get_all_users(active_only=True)
    
    msg = await message.answer(f"🚀 Xabar yuborish boshlandi ({len(users)} ta)...")
    
    sent = 0
    blocked = 0
    
    for user_id in users:
        try:
            await bot.send_message(user_id, text, parse_mode=ParseMode.MARKDOWN_V2)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            blocked += 1
            await set_user_active(user_id, False)
        await asyncio.sleep(0.035)  # Telegram flood limit: ~30 msg/sec
    
    await msg.edit_text(
        f"✅ *Xabar yuborildi*\n\n"
        f"📤 Yuborildi: {sent}\n"
        f"🚫 Bloklangan: {blocked}",
        parse_mode=ParseMode.MARKDOWN
    )


@router.message(BroadcastState.waiting_for_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    """Broadcast xabarini qabul qilish"""
    # Xabarni vaqtinchalik saqlash (bu yerda oddiygina qayta yuborish logikasi bo'ladi)
    # Ammo hozircha message_id va chat_id ni saqlaymiz
    await state.update_data(message_id=message.message_id, chat_id=message.chat.id)
    
    await message.reply(
        "✅ Xabar qabul qilindi. Yuborishni tasdiqlaysizmi?",
        reply_markup=broadcast_confirm_keyboard()
    )
    await state.set_state(BroadcastState.confirm_send)


@router.callback_query(BroadcastState.confirm_send, F.data == "broadcast:send")
async def process_broadcast_send(callback: CallbackQuery, state: FSMContext):
    """Broadcastni yuborish"""
    if callback.from_user.id not in config.admin_ids:
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text("🚀 Xabar yuborilmoqda...")
    
    data = await state.get_data()
    message_id = data['message_id']
    chat_id = data['chat_id']
    
    users = await get_all_users(active_only=True)
    sent = 0
    blocked = 0
    
    for user_id in users:
        try:
            # Copy message - rasm/video/matn hammasini qo'llab-quvvatlaydi
            await bot.copy_message(chat_id=user_id, from_chat_id=chat_id, message_id=message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            blocked += 1
            await set_user_active(user_id, False)
        await asyncio.sleep(0.035)  # Telegram flood limit: ~30 msg/sec
    
    await callback.message.edit_text(
        f"✅ *Xabar yuborildi*\n\n"
        f"📤 Yuborildi: {sent}\n"
        f"🚫 Bloklangan: {blocked}",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.clear()


@router.callback_query(BroadcastState.confirm_send, F.data == "broadcast:cancel")
async def process_broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    """Broadcastni bekor qilish"""
    if callback.from_user.id not in config.admin_ids:
         await callback.answer("❌ Siz admin emassiz!", show_alert=True)
         return

    await state.clear()
    await callback.message.edit_text("❌ Xabar yuborish bekor qilindi.")
    
    # Admin panelga qaytish
    total = await get_users_count()
    active = await get_active_users_count()
    new_today = await get_new_users_today()
    
    text = (
        "👑 *Admin Panel*\n\n"
        f"👤 Jami foydalanuvchilar: {total}\n"
        f"✅ Aktiv foydalanuvchilar: {active}\n"
        f"🆕 Bugungi yangi: {new_today}\n\n"
        "Quyidagi bo'limlardan birini tanlang:"
    )
    await safe_edit(callback.message, text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_keyboard())


# ============== Link Handler ==============

@router.message(F.text)
async def handle_message(message: Message, state: FSMContext, t):
    """Xabarlarni qayta ishlash (optimized + FSM)"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Aktiv statusini yangilash (bazaga qo'shish emas — /start da qilinadi)
    await set_user_active(user_id, True)
    
    # URL ni topish
    url = extract_url(text)
    
    if not url:
        await message.answer(
            t("error_link"),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    # Platformani aniqlash
    platform = detect_platform(url)
    
    if not platform:
        await message.answer(
            t("error_generic"), # Yoki error_unsupported agar bo'lsa
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    # Platform info
    platform_info = SUPPORTED_PLATFORMS[platform]
    emoji = platform_info['emoji']
    name = platform_info['name']
    supports = platform_info.get('supports', ['video'])
    
    # URL va platformani saqlash (FSM)
    await state.update_data(url=url, platform=platform)
    await state.set_state(DownloadState.waiting_for_choice)
    
    # Variant kerak bo'lgan platformalar
    needs_choice = (
        platform in ['youtube', 'tiktok', 'vk', 'soundcloud', 'spotify'] or
        len(supports) > 1
    )
    
    if needs_choice:
        await message.answer(
            t("what_to_download", emoji=emoji, name=escape_md(name)),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=download_keyboard(url, platform, t)
        )
        return
    
    # To'g'ridan-to'g'ri yuklash
    media_type = supports[0] if supports else 'video'
    
    # Katta fayllarni tekshirish (HEAD request)
    # create_task da exception handling qiyin, shuning uchun process_download ichida hal qilinadi.
    asyncio.create_task(process_download(message, url, platform, media_type, t=t))


async def process_download(
    message: Message, 
    url: str, 
    platform: str, 
    media_type: str, 
    t,
    no_watermark: bool = False
):
    """
    Yuklash jarayoni (maksimal optimizatsiya)
    - Progress bar
    - Retry logic
    - Better error handling
    """
    platform_info = SUPPORTED_PLATFORMS.get(platform, {})
    emoji = platform_info.get('emoji', '📥')
    name = platform_info.get('name', platform)
    
    # Loading xabar
    loading_msg = await message.answer(
        f"{emoji} *{escape_md(name)}*\n\n{t('preparing')}",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    # 1. Keshni tekshirish (File ID Caching)
    cached_file = await get_cached_file(url)
    if cached_file:
        try:
            file_id = cached_file.get('file_id')
            media_type_cached = cached_file.get('media_type')
            
            await safe_edit(
                loading_msg,
                f"{emoji} *{escape_md(name)}*\n\n✅ Fayl topildi, yuborilmoqda...",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
            # Send cached file
            if media_type_cached == 'audio':
                await message.answer_audio(file_id, caption=f"{emoji} {escape_md(name)} via @tguzsavebot")
            elif media_type_cached == 'image':
                await message.answer_photo(file_id, caption=f"{emoji} {escape_md(name)} via @tguzsavebot")
            else: # video
                await message.answer_video(file_id, caption=f"{emoji} {escape_md(name)} via @tguzsavebot")
            
            await safe_delete(loading_msg)
            return
        except Exception as e:
            logger.warning(f"Cache hit but failed to send {url}: {e}")
            # Agar kesh ishlamasa, qayta yuklashga o'tadi
    
    # 2. Concurrency limiting (Navbat)
    if DOWNLOAD_SEMAPHORE.locked():
        await safe_edit(
            loading_msg,
            f"{emoji} *{escape_md(name)}*\n\n⏳ Server band, navbatingizni kuting...",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    
    async with DOWNLOAD_SEMAPHORE:
        # Progress callback
        progress_state = {'last_update': 0, 'step': 0}
        
        async def update_progress(status: str):
            now = time.time()
            if now - progress_state['last_update'] > 2:
                progress_state['step'] += 1
                dots = "." * (progress_state['step'] % 4)
                try:
                    await safe_edit(
                        loading_msg,
                        f"{emoji} *{escape_md(name)}*\n\n{escape_md(status)}{dots}",
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    progress_state['last_update'] = now
                except:
                    pass
        
        result = None
        
        try:
            # Yuklash boshlandi
            await safe_edit(
                loading_msg,
                f"{emoji} *{escape_md(name)}*\n\n{t('downloading')}",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
            # Yuklash (retry bilan)
            for attempt in range(2):
                result = await download_media(url, media_type, no_watermark, update_progress)
                
                if result.success:
                    break
                elif attempt < 1:
                    await asyncio.sleep(1)
                    logger.info(f"Retry download: {platform}")
            
            if not result.success:
                error_text = result.error or t("error_unknown")
                await safe_edit(
                    loading_msg,
                    f"❌ *Xatolik*\n\n{escape_md(error_text)}",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                return
            
            # Uploading
            await safe_edit(
                loading_msg,
                f"{emoji} *{escape_md(name)}*\n\n{t('uploading')}",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
            # Caption yaratish
            # Caption yaratish
            caption = generate_caption(result, name, emoji)
            
            # Media yuborish (Safe Wrapper orqali)
            input_file = FSInputFile(result.file_path)
            thumb_file = BufferedInputFile(result.thumbnail, filename="thumb.jpg") if result.thumbnail else None
            
            sent_msg = None
            if result.media_type == 'audio':
                sent_msg = await safe_send_media(
                    message, 
                    'audio', 
                    input_file,
                    title=result.title[:1000],
                    duration=result.duration,
                    thumbnail=thumb_file,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            elif result.media_type == 'image':
                sent_msg = await safe_send_media(
                    message, 
                    'photo', 
                    input_file,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                sent_msg = await safe_send_media(
                    message, 
                    'video', 
                    input_file,
                    caption=caption,
                    duration=result.duration,
                    width=1920,
                    height=1080,
                    thumbnail=thumb_file,
                    supports_streaming=True,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                
            # 3. Keshga saqlash (File ID Caching)
            if sent_msg:
                file_id = None
                if result.media_type == 'audio' and sent_msg.audio:
                    file_id = sent_msg.audio.file_id
                elif result.media_type == 'image' and sent_msg.photo:
                    file_id = sent_msg.photo[-1].file_id
                elif result.media_type == 'video' and sent_msg.video:
                    file_id = sent_msg.video.file_id
                
                if file_id:
                    await add_cached_file(url, file_id, result.media_type)
                    logger.info(f"Cached file_id for {url}")
            
            # Loading xabarini o'chirish
            await safe_delete(loading_msg)
            
        except Exception as e:
            logger.error(f"Download error: {e}", exc_info=True)
            await safe_edit(
                loading_msg,
                f"❌ *Xatolik*\n\n{escape_md(str(e)[:80])}",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        
        finally:
            # Cleanup (muhim!)
            if result:
                result.cleanup()


# ============== Callbacks ==============

@router.callback_query(F.data.startswith("dl:"))
async def handle_download(callback: CallbackQuery, state: FSMContext, t):
    """Yuklash callback (optimized + FSM)"""
    await callback.answer()
    
    action = callback.data.split(":")[1] if ":" in callback.data else "video"
    
    # Saqlangan URL (FSM)
    data = await state.get_data()
    url = data.get('url')
    platform = data.get('platform', 'youtube')
    
    if not url:
        await safe_edit(
            callback.message,
            t("link_expired"),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    # Xabarni o'chirish
    await safe_delete(callback.message)
    
    # FSM tozalash
    await state.clear()
    
    # Media type va no_watermark
    no_watermark = (action == 'nowm')
    media_type = 'video' if action in ['video', 'nowm'] else 'audio'
    
    # Yuklash
    await process_download(callback.message, url, platform, media_type, t=t, no_watermark=no_watermark)


@router.callback_query(F.data.startswith("q:"))
async def handle_quality(callback: CallbackQuery, t):
    """Sifat tanlash"""
    quality = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    # DB va Cache yangilash
    await update_settings(user_id, 'video_quality', quality)
    settings = await get_user_settings(user_id)
    settings['video_quality'] = quality
    
    await callback.answer(f"✅ Sifat: {quality}")
    
    text = t("settings") + "\n\n" + \
           f"📹 Video: {settings['video_quality']}\n" + \
           f"🎵 Audio: {settings['audio_quality']}"
           
    await safe_edit(
        callback.message,
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=quality_keyboard(t)
    )


@router.callback_query(F.data == "settings")
async def handle_settings(callback: CallbackQuery, t):
    """Sozlamalar callback"""
    await callback.answer()
    settings = await get_user_settings(callback.from_user.id)
    text = t("settings") + "\n\n" + \
           f"📹 Video: {settings['video_quality']}\n" + \
           f"🎵 Audio: {settings['audio_quality']}"

    await safe_edit(
        callback.message,
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=quality_keyboard(t)
    )


@router.callback_query(F.data == "help")
async def handle_help(callback: CallbackQuery, t):
    """Yordam callback"""
    await callback.answer()
    await safe_edit(
        callback.message,
        t("help"),
        parse_mode=ParseMode.MARKDOWN_V2
    )


@router.callback_query(F.data.in_({"cancel", "back"}))
async def handle_cancel(callback: CallbackQuery):
    """Bekor qilish"""
    await callback.answer("❌ Bekor qilindi")
    
    # Pending URL tozalash
    settings = await get_user_settings(callback.from_user.id)
    settings['pending_url'] = None
    settings['pending_platform'] = None
    
    await safe_delete(callback.message)


# ============== Main ==============

# ============== Subscription Commands ==============

@router.callback_query(F.data == "check_subscription")
async def handle_check_subscription(callback: CallbackQuery):
    """Obunani tekshirish (Agar middleware dan o'tsa)"""
    await callback.answer("✅ Obuna tasdiqlandi! Botdan foydalanishingiz mumkin.", show_alert=True)
    await safe_delete(callback.message)

# ============== Channel Admin Commands ==============

@router.message(Command("add_channel"))
async def cmd_add_channel(message: Message):
    """Kanal qo'shish (Admin)"""
    if message.from_user.id not in config.admin_ids:
        return

    # Argumentlarni olish
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "⚠️ Kanal ID yoki username kiriting!\n"
            "Namuna: `/add_channel @kanal_username` yoki `-1001234567890`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    channel_input = parts[1]
    
    try:
        # Kanal ma'lumotlarini olish
        chat = await bot.get_chat(channel_input)
        
        # Bot admin ekanligini tekshirish
        member = await bot.get_chat_member(chat.id, bot.id)
        if member.status not in ("administrator", "creator"):
            await message.answer("❌ Bot ushbu kanalda admin emas!", parse_mode=ParseMode.MARKDOWN)
            return

        # Bazaga qo'shish
        from database import add_channel
        success = await add_channel(
            channel_id=chat.id,
            title=chat.title,
            username=chat.username,
            invite_link=chat.invite_link or f"https://t.me/{chat.username}"
        )
        
        if success:
            await message.answer(f"✅ Kanal qo'shildi:\n*{escape_md(chat.title)}*", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await message.answer("❌ Bazaga yozishda xatolik!", parse_mode=ParseMode.MARKDOWN)
            
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}", parse_mode=ParseMode.MARKDOWN)

async def send_channel_list(message: Message, edit_message: bool = False):
    """Kanallar ro'yxatini yuborish (yordamchi funksiya)"""
    from database import get_channels
    channels = await get_channels()
    
    text = "📋 *Ulagan kanallar:*\n\n"
    keyboard = []
    
    if not channels:
        text = "📂 Kanallar ro'yxati bo'sh."
    else:
        for ch in channels:
            text += f"📢 {escape_md(ch['title'])} (`{ch['channel_id']}`)\n"
            keyboard.append([InlineKeyboardButton(text=f"🗑 O'chirish: {ch['title']}", callback_data=f"del_ch:{ch['channel_id']}")])
        
    keyboard.append([InlineKeyboardButton(text="❌ Yopish", callback_data="delete_msg")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    if edit_message:
        await message.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=markup)
    else:
        await message.answer(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=markup)

@router.message(Command("channels"))
async def cmd_list_channels(message: Message):
    """Kanallar ro'yxati (Admin)"""
    if message.from_user.id not in config.admin_ids:
        return
    await send_channel_list(message)

@router.callback_query(F.data.startswith("del_ch:"))
async def handle_delete_channel(callback: CallbackQuery):
    """Kanalni o'chirish"""
    if callback.from_user.id not in config.admin_ids:
        return
        
    channel_id = int(callback.data.split(":")[1])
    from database import remove_channel
    
    if await remove_channel(channel_id):
        await callback.answer("✅ Kanal o'chirildi", show_alert=True)
        # Ro'yxatni yangilash
        await send_channel_list(callback.message, edit_message=True)
    else:
        await callback.answer("❌ Xatolik", show_alert=True)

# --- HEALTH CHECK SERVER ---
from aiohttp import web

async def handle_health_check(request):
    return web.Response(text="I am alive!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 7860)
    await site.start()
    logger.info("✅ Health check server started on port 7860")


async def main():
    if not await system_startup_check():
        logger.error("🛑 Startup checks failed! Exiting...")
        return

    await init_db()
    
    # Session creation (Singleton)
    # DNS Fix
    from aiohttp.resolver import AsyncResolver
    from aiohttp import TCPConnector
    resolver = AsyncResolver(nameservers=["8.8.8.8", "1.1.1.1"])
    connector = TCPConnector(resolver=resolver, family=2, ssl=False) # AF_INET=2

    session = AiohttpSession(connector=connector)
    global bot
    bot = Bot(token=config.token, session=session)
    
    # Middlewares
    from middlewares import SubscriptionMiddleware, ThrottlingMiddleware
    dp.update.middleware(ThrottlingMiddleware(limit=0.5))
    dp.update.middleware(SubscriptionMiddleware())
    dp.update.middleware(I18nMiddleware(locales_dir="locales", default_locale="uz"))
    
    # Web server start
    await start_web_server()

    # Commands setup
    await bot.set_my_commands([
        BotCommand(command="start", description="Boshlash"),
        BotCommand(command="settings", description="Sozlamalar"),
        BotCommand(command="lang", description="Tilni o'zgartirish"),
        BotCommand(command="help", description="Yordam"),
    ])
    
    logger.info("🚀 Bot ishga tushdi!")
    
    # Error Handler
    @dp.error()
    async def global_error_handler(event: ErrorEvent):
        logger.critical(f"Global error: {event.exception}", exc_info=True)

    # Start polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
