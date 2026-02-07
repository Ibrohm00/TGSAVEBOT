import aiosqlite
import logging
import os
from datetime import datetime
from typing import Optional, List, Tuple

from config import config

logger = logging.getLogger(__name__)

DB_PATH = config.db_path

async def init_db():
    """Ma'lumotlar bazasini yaratish"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Users table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        
        # Settings table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY,
                video_quality TEXT DEFAULT '720p',
                audio_quality TEXT DEFAULT '128k',
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        
        await db.commit()
        logger.info("Database initialized")

async def add_user(user_id: int, username: str = None, full_name: str = None):
    """Yangi foydalanuvchi qo'shish"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
        """, (user_id, username, full_name))
        
        # Update info if exists
        await db.execute("""
            UPDATE users 
            SET username = ?, full_name = ?, is_active = 1
            WHERE user_id = ?
        """, (username, full_name, user_id))
        
        # Create default settings
        await db.execute("""
            INSERT OR IGNORE INTO settings (user_id)
            VALUES (?)
        """, (user_id,))
        
        await db.commit()

async def get_settings(user_id: int) -> dict:
    """Foydalanuvchi sozlamalarini olish"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT video_quality, audio_quality FROM settings WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {'video_quality': row[0], 'audio_quality': row[1]}
            return {'video_quality': '720p', 'audio_quality': '128k'}

async def update_settings(user_id: int, key: str, value: str):
    """Sozlamalarni yangilash"""
    valid_keys = ['video_quality', 'audio_quality']
    if key not in valid_keys:
        return
        
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE settings SET {key} = ? WHERE user_id = ?", (value, user_id))
        await db.commit()

async def get_users_count() -> int:
    """Foydalanuvchilar sonini olish"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            return (await cursor.fetchone())[0]

async def get_all_users() -> List[int]:
    """Barcha foydalanuvchilar ID sini olish"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE is_active = 1") as cursor:
            return [row[0] for row in await cursor.fetchall()]

async def set_user_active(user_id: int, is_active: bool):
    """Foydalanuvchi statusini o'zgartirish"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_active = ? WHERE user_id = ?", (is_active, user_id))
        await db.commit()

async def get_new_users_today() -> int:
    """Bugungi yangi foydalanuvchilar soni"""
    today = datetime.now().date()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE date(joined_date) = date(?)", (today,)) as cursor:
            return (await cursor.fetchone())[0]

async def get_active_users_count() -> int:
    """Aktiv foydalanuvchilar soni"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_active = 1") as cursor:
            return (await cursor.fetchone())[0]

async def get_last_users(limit: int = 10) -> List[Tuple[int, str, str]]:
    """Oxirgi qo'shilgan foydalanuvchilar"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, username, full_name, joined_date FROM users ORDER BY joined_date DESC LIMIT ?", 
            (limit,)
        ) as cursor:
            return await cursor.fetchall()
