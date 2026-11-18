"""
handlers/fallback.py — پیام‌ها و دکمه‌های پیش‌بینی‌نشده (آخرین روتر)
"""
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

import keyboards as kb

router = Router()


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query()
async def cb_unknown(cb: CallbackQuery) -> None:
    await cb.answer("⌛️ این دکمه منقضی شده است. لطفاً /start را بزنید.", show_alert=True)


@router.message(F.chat.type == "private")
async def msg_unknown(message: Message) -> None:
    await message.answer("🤔 متوجه نشدم. لطفاً از دکمه‌های زیر استفاده کنید:", reply_markup=kb.main_menu())
