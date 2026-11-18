"""
handlers/payment.py — کیف پول، شارژ، صفحه پرداخت کارت‌به‌کارت، دریافت رسید، پرداخت با کیف پول
قیمت همیشه از روی کد پلن و از فایل plans.py محاسبه می‌شود (هیچ قیمت ثابتی در متن‌ها نیست).
"""
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
import database as db
import keyboards as kb
import plans
import services
from backup import schedule_backup
from states import PaymentStates
from utils import esc, normalize_number, show

log = logging.getLogger("payment")
order_log = logging.getLogger("orders")
router = Router()


# ------------------------------------------------------------------ کمکی
def resolve_item(code: str) -> dict | None:
    """از روی کد (n:30:5 / s:150 / t:150000) مشخصات سفارش را برمی‌گرداند."""
    if code.startswith("t:"):
        try:
            amount = int(code[2:])
        except ValueError:
            return None
        if not config.MIN_TOPUP <= amount <= config.MAX_TOPUP:
            return None
        return dict(label=f"شارژ کیف پول ({amount:,} تومان)", category="topup", duration="-",
                    price=amount, type="topup", extra="")
    plan = plans.get_plan(code)
    if not plan:
        return None
    return dict(label=plan.label, category=plan.category, duration=plan.duration,
                price=plan.price, type="config", extra=plan.extra)


def payment_text(item: dict) -> str:
    extra = f"{item['extra']}\n" if item["extra"] else ""
    return (
        "💳 <b>پرداخت سفارش</b>\n\n"
        f"📦 {esc(item['label'])}\n"
        f"{extra}"
        f"💵 مبلغ قابل پرداخت: <b>{item['price']:,} تومان</b>\n\n"
        f"🏦 شماره کارت:\n<code>{config.CARD_NUMBER}</code>\n"
        f"👤 به نام: {esc(config.CARD_HOLDER)}\n\n"
        "لطفاً دقیقاً مبلغ پلن انتخابی را به شماره کارت بالا واریز کنید.\n\n"
        "⚠️ اگر بیش از ۳۰ دقیقه از زمان پرداخت بگذرد، پرداخت شما حساب نمی‌شود.\n"
        "⏳ بعد از ارسال رسید، حداکثر تا ۳۰ دقیقه رسید شما بررسی و تایید می‌شود. لطفاً صبر کنید."
    )


async def _balance(user_id: int) -> int:
    user = await db.get_user(user_id)
    return user["balance"] if user else 0


# ------------------------------------------------------------------ کیف پول
@router.callback_query(F.data == "menu:wallet")
async def cb_wallet(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user = cb.from_user
    await db.upsert_user(user.id, user.username, user.first_name)
    balance = await _balance(user.id)
    await cb.answer()
    await show(cb, f"💰 <b>کیف پول</b>\n\nموجودی فعلی: <b>{balance:,} تومان</b>", kb.wallet_kb())


@router.callback_query(F.data == "topup:start")
async def cb_topup_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PaymentStates.waiting_amount)
    await cb.answer()
    await show(
        cb,
        "➕ <b>شارژ حساب</b>\n\n"
        f"مبلغ مورد نظر را به <b>تومان</b> و به صورت عدد بفرستید.\n"
        f"(حداقل {config.MIN_TOPUP:,} و حداکثر {config.MAX_TOPUP:,} تومان)",
        kb.only_back("menu:wallet"),
    )


@router.message(PaymentStates.waiting_amount, F.text)
async def msg_topup_amount(message: Message, state: FSMContext) -> None:
    raw = normalize_number(message.text)
    if not raw.isdigit():
        await message.answer("❌ لطفاً فقط یک عدد بفرستید. مثال: 150000", reply_markup=kb.only_back("menu:wallet"))
        return
    amount = int(raw)
    if not config.MIN_TOPUP <= amount <= config.MAX_TOPUP:
        await message.answer(
            f"❌ مبلغ باید بین {config.MIN_TOPUP:,} و {config.MAX_TOPUP:,} تومان باشد.",
            reply_markup=kb.only_back("menu:wallet"))
        return
    await state.clear()
    code = f"t:{amount}"
    item = resolve_item(code)
    await message.answer(payment_text(item), reply_markup=kb.payment_kb(code, amount))


@router.message(PaymentStates.waiting_amount)
async def msg_topup_amount_invalid(message: Message) -> None:
    await message.answer("❌ لطفاً مبلغ را به صورت عدد بفرستید.", reply_markup=kb.only_back("menu:wallet"))


# ------------------------------------------------------------------ نمایش صفحه پرداخت یک پلن
@router.callback_query(F.data.startswith("plan:"))
async def cb_plan(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    code = cb.data.split(":", 1)[1]
    item = resolve_item(code)
    if not item:
        await cb.answer("این پلن دیگر موجود نیست.", show_alert=True)
        return
    user = cb.from_user
    await db.upsert_user(user.id, user.username, user.first_name)
    balance = await _balance(user.id)
    await cb.answer()
    await show(cb, payment_text(item), kb.payment_kb(code, item["price"], balance))


# ------------------------------------------------------------------ ارسال رسید
@router.callback_query(F.data.startswith("rcpt:"))
async def cb_receipt_start(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    code = cb.data.split(":", 1)[1]
    if not resolve_item(code):
        await cb.answer("این سفارش معتبر نیست.", show_alert=True)
        return
    await state.set_state(PaymentStates.waiting_receipt)
    await state.update_data(code=code)
    await cb.answer()
    await bot.send_message(
        cb.from_user.id,
        "📤 لطفاً <b>عکس یا فایل رسید</b> پرداخت را همین‌جا بفرستید.\n"
        "برای لغو، دکمه بازگشت را بزنید.",
        reply_markup=kb.only_back("menu:main"),
    )


@router.message(PaymentStates.waiting_receipt, F.photo | F.document)
async def msg_receipt(message: Message, state: FSMContext, bot: Bot) -> None:
    user = message.from_user
    data = await state.get_data()
    item = resolve_item(data.get("code", ""))
    if not item:
        await state.clear()
        await message.answer("⌛️ این جلسه منقضی شده است. لطفاً دوباره از منو شروع کنید.",
                             reply_markup=kb.main_menu())
        return

    if message.photo:
        file_id, rtype = message.photo[-1].file_id, "photo"
    else:
        doc = message.document
        mime = doc.mime_type or ""
        if not (mime.startswith("image/") or mime == "application/pdf"):
            await message.answer("❌ فقط عکس یا فایل PDF رسید قابل قبول است.")
            return
        file_id, rtype = doc.file_id, "document"

    await db.upsert_user(user.id, user.username, user.first_name)
    if await db.count_pending(user.id) >= config.MAX_PENDING_ORDERS:
        await state.clear()
        await message.answer("⚠️ شما چند سفارش در حال بررسی دارید. لطفاً تا تعیین وضعیت آن‌ها صبر کنید.",
                             reply_markup=kb.main_menu())
        return

    order_id = await db.create_order(user.id, item["label"], item["category"], item["duration"],
                                     item["price"], item["type"], file_id, rtype)
    await state.clear()
    order_log.info("سفارش جدید #%s | user=%s | %s | %s تومان | %s",
                   order_id, user.id, item["label"], item["price"], item["type"])

    await message.answer("✅ رسید شما دریافت شد و حداکثر تا ۳۰ دقیقه بررسی می‌شود. لطفاً صبر کنید.",
                         reply_markup=kb.only_back("menu:main"))
    if not await services.send_order_to_admin(bot, order_id):
        order_log.error("سفارش #%s برای ادمین ارسال نشد! ادمین باید ربات را /start کرده باشد.", order_id)


@router.message(PaymentStates.waiting_receipt)
async def msg_receipt_invalid(message: Message) -> None:
    await message.answer("❌ لطفاً فقط <b>عکس یا فایل رسید</b> را بفرستید.",
                         reply_markup=kb.only_back("menu:main"))


# ------------------------------------------------------------------ پرداخت از کیف پول
@router.callback_query(F.data.startswith("wpay:"))
async def cb_wallet_pay(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user = cb.from_user
    item = resolve_item(cb.data.split(":", 1)[1])
    if not item or item["type"] != "config":
        await cb.answer("این سفارش معتبر نیست.", show_alert=True)
        return
    if await db.count_pending(user.id) >= config.MAX_PENDING_ORDERS:
        await cb.answer("شما چند سفارش در حال بررسی دارید. کمی صبر کنید.", show_alert=True)
        return
    if not await db.deduct_balance(user.id, item["price"]):
        await cb.answer("❌ موجودی کیف پول کافی نیست.", show_alert=True)
        return

    order_id = await db.create_order(user.id, item["label"], item["category"], item["duration"],
                                     item["price"], item["type"], None, "wallet")
    order_log.info("سفارش #%s با کیف پول | user=%s | %s | %s تومان",
                   order_id, user.id, item["label"], item["price"])
    await cb.answer("✅ پرداخت شد")
    await show(
        cb,
        f"✅ مبلغ <b>{item['price']:,} تومان</b> از کیف پول شما کسر شد.\n"
        "سفارش برای ادمین ارسال شد و حداکثر تا ۳۰ دقیقه کانفیگ شما ارسال می‌شود. لطفاً صبر کنید.",
        kb.only_back("menu:main"),
    )
    if not await services.send_order_to_admin(bot, order_id):
        order_log.error("سفارش #%s برای ادمین ارسال نشد!", order_id)
    schedule_backup(bot)
