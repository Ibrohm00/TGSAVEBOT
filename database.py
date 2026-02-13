
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from motor.motor_asyncio import AsyncIOMotorClient

from config import config

# Logger setup
logger = logging.getLogger(__name__)

# MongoDB Client
client = AsyncIOMotorClient(config.mongo_uri)
db = client[config.db_name]
users_col = db['users']
settings_col = db['settings']

async def init_db():
    """Ma'lumotlar bazasini tekshirish (MongoDB da o'zi avtomatik)"""
    try:
        # Ping the database
        await client.admin.command('ping')
        logger.info("✅ MongoDB ga ulanish muvaffaqiyatli!")
        
        # Index yaratish (tez ishlashi uchun)
        await users_col.create_index("user_id", unique=True)
        await settings_col.create_index("user_id", unique=True)
        
    except Exception as e:
        logger.error(f"❌ MongoDB ga ulanishda xatolik: {e}")

async def add_user(user_id: int, username: str = None, full_name: str = None):
    """Yangi foydalanuvchi qo'shish yoki yangilash"""
    try:
        user_data = {
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "is_active": True,
            "last_active": datetime.now()
        }
        
        # User borligini tekshirish va yangilash
        existing_user = await users_col.find_one({"user_id": user_id})
        
        if existing_user:
            await users_col.update_one(
                {"user_id": user_id},
                {"$set": {
                    "username": username, 
                    "full_name": full_name, 
                    "is_active": True,
                    "last_active": datetime.now()
                }}
            )
        else:
            user_data["joined_date"] = datetime.now()
            user_data["language"] = "uz" # Default language
            await users_col.insert_one(user_data)
            
            # Default settings
            await settings_col.insert_one({
                "user_id": user_id,
                "video_quality": "720p",
                "audio_quality": "128k"
            })
            
    except Exception as e:
        logger.error(f"Error adding user {user_id}: {e}")

async def get_settings(user_id: int) -> Dict:
    """Foydalanuvchi sozlamalarini olish"""
    try:
        settings = await settings_col.find_one({"user_id": user_id})
        if settings:
            return settings
        
        # Agar yo'q bo'lsa default qaytarish
        return {"video_quality": "720p", "audio_quality": "128k"}
    except Exception as e:
        logger.error(f"Error getting settings for {user_id}: {e}")
        return {"video_quality": "720p", "audio_quality": "128k"}

async def update_settings(user_id: int, key: str, value: str):
    """Sozlamalarni yangilash"""
    try:
        await settings_col.update_one(
            {"user_id": user_id},
            {"$set": {key: value}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error updating settings for {user_id}: {e}")

async def get_users_count() -> int:
    """Jami foydalanuvchilar soni"""
    return await users_col.count_documents({})

async def get_active_users_count() -> int:
    """Aktiv foydalanuvchilar soni"""
    return await users_col.count_documents({"is_active": True})

async def get_new_users_today() -> int:
    """Bugungi yangi foydalanuvchilar"""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return await users_col.count_documents({"joined_date": {"$gte": today}})

async def get_all_users() -> List[int]:
    """Barcha user ID larini olish (broadcast uchun)"""
    cursor = users_col.find({}, {"user_id": 1})
    users = await cursor.to_list(length=None)
    return [user['user_id'] for user in users]

async def get_last_users(limit: int = 10) -> List[Tuple[int, str, str, str]]:
    """Oxirgi qo'shilgan foydalanuvchilar"""
    cursor = users_col.find().sort("joined_date", -1).limit(limit)
    users = await cursor.to_list(length=limit)
    
    result = []
    for user in users:
        result.append((
            user['user_id'],
            user.get('username', ''),
            user.get('full_name', 'Unknown'),
            user.get('joined_date', datetime.now())
        ))
    return result

async def set_user_active(user_id: int, is_active: bool):
    """User statusini o'zgartirish (bloklaganda)"""
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"is_active": is_active}}
    )

async def set_user_language(user_id: int, lang: str):
    """Foydalanuvchi tilini o'zgartirish"""
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"language": lang}},
        upsert=True
    )

async def get_user_language(user_id: int) -> str:
    """Foydalanuvchi tilini olish"""
    user = await users_col.find_one({"user_id": user_id})
    if user and "language" in user:
        return user["language"]
    return "uz" # Default

# ============== Channels (Sponsorship) ==============

channels_col = db['channels']

async def add_channel(channel_id: int, title: str, username: str, invite_link: str):
    """Kanal qo'shish (Majburiy obuna uchun)"""
    try:
        await channels_col.update_one(
            {"channel_id": channel_id},
            {"$set": {
                "channel_id": channel_id,
                "title": title,
                "username": username,
                "invite_link": invite_link,
                "added_date": datetime.now()
            }},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error adding channel {channel_id}: {e}")
        return False

async def remove_channel(channel_id: int):
    """Kanalni o'chirish"""
    try:
        await channels_col.delete_one({"channel_id": channel_id})
        return True
    except Exception as e:
        logger.error(f"Error removing channel {channel_id}: {e}")
        return False

async def get_channels() -> List[Dict]:
    """Barcha kanallarni olish"""
    try:
        cursor = channels_col.find({})
        channels = await cursor.to_list(length=None)
        return channels
    except Exception as e:
        logger.error(f"Error getting channels: {e}")
        return []


# ============== File ID Cache (High Load Strategy) ==============

downloads_col = db['downloads']

async def add_cached_file(url: str, file_id: str, media_type: str):
    """Fayl ID sini keshlab qo'yish"""
    try:
        await downloads_col.update_one(
            {"url": url},
            {"$set": {
                "file_id": file_id,
                "media_type": media_type,
                "timestamp": datetime.now()
            }},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error caching file {url}: {e}")

async def get_cached_file(url: str) -> Dict:
    """Keshlangan faylni olish"""
    try:
        data = await downloads_col.find_one({"url": url})
        if data:
            # 24 soatdan oshgan bo'lsa, eskirgan deb hisoblash mumkin (ixtiyoriy)
            # Lekin file_id lar odatda uzoq vaqt ishlaydi
            return data
        return None
    except Exception as e:
        logger.error(f"Error getting cached file {url}: {e}")
        return None
