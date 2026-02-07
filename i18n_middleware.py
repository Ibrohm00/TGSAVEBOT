import json
import os
from typing import Callable, Dict, Any, Awaitable, Union
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, User

from database import get_user_language

# Cache for loaded locales
_locales = {}

def load_locales():
    """Load all locale files from locales/ directory"""
    global _locales
    locales_dir = "locales"
    for filename in os.listdir(locales_dir):
        if filename.endswith(".json"):
            lang_code = filename.split(".")[0]
            with open(os.path.join(locales_dir, filename), "r", encoding="utf-8") as f:
                _locales[lang_code] = json.load(f)

# Load locales on module import
load_locales()

def t(key: str, lang: str = "uz", **kwargs) -> str:
    """Translate text by key"""
    try:
        text = _locales.get(lang, {}).get(key, _locales.get("uz", {}).get(key, key))
        if kwargs:
            return text.format(**kwargs)
        return text
    except Exception:
        return key

class I18nMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], Dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: Dict[str, Any]
    ) -> Any:
        
        user: User = data.get("event_from_user")
        
        if user:
            # Get user language from DB
            lang = await get_user_language(user.id)
        else:
            lang = "uz"
            
        # Inject language and translate function into data
        data["lang"] = lang
        data["t"] = lambda key, **kwargs: t(key, lang, **kwargs)
        
        return await handler(event, data)
