"""
handlers/shop.py — منوی خرید: دسته‌ها، مدت، حجم (فقط نمایش و انتخاب)
انتخاب نهایی پلن در payment.py مدیریت می‌شود.
"""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import keyboards as kb
import plans
from utils import show

router = Router()


@router.callback_query(F.data == "menu:buy")
async def cb_buy(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    await show(cb, "🛒 <b>ساخت کانفیگ جدید</b>\n\nدسته‌بندی مورد نظر را انتخاب کنید:", kb.category_kb())


@router.callback_query(F.data == "cat:normal")
async def cb_normal(cb: CallbackQuery) -> None:
    await cb.answer()
    await show(cb, f"📦 <b>پلن‌های معمولی</b>\n\n{plans.NORMAL_NOTE}\n\n⏱ مدت زمان را انتخاب کنید:",
               kb.durations_kb())


@router.callback_query(F.data.startswith("dur:"))
async def cb_duration(cb: CallbackQuery) -> None:
    key = cb.data.split(":", 1)[1]
    group = plans.NORMAL_PLANS.get(key)
    if not group:
        await cb.answer("این گزینه معتبر نیست.", show_alert=True)
        return
    what = "حجم" if group["kind"] == "volume" else "مدت"
    await cb.answer()
    await show(cb, f"📦 <b>پلن {group['title']}</b>\n\n{what} مورد نظر را انتخاب کنید:", kb.items_kb(key))


@router.callback_query(F.data == "cat:static")
async def cb_static(cb: CallbackQuery) -> None:
    await cb.answer()
    await show(cb, f"🔒 <b>پلن آی‌پی ثابت 🇩🇪</b>\n\n{plans.STATIC_NOTE}\n\nحجم مورد نظر را انتخاب کنید:",
               kb.static_kb())
