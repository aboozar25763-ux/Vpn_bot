"""
middlewares.py — ضد اسپم و الزام عضویت در کانال‌ها
"""
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

import config
import keyboards as kb
import services
from utils import show


class ThrottleMiddleware(BaseMiddleware):
    """جلوگیری از اسپم: فاصله حداقل بین دو درخواست هر کاربر."""

    def __init__(self, rate: float = 0.6) -> None:
        self.rate = rate
        self._last: dict[int, float] = {}

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user and user.id != config.ADMIN_ID:
            now = time.monotonic()
            if now - self._last.get(user.id, 0.0) < self.rate:
                if isinstance(event, CallbackQuery):
                    await event.answer("⏳ کمی آهسته‌تر لطفاً")
                return None
            if len(self._last) > 20000:
                self._last.clear()
            self._last[user.id] = now
        return await handler(event, data)


class MembershipMiddleware(BaseMiddleware):
    """
    روی دکمه‌ها (callback) اجرا می‌شود: اگر کاربر از کانال‌ها خارج شده باشد، دوباره صفحه عضویت نمایش داده می‌شود.
    (روی /start و «✅ عضو شدم» خودِ هندلر بررسی را انجام می‌دهد.)
    """

    async def __call__(self, handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
                       event: CallbackQuery, data: dict[str, Any]) -> Any:
        user = event.from_user
        payload = event.data or ""
        if user.id == config.ADMIN_ID or payload in ("check_sub", "noop") or payload.startswith("adm:"):
            return await handler(event, data)
        missing = await services.missing_channels(data["bot"], user.id)
        if missing:
            await event.answer("ابتدا در کانال‌ها عضو شوید.", show_alert=True)
            await show(event, services.JOIN_TEXT, kb.join_kb(missing))
            return None
        return await handler(event, data)
