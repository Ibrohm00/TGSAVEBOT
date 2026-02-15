import logging
from typing import Callable, Dict, Any, Awaitable, Union, List
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatMemberStatus

from database import get_channels
from config import config

logger = logging.getLogger(__name__)

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], Dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: Dict[str, Any]
    ) -> Any:
        
        bot = data.get("bot")
        user = data.get("event_from_user")
        
        if not user:
            return await handler(event, data)
            
        # Adminlar uchun tekshiruv shart emas
        if user.id in config.admin_ids:
            return await handler(event, data)

        # Kanallarni olish
        channels = await get_channels()
        if not channels:
            return await handler(event, data)
        
        not_subscribed = []
        
        for ch in channels:
            try:
                member = await bot.get_chat_member(chat_id=ch['channel_id'], user_id=user.id)
                if member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
                    not_subscribed.append(ch)
            except Exception as e:
                logger.error(f"Error checking subscription for {ch['channel_id']}: {e}")
                # Agar bot kanal admini bo'lmasa yoki boshqa xato bo'lsa, o'tkazib yuboramiz (user aybi emas)
                continue
                
        if not not_subscribed:
            return await handler(event, data)
            
        # Obuna bo'lmagan kanallari bor
        buttons = []
        for ch in not_subscribed:
            buttons.append([InlineKeyboardButton(text=f"➕ {ch['title']}", url=ch['invite_link'])])
            
        buttons.append([InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_subscription")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        text = "🚫 **Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:**"
        
        # CallbackQuery bo'lsa (masalan "check_subscription" tugmasini bosganda)
        if isinstance(event, CallbackQuery):
            if event.data == "check_subscription":
                await event.answer("❌ Hali hammasiga obuna bo'lmadingiz!", show_alert=True)
                # Xabarni yangilash (agar kerak bo'lsa)
                return
            await event.answer("Avval kanallarga obuna bo'ling!", show_alert=True)
            # Yoki xabar yuborish mumkin
            # await event.message.answer(text, reply_markup=keyboard) 
            return

        # Message bo'lsa
        if isinstance(event, Message):
            await event.answer(text, reply_markup=keyboard, parse_mode="Markdown")
            return
            

        return await handler(event, data)


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 0.5):
        self.limit = limit
        self.storage: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], Dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: Dict[str, Any]
    ) -> Any:
        
        user = data.get("event_from_user")
        
        if not user:
            return await handler(event, data)
        
        # Adminlar uchun limit yo'q
        if user.id in config.admin_ids:
            return await handler(event, data)
            
        import time
        now = time.time()
        last_request = self.storage.get(user.id, 0)
        
        if now - last_request < self.limit:
            # Silent drop (spamdan himoya)
            return

        self.storage[user.id] = now
        return await handler(event, data)
