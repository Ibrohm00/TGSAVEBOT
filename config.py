"""
Media Downloader Bot - Configuration
YouTube, Instagram, TikTok va boshqa platformalardan yuklab beruvchi bot
"""

import os
import logging
from dataclasses import dataclass
from typing import List
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Anti-Bot User Agent (Chrome on Windows 10)
REAL_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


@dataclass
class BotConfig:
    """Bot konfiguratsiyasi"""
    # API
    token: str = os.getenv("BOT_TOKEN", "")
    admin_ids: List[int] = None
    # MongoDB
    mongo_uri: str = os.getenv("MONGO_URI", "mongodb+srv://ibrohm135:mansur5754@cluster0.intw8qq.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
    db_name: str = "media_downloader_bot"
    
    # Limitlar (Olib tashlandi / Kengaytirildi)
    max_video_size_mb: int = 2000    # 2GB (Telegram Local Bot API uchun)
    max_audio_size_mb: int = 2000
    max_duration_seconds: int = 14400 # 4 soat
    
    # Timeouts
    download_timeout: int = 600       # 10 daqiqa (katta fayllar uchun)
    request_timeout: int = 120
    
    # Sifat - MAKSIMAL
    default_video_quality: str = "1080p"  # Eng yuqori
    default_audio_quality: str = "320k"   # Eng yuqori
    
    def __post_init__(self):
        if self.admin_ids is None:
            admin_str = os.getenv("ADMIN_IDS", "")
            self.admin_ids = [int(x) for x in admin_str.split(",") if x.strip().isdigit()]
        
        if not self.token:
            raise ValueError("❌ BOT_TOKEN topilmadi! .env faylini tekshiring.")
        
        logger.info("✅ Config yuklandi")


# Qo'llab-quvvatlanadigan platformalar
SUPPORTED_PLATFORMS = {
    'youtube': {
        'name': 'YouTube',
        'emoji': '🎬',
        'patterns': ['youtube.com', 'youtu.be', 'youtube.com/shorts'],
        'supports': ['video', 'audio', 'thumbnail']
    },
    'instagram': {
        'name': 'Instagram',
        'emoji': '📸',
        'patterns': ['instagram.com/p/', 'instagram.com/reel/', 'instagram.com/stories/'],
        'supports': ['video', 'image']
    },
    'tiktok': {
        'name': 'TikTok',
        'emoji': '🎵',
        'patterns': ['tiktok.com', 'vm.tiktok.com'],
        'supports': ['video', 'audio']
    },
    'twitter': {
        'name': 'Twitter/X',
        'emoji': '🐦',
        'patterns': ['twitter.com', 'x.com'],
        'supports': ['video', 'image']
    },
    'facebook': {
        'name': 'Facebook',
        'emoji': '📘',
        'patterns': ['facebook.com', 'fb.watch'],
        'supports': ['video']
    },
    'pinterest': {
        'name': 'Pinterest',
        'emoji': '📌',
        'patterns': ['pinterest.com', 'pin.it'],
        'supports': ['image']
    },
    'spotify': {
        'name': 'Spotify',
        'emoji': '🎧',
        'patterns': ['open.spotify.com/track', 'spotify.com/track'],
        'supports': ['audio']
    },
    'soundcloud': {
        'name': 'SoundCloud',
        'emoji': '🔊',
        'patterns': ['soundcloud.com'],
        'supports': ['audio']
    },
    'vk': {
        'name': 'VK',
        'emoji': '📱',
        'patterns': ['vk.com/video', 'vk.com/clip', 'vk.com/music'],
        'supports': ['video', 'audio']
    },
    'likee': {
        'name': 'Likee',
        'emoji': '🎭',
        'patterns': ['likee.video', 'l.likee.video', 'likee.com'],
        'supports': ['video']
    },
    'dailymotion': {
        'name': 'Dailymotion',
        'emoji': '📺',
        'patterns': ['dailymotion.com', 'dai.ly'],
        'supports': ['video']
    },
    'vimeo': {
        'name': 'Vimeo',
        'emoji': '🎥',
        'patterns': ['vimeo.com'],
        'supports': ['video']
    },
    'reddit': {
        'name': 'Reddit',
        'emoji': '🔴',
        'patterns': ['reddit.com', 'redd.it', 'v.redd.it'],
        'supports': ['video', 'image']
    },
    'tumblr': {
        'name': 'Tumblr',
        'emoji': '📝',
        'patterns': ['tumblr.com'],
        'supports': ['video', 'image']
    },
    'twitch': {
        'name': 'Twitch',
        'emoji': '💜',
        'patterns': ['twitch.tv/clip', 'clips.twitch.tv'],
        'supports': ['video']
    },
    'okru': {
        'name': 'OK.ru',
        'emoji': '🟠',
        'patterns': ['ok.ru', 'odnoklassniki.ru'],
        'supports': ['video']
    },
    'rutube': {
        'name': 'Rutube',
        'emoji': '🔵',
        'patterns': ['rutube.ru'],
        'supports': ['video']
    }
}




# Config instance
config = BotConfig()
