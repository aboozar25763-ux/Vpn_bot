"""
utils.py — توابع کمکی
"""
import html
from datetime import datetime, timedelta, timezone

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))  # ایران ساعت تابستانی ندارد

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def esc(text: str | None) -> str:
    """escape برای HTML تلگرام."""
    return html.escape(text or "")


def normalize_number(text: str) -> str:
    """ارقام فارسی/عربی را لاتین و جداکننده‌ها را حذف می‌کند."""
    text = text.translate(_DIGITS)
    for ch in (",", "٬", "،", " ", "تومان"):
        text = text.replace(ch, "")
    return text.strip()


def to_iran_time(utc_str: str) -> str:
    try:
        dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone(IRAN_TZ).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return utc_str or "-"


def user_link_name(user: dict | None) -> str:
    if not user:
        return "-"
    return esc(user.get("first_name") or "-")


async def show(event: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """پیام فعلی را ویرایش می‌کند؛ اگر نشد پیام جدید می‌فرستد."""
    msg = event.message
    if isinstance(msg, Message):
        try:
            await msg.edit_text(text, reply_markup=kb)
            return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return
        await msg.answer(text, reply_markup=kb)
        return
    await event.bot.send_message(event.from_user.id, text, reply_markup=kb)
