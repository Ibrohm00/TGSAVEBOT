"""
Media Downloader - YouTube, Instagram, TikTok, Twitter yuklash
"""

import os
import re
import asyncio
import tempfile
import shutil
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp

from config import config, SUPPORTED_PLATFORMS, REAL_USER_AGENT

logger = logging.getLogger(__name__)

def get_connector():
    """Google va Cloudflare DNS bilan connector"""
    from aiohttp import TCPConnector, AsyncResolver
    import socket
    resolver = AsyncResolver(nameservers=["8.8.8.8", "1.1.1.1"])
    return TCPConnector(family=socket.AF_INET, ssl=True, resolver=resolver)


@dataclass
class DownloadResult:
    """Yuklash natijasi"""
    success: bool
    platform: str = ""
    media_type: str = ""  # video, audio, image
    file_path: str = ""
    temp_dir: str = ""
    title: str = ""
    duration: int = 0
    size_mb: float = 0
    thumbnail: bytes = None
    error: str = ""
    
    def cleanup(self):
        """Vaqtinchalik fayllarni tozalash"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except:
                pass


def detect_platform(url: str) -> Optional[str]:
    """URL dan platformani aniqlash"""
    url_lower = url.lower()
    
    for platform_id, platform_info in SUPPORTED_PLATFORMS.items():
        for pattern in platform_info['patterns']:
            if pattern in url_lower:
                return platform_id
    
    return None


def extract_url(text: str) -> Optional[str]:
    """Matndan URL ni ajratib olish"""
    # URL pattern
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    
    match = re.search(url_pattern, text)
    if match:
        return match.group(0)
    
    return None


async def download_youtube(url: str, media_type: str = "video") -> DownloadResult:
    """
    YouTube'dan video yoki audio yuklash (MAKSIMAL SIFAT)
    Bot detection bypass bilan
    """
    temp_dir = tempfile.mkdtemp()
    
    # YouTube bot detection ni chetlab o'tish uchun client kombinatsiyalari
    client_configs = [
        ['default', 'mweb'],      # Eng ishonchli
        ['tv_embedded'],           # TV client (kam tekshiriladi)
        ['web_creator', 'mweb'],   # Creator client
    ]
    
    for client_attempt, clients in enumerate(client_configs):
        try:
            import yt_dlp
            
            base_opts = {
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': config.download_timeout,
                'force_ipv4': True,
                'user_agent': REAL_USER_AGENT,
                'extractor_args': {
                    'youtube': {
                        'player_client': clients,
                    }
                },
                'http_headers': {
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                },
            }
            
            if media_type == "audio":
                output_path = os.path.join(temp_dir, "audio.mp3")
                ydl_opts = {
                    **base_opts,
                    'format': 'bestaudio/best',
                    'outtmpl': output_path.replace('.mp3', '.%(ext)s'),
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '320',
                    }],
                }
            else:
                output_path = os.path.join(temp_dir, "video.mp4")
                ydl_opts = {
                    **base_opts,
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
                    'outtmpl': output_path.replace('.mp4', '.%(ext)s'),
                    'merge_output_format': 'mp4',
                    'postprocessor_args': {
                        'ffmpeg': ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k']
                    },
                }
            
            # Info + Download bir vaqtda
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Video')
                duration = info.get('duration', 0)
                video_id = info.get('id', '')
            
            # Fayl topish
            actual_path = None
            for f in os.listdir(temp_dir):
                if f.endswith(('.mp4', '.mp3', '.m4a', '.webm')):
                    actual_path = os.path.join(temp_dir, f)
                    break
            
            if not actual_path or not os.path.exists(actual_path):
                if client_attempt < len(client_configs) - 1:
                    logger.warning(f"YouTube: File not found with clients {clients}, trying next...")
                    continue
                return DownloadResult(
                    success=False,
                    platform='youtube',
                    temp_dir=temp_dir,
                    error="Fayl topilmadi"
                )
            
            file_size = os.path.getsize(actual_path) / (1024 * 1024)
            
            # Thumbnail
            thumbnail = None
            try:
                thumb_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
                async with aiohttp.ClientSession(connector=get_connector()) as session:
                    async with session.get(thumb_url, timeout=10) as resp:
                        if resp.status == 200:
                            thumbnail = await resp.read()
            except:
                pass
            
            logger.info(f"YouTube download OK with clients {clients}")
            
            return DownloadResult(
                success=True,
                platform='youtube',
                media_type=media_type,
                file_path=actual_path,
                temp_dir=temp_dir,
                title=title,
                duration=duration,
                size_mb=file_size,
                thumbnail=thumbnail
            )
            
        except Exception as e:
            error_str = str(e)
            if 'Sign in' in error_str or 'bot' in error_str.lower():
                logger.warning(f"YouTube bot detection with clients {clients} (attempt {client_attempt+1})")
                if client_attempt < len(client_configs) - 1:
                    # Eski fayllarni tozalab, keyingi clientni sinash
                    for f in os.listdir(temp_dir):
                        try:
                            os.remove(os.path.join(temp_dir, f))
                        except:
                            pass
                    continue
            
            logger.error(f"YouTube download error: {e}")
            return DownloadResult(
                success=False,
                platform='youtube',
                temp_dir=temp_dir,
                error=str(e)[:100]
            )
    
    return DownloadResult(
        success=False,
        platform='youtube',
        temp_dir=temp_dir,
        error="Barcha urinishlar muvaffaqiyatsiz"
    )



async def download_instagram(url: str) -> DownloadResult:
    """Instagram'dan video/rasm yuklash"""
    try:
        import yt_dlp
        
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, "media")
        
        ydl_opts = {
            # MAKSIMAL SIFAT
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
            'outtmpl': output_path + '.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': config.download_timeout,
            'merge_output_format': 'mp4',
            'force_ipv4': True,
            'user_agent': REAL_USER_AGENT,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Instagram')[:50]
        
        # Fayl topish
        actual_path = None
        media_type = 'video'
        for f in os.listdir(temp_dir):
            full_path = os.path.join(temp_dir, f)
            if f.endswith(('.mp4', '.webm')):
                actual_path = full_path
                media_type = 'video'
                break
            elif f.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                actual_path = full_path
                media_type = 'image'
        
        if not actual_path or not os.path.exists(actual_path):
            return DownloadResult(success=False, platform='instagram', error="Media topilmadi")
        
        file_size = os.path.getsize(actual_path) / (1024 * 1024)
        
        return DownloadResult(
            success=True,
            platform='instagram',
            media_type=media_type,
            file_path=actual_path,
            temp_dir=temp_dir,
            title=title,
            size_mb=file_size
        )
        
    except Exception as e:
        logger.error(f"Instagram download error: {e}")
        return DownloadResult(success=False, platform='instagram', error=str(e)[:100])


async def download_twitter(url: str) -> DownloadResult:
    """Twitter/X dan video/rasm yuklash"""
    try:
        import yt_dlp
        
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, "media")
        
        ydl_opts = {
            # MAKSIMAL SIFAT
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
            'outtmpl': output_path + '.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': config.download_timeout,
            'merge_output_format': 'mp4',
            'force_ipv4': True,
            'user_agent': REAL_USER_AGENT,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Twitter')[:50]
        
        # Fayl topish
        actual_path = None
        media_type = 'video'
        for f in os.listdir(temp_dir):
            full_path = os.path.join(temp_dir, f)
            if f.endswith(('.mp4', '.webm')):
                actual_path = full_path
                media_type = 'video'
                break
            elif f.endswith(('.jpg', '.jpeg', '.png')):
                actual_path = full_path
                media_type = 'image'
        
        if not actual_path:
            return DownloadResult(success=False, platform='twitter', error="Media topilmadi")
        
        file_size = os.path.getsize(actual_path) / (1024 * 1024)
        
        return DownloadResult(
            success=True,
            platform='twitter',
            media_type=media_type,
            file_path=actual_path,
            temp_dir=temp_dir,
            title=title,
            size_mb=file_size
        )
        
    except Exception as e:
        logger.error(f"Twitter download error: {e}")
        return DownloadResult(success=False, platform='twitter', error=str(e)[:100])


async def download_pinterest(url: str) -> DownloadResult:
    """Pinterest'dan rasm/video yuklash"""
    try:
        temp_dir = tempfile.mkdtemp()
        
        # Pinterest sahifasini olish va rasm URL ni topish
        async with aiohttp.ClientSession(connector=get_connector()) as session:
            headers = {'User-Agent': REAL_USER_AGENT}
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return DownloadResult(success=False, platform='pinterest', error="Sahifa ochilmadi")
                
                html = await resp.text()
                
                # Rasm URL ni topish (turli patternlar)
                import re
                patterns = [
                    r'"originals":\s*{\s*"url":\s*"([^"]+)"',
                    r'"url":\s*"(https://i\.pinimg\.com/originals/[^"]+)"',
                    r'<meta property="og:image" content="([^"]+)"',
                    r'"image_signature":"[^"]+","images":\{"orig":\{"url":"([^"]+)"',
                    r'https://i\.pinimg\.com/\d+x\d+/[a-zA-Z0-9/]+\.[a-z]+',
                ]
                
                img_url = None
                for pattern in patterns:
                    match = re.search(pattern, html)
                    if match:
                        if match.groups():
                            img_url = match.group(1).replace('\\u002F', '/')
                        else:
                            img_url = match.group(0)
                        # originals versiyasini olishga harakat qilish
                        if 'pinimg.com' in img_url and '/originals/' not in img_url:
                            img_url = re.sub(r'/\d+x\d+/', '/originals/', img_url)
                        break
                
                if not img_url:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return DownloadResult(success=False, platform='pinterest', error="Rasm topilmadi")
                
                # Rasm yuklash
                async with session.get(img_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as img_resp:
                    if img_resp.status != 200:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        return DownloadResult(success=False, platform='pinterest', error="Rasm yuklanmadi")
                    
                    # Fayl kengaytmasini aniqlash
                    ext = '.jpg'
                    content_type = img_resp.headers.get('content-type', '')
                    if 'png' in content_type:
                        ext = '.png'
                    elif 'webp' in content_type:
                        ext = '.webp'
                    elif 'gif' in content_type:
                        ext = '.gif'
                    
                    output_path = os.path.join(temp_dir, f"pinterest{ext}")
                    with open(output_path, 'wb') as f:
                        f.write(await img_resp.read())
                    
                    file_size = os.path.getsize(output_path) / (1024 * 1024)
                    
                    return DownloadResult(
                        success=True,
                        platform='pinterest',
                        media_type='image',
                        file_path=output_path,
                        temp_dir=temp_dir,
                        title='Pinterest',
                        size_mb=file_size
                    )
        
    except Exception as e:
        logger.error(f"Pinterest download error: {e}")
        if 'temp_dir' in locals():
            shutil.rmtree(temp_dir, ignore_errors=True)
        return DownloadResult(success=False, platform='pinterest', error=str(e)[:100])


async def download_media(url: str, media_type: str = "video", no_watermark: bool = False, progress_callback=None) -> DownloadResult:
    """
    Asosiy yuklash funksiyasi - platformani aniqlaydi va yuklaydi
    
    Args:
        url: Media URL
        media_type: 'video' yoki 'audio'
        no_watermark: TikTok uchun watermark olib tashlash
        progress_callback: Progress callback funksiyasi
    """
    platform = detect_platform(url)
    
    if not platform:
        return DownloadResult(
            success=False,
            error="Bu platforma qo'llab-quvvatlanmaydi"
        )
    
    logger.info(f"Downloading from {platform}: {url[:50]}")
    
    if progress_callback:
        await progress_callback("📥 Yuklanmoqda...")
    
    # Platform-specific download
    if platform == 'youtube':
        return await download_youtube(url, media_type)
    elif platform == 'tiktok':
        return await download_tiktok(url, no_watermark)
    elif platform == 'instagram':
        return await download_instagram(url)
    elif platform == 'twitter':
        return await download_twitter(url)
    elif platform == 'facebook':
        return await download_twitter(url)
    elif platform == 'pinterest':
        return await download_pinterest(url)
    elif platform == 'spotify':
        return await download_spotify(url)
    elif platform == 'soundcloud':
        return await download_soundcloud(url)
    elif platform == 'vk':
        return await download_vk(url)
    elif platform == 'likee':
        return await download_likee(url)
    # Yangi platformalar - universal download
    elif platform in ['dailymotion', 'vimeo', 'reddit', 'tumblr', 'twitch', 'okru', 'rutube']:
        return await download_generic(url, platform)
    else:
        return DownloadResult(
            success=False,
            platform=platform,
            error="Bu platforma hali qo'shilmagan"
        )


async def download_generic(url: str, platform: str) -> DownloadResult:
    """
    Universal yuklash funksiyasi (yt-dlp bilan) - MAKSIMAL SIFAT
    Dailymotion, Vimeo, Reddit, Tumblr, Twitch, OK.ru, Rutube uchun
    """
    try:
        import yt_dlp
        
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, "media.%(ext)s")
        
        ydl_opts = {
            # MAKSIMAL SIFAT - eng yaxshi video va audio
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': config.download_timeout,
            'merge_output_format': 'mp4',
            # Sifatni saqlash
            'postprocessor_args': {
                'ffmpeg': ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k']
            },
            'force_ipv4': True,
            'user_agent': REAL_USER_AGENT,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', platform.capitalize())[:50]
            duration = info.get('duration', 0)
        
        # Fayl topish
        actual_path = None
        media_type = 'video'
        
        for f in os.listdir(temp_dir):
            full_path = os.path.join(temp_dir, f)
            if f.endswith(('.mp4', '.webm', '.mkv')):
                actual_path = full_path
                media_type = 'video'
                break
            elif f.endswith(('.jpg', '.png', '.gif', '.webp')):
                actual_path = full_path
                media_type = 'image'
                break
        
        if not actual_path:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return DownloadResult(success=False, platform=platform, error="Media topilmadi")
        
        file_size = os.path.getsize(actual_path) / (1024 * 1024)
        
        # Hajm tekshirish
        # Hajm tekshirish (faqat ogohlantirish)
        if file_size > config.max_video_size_mb:
             logger.warning(f"File size {file_size:.1f}MB > limit. Telegram might fail.")
        
        return DownloadResult(
            success=True,
            platform=platform,
            media_type=media_type,
            file_path=actual_path,
            temp_dir=temp_dir,
            title=title,
            duration=duration,
            size_mb=file_size
        )
        
    except Exception as e:
        logger.error(f"{platform} download error: {e}")
        if 'temp_dir' in locals():
            shutil.rmtree(temp_dir, ignore_errors=True)
        return DownloadResult(success=False, platform=platform, error=str(e)[:100])


async def download_soundcloud(url: str) -> DownloadResult:
    """SoundCloud'dan musiqa yuklash"""
    try:
        import yt_dlp
        
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, "audio.mp3")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_path.replace('.mp3', '.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': config.download_timeout,
            'force_ipv4': True,
            'user_agent': REAL_USER_AGENT,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'SoundCloud')[:50]
            duration = info.get('duration', 0)
        
        # Fayl topish
        actual_path = None
        for f in os.listdir(temp_dir):
            if f.endswith(('.mp3', '.m4a', '.opus')):
                actual_path = os.path.join(temp_dir, f)
                break
        
        if not actual_path:
            return DownloadResult(success=False, platform='soundcloud', error="Audio topilmadi")
        
        file_size = os.path.getsize(actual_path) / (1024 * 1024)
        
        return DownloadResult(
            success=True,
            platform='soundcloud',
            media_type='audio',
            file_path=actual_path,
            temp_dir=temp_dir,
            title=title,
            duration=duration,
            size_mb=file_size
        )
        
    except Exception as e:
        logger.error(f"SoundCloud download error: {e}")
        return DownloadResult(success=False, platform='soundcloud', error=str(e)[:100])


async def download_vk(url: str) -> DownloadResult:
    """VK'dan video/musiqa yuklash"""
    try:
        import yt_dlp
        
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, "media")
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': output_path + '.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': config.download_timeout,
            'force_ipv4': True,
            'user_agent': REAL_USER_AGENT,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'VK')[:50]
            duration = info.get('duration', 0)
        
        # Fayl topish
        actual_path = None
        media_type = 'video'
        for f in os.listdir(temp_dir):
            full_path = os.path.join(temp_dir, f)
            if f.endswith(('.mp4', '.webm')):
                actual_path = full_path
                media_type = 'video'
                break
            elif f.endswith(('.mp3', '.m4a')):
                actual_path = full_path
                media_type = 'audio'
        
        if not actual_path:
            return DownloadResult(success=False, platform='vk', error="Media topilmadi")
        
        file_size = os.path.getsize(actual_path) / (1024 * 1024)
        
        if file_size > config.max_video_size_mb:
             logger.warning(f"File size {file_size:.1f}MB > limit.")
        
        return DownloadResult(
            success=True,
            platform='vk',
            media_type=media_type,
            file_path=actual_path,
            temp_dir=temp_dir,
            title=title,
            duration=duration,
            size_mb=file_size
        )
        
    except Exception as e:
        logger.error(f"VK download error: {e}")
        return DownloadResult(success=False, platform='vk', error=str(e)[:100])


async def download_likee(url: str) -> DownloadResult:
    """Likee'dan video yuklash"""
    try:
        import yt_dlp
        
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, "video.mp4")
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': config.download_timeout,
            'force_ipv4': True,
            'user_agent': REAL_USER_AGENT,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Likee')[:50]
            duration = info.get('duration', 0)
        
        # Fayl topish
        actual_path = None
        for f in os.listdir(temp_dir):
            if f.endswith(('.mp4', '.webm')):
                actual_path = os.path.join(temp_dir, f)
                break
        
        if not actual_path:
            return DownloadResult(success=False, platform='likee', error="Video topilmadi")
        
        file_size = os.path.getsize(actual_path) / (1024 * 1024)
        
        if file_size > config.max_video_size_mb:
             logger.warning(f"File size {file_size:.1f}MB > limit.")
        
        return DownloadResult(
            success=True,
            platform='likee',
            media_type='video',
            file_path=actual_path,
            temp_dir=temp_dir,
            title=title,
            duration=duration,
            size_mb=file_size
        )
        
    except Exception as e:
        logger.error(f"Likee download error: {e}")
        return DownloadResult(success=False, platform='likee', error=str(e)[:100])


async def download_tiktok(url: str, no_watermark: bool = False) -> DownloadResult:
    """
    TikTok'dan video yuklash
    
    Args:
        url: TikTok URL
        no_watermark: Watermark olib tashlash (API orqali)
    """
    try:
        import yt_dlp
        
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, "video.mp4")
        
        # No watermark - API orqali
        if no_watermark:
            try:
                api_url = f"https://www.tikwm.com/api/?url={url}"
                headers = {'User-Agent': REAL_USER_AGENT}
                async with aiohttp.ClientSession(connector=get_connector()) as session:
                    async with session.get(api_url, headers=headers, timeout=30) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get('code') == 0:
                                video_url = data.get('data', {}).get('play')
                                if video_url:
                                    async with session.get(video_url, timeout=60) as video_resp:
                                        if video_resp.status == 200:
                                            with open(output_path, 'wb') as f:
                                                f.write(await video_resp.read())
                                            
                                            title = data.get('data', {}).get('title', 'TikTok')[:50]
                                            duration = data.get('data', {}).get('duration', 0)
                                            file_size = os.path.getsize(output_path) / (1024 * 1024)
                                            
                                            return DownloadResult(
                                                success=True,
                                                platform='tiktok',
                                                media_type='video',
                                                file_path=output_path,
                                                temp_dir=temp_dir,
                                                title=title + " (no watermark)",
                                                duration=duration,
                                                size_mb=file_size
                                            )
            except Exception as e:
                logger.warning(f"TikTok no-watermark API error: {e}, falling back to yt-dlp")
        
        # Standard yt-dlp
        ydl_opts = {
            'format': 'best',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': config.download_timeout,
            'force_ipv4': True,
            'user_agent': REAL_USER_AGENT,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'TikTok Video')[:50]
            duration = info.get('duration', 0)
        
        actual_path = None
        for f in os.listdir(temp_dir):
            if f.endswith(('.mp4', '.webm')):
                actual_path = os.path.join(temp_dir, f)
                break
        
        if not actual_path or not os.path.exists(actual_path):
            return DownloadResult(success=False, platform='tiktok', error="Fayl topilmadi")
        
        file_size = os.path.getsize(actual_path) / (1024 * 1024)
        
        if file_size > config.max_video_size_mb:
             logger.warning(f"File size {file_size:.1f}MB > limit.")
        
        return DownloadResult(
            success=True,
            platform='tiktok',
            media_type='video',
            file_path=actual_path,
            temp_dir=temp_dir,
            title=title,
            duration=duration,
            size_mb=file_size
        )
        
    except Exception as e:
        logger.error(f"TikTok download error: {e}")
        return DownloadResult(success=False, platform='tiktok', error=str(e)[:100])


async def download_spotify(url: str) -> DownloadResult:
    """
    Spotify'dan musiqa yuklash
    spotdl kutubxonasi orqali
    """
    try:
        temp_dir = tempfile.mkdtemp()
        
        # spotdl orqali yuklash
        try:
            import subprocess
            result = subprocess.run(
                ['spotdl', url, '--output', temp_dir],
                capture_output=True,
                text=True,
                timeout=120
            )
        except FileNotFoundError:
            # spotdl o'rnatilmagan - yt-dlp orqali urinish
            import yt_dlp
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(temp_dir, 'audio.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Spotify Track')[:50]
        
        # Fayl topish
        actual_path = None
        for f in os.listdir(temp_dir):
            if f.endswith(('.mp3', '.m4a', '.opus', '.webm')):
                actual_path = os.path.join(temp_dir, f)
                break
        
        if not actual_path:
            return DownloadResult(success=False, platform='spotify', error="Audio topilmadi. spotdl o'rnatilmagan bo'lishi mumkin.")
        
        file_size = os.path.getsize(actual_path) / (1024 * 1024)
        
        # Fayl nomidan title olish
        title = os.path.splitext(os.path.basename(actual_path))[0][:50]
        
        return DownloadResult(
            success=True,
            platform='spotify',
            media_type='audio',
            file_path=actual_path,
            temp_dir=temp_dir,
            title=title,
            size_mb=file_size
        )
        
    except Exception as e:
        logger.error(f"Spotify download error: {e}")
        return DownloadResult(success=False, platform='spotify', error=str(e)[:100])
