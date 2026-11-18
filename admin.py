"""
handlers/admin.py — همه چیزِ مربوط به ادمین (فقط ADMIN_ID)
  • تایید سفارش با صف FIFO (چند سفارش هم‌زمان)
  • رد سفارش با علت اختیاری
  • دستورها: /stats /pending /backup /cancel /skip و ریستور با ارسال فایل .db + کپشن /restore
تمام هندلرهای این فایل با فیلتر روتر فقط برای ادمین کار می‌کنند؛ مشتری هرگز این دکمه‌ها را نمی‌بیند.
"""
import logging
import os
import shutil
import tempfile
from collections import deque

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import backup
import config
import database as db
import keyboards as kb
import services
from states import AdminStates
from utils import esc

log = logging.getLogger("admin")
order_log = logging.getLogger("orders")

router = Router()
router.message.filter(F.from_user.id == config.ADMIN_ID)
router.callback_query.filter(F.from_user.id == config.ADMIN_ID)

# صف FIFO سفارش‌هایی که ادمین «تایید» زده و منتظر ارسال کانفیگ‌اند
approval_queue: deque[int] = deque()


# ------------------------------------------------------------------ صف
async def activate_next(bot: Bot, state: FSMContext) -> None:
    """اگر ادمین آزاد است، اولین سفارش صف را فعال و کانفیگ را از او می‌خواهد."""
    if await state.get_state() is not None:
        return
    while approval_queue:
        order_id = approval_queue.popleft()
        order = await db.get_order(order_id)
        if not order or order["status"] != "pending":
            continue
        await state.set_state(AdminStates.waiting_config)
        await state.update_data(order_id=order_id)
        remaining = f"\n📥 در صف بعدی: {len(approval_queue)} سفارش" if approval_queue else ""
        await bot.send_message(
            config.ADMIN_ID,
            f"سفارش #{order_id} — {esc(order['plan_label'])}\n"
            f"👤 آیدی مشتری: <code>{order['user_id']}</code>\n\n"
            f"<b>کانفیگ یا آیدی را ارسال کنید</b>{remaining}\n"
            "(لغو: /cancel)",
        )
        return


# ------------------------------------------------------------------ دکمه‌ها
@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data.startswith("adm:ok:"))
async def cb_approve(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    order_id = int(cb.data.split(":")[2])
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        await cb.answer("این سفارش قبلاً بررسی شده است.", show_alert=True)
        return

    # --- سفارش شارژ: بدون نیاز به کانفیگ، مستقیم موجودی اضافه می‌شود
    if order["type"] == "topup":
        balance = await db.approve_topup(order_id)
        if balance is None:
            await cb.answer("این سفارش قبلاً بررسی شده است.", show_alert=True)
            return
        order_log.info("شارژ #%s تایید شد | user=%s | +%s | موجودی=%s",
                       order_id, order["user_id"], order["price"], balance)
        await services.mark_admin_card(bot, order, "✅ تایید شد")
        await cb.answer("✅ شارژ تایید شد")
        try:
            await bot.send_message(
                order["user_id"],
                f"✅ پرداخت شما تایید شد و <b>{order['price']:,} تومان</b> به کیف پول شما اضافه شد.\n"
                f"💰 موجودی فعلی: <b>{balance:,} تومان</b>",
                reply_markup=kb.only_back("menu:main"),
            )
        except TelegramAPIError:
            await bot.send_message(config.ADMIN_ID, f"⚠️ پیام شارژ #{order_id} به مشتری نرسید (ربات را بلاک کرده؟).")
        backup.schedule_backup(bot)
        return

    # --- سفارش کانفیگ: وارد صف FIFO می‌شود
    current = None
    if await state.get_state() == AdminStates.waiting_config.state:
        current = (await state.get_data()).get("order_id")
    if order_id in approval_queue or current == order_id:
        await cb.answer("این سفارش همین الان در صف/در حال انجام است.", show_alert=True)
        return

    approval_queue.append(order_id)
    order_log.info("سفارش #%s توسط ادمین تایید شد و در صف کانفیگ قرار گرفت", order_id)
    busy = await state.get_state() is not None
    await cb.answer("✅ در صف قرار گرفت" if busy else "✅")
    if busy:
        await bot.send_message(config.ADMIN_ID,
                               f"📥 سفارش #{order_id} در صف قرار گرفت (جایگاه {len(approval_queue)}).")
    await activate_next(bot, state)


@router.callback_query(F.data.startswith("adm:no:"))
async def cb_reject(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    order_id = int(cb.data.split(":")[2])
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        await cb.answer("این سفارش قبلاً بررسی شده است.", show_alert=True)
        return
    if await state.get_state() is not None:
        await cb.answer("ابتدا کار جاری را تمام کنید یا /cancel بزنید.", show_alert=True)
        return
    if order_id in approval_queue:
        approval_queue.remove(order_id)
    await state.set_state(AdminStates.waiting_reject_reason)
    await state.update_data(order_id=order_id)
    await cb.answer()
    await bot.send_message(
        config.ADMIN_ID,
        f"❌ رد سفارش #{order_id}\n\n"
        "علت رد را بنویسید (اختیاری). برای رد بدون علت /skip بزنید.\n(لغو: /cancel)",
    )


# ------------------------------------------------------------------ دستورها
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, bot: Bot) -> None:
    if await state.get_state() is None:
        await message.answer("کار فعالی وجود ندارد.")
        return
    order_id = (await state.get_data()).get("order_id")
    await state.clear()
    extra = f"\nسفارش #{order_id} همچنان در انتظار است و دکمه‌هایش فعال است." if order_id else ""
    await message.answer(f"↩️ لغو شد.{extra}")
    await activate_next(bot, state)


@router.message(Command("skip"), AdminStates.waiting_reject_reason)
async def cmd_skip(message: Message, state: FSMContext, bot: Bot) -> None:
    await _finish_reject(message, state, bot, None)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    s = await db.stats()
    o = s["orders"]
    await message.answer(
        "📊 <b>آمار ربات</b>\n\n"
        f"👥 کاربران: {s['users']}\n"
        f"🧾 سفارش‌ها: در انتظار {o.get('pending', 0)} | تایید {o.get('approved', 0)} | رد {o.get('rejected', 0)}\n"
        f"💵 جمع فروش تاییدشده: {s['sales']:,} تومان\n"
        f"➕ جمع شارژهای تاییدشده: {s['topups']:,} تومان\n"
        f"📥 صف کانفیگ: {len(approval_queue)}"
    )


@router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    rows = await db.list_pending()
    if not rows:
        await message.answer("✅ سفارش در انتظاری وجود ندارد.")
        return
    lines = [f"#{r['id']} | {esc(r['plan_label'])} | {r['price']:,} تومان | <code>{r['user_id']}</code>"
             for r in rows]
    await message.answer("⏳ <b>سفارش‌های در انتظار</b>\n\n" + "\n".join(lines) +
                         "\n\n(کارت هر سفارش بالاتر در همین چت است)")


@router.message(Command("backup"))
async def cmd_backup(message: Message, bot: Bot) -> None:
    ok = await backup.make_backup(bot, force=True)
    if not ok:
        await message.answer("❌ ساخت بکاپ ناموفق بود. لاگ‌ها را ببینید.")


@router.message(F.document, F.caption.startswith("/restore"))
async def cmd_restore(message: Message, bot: Bot, state: FSMContext) -> None:
    tmp_dir = tempfile.mkdtemp(prefix="botrestore_")
    try:
        path = os.path.join(tmp_dir, "restore.db")
        await bot.download(message.document, destination=path)
        if not backup.restore_from_file(path):
            await message.answer("❌ این فایل یک دیتابیس سالم از این ربات نیست.")
            return
        await db.init_db()
        await state.clear()
        s = await db.stats()
        await message.answer(f"✅ دیتابیس بازیابی شد.\n👥 کاربران: {s['users']}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ------------------------------------------------------------------ رد سفارش
async def _finish_reject(message: Message, state: FSMContext, bot: Bot, reason: str | None) -> None:
    order_id = (await state.get_data()).get("order_id")
    await state.clear()
    order = await db.get_order(order_id) if order_id else None
    if not order or not await db.reject_order(order_id, reason):
        await message.answer("این سفارش قبلاً بررسی شده است.")
        await activate_next(bot, state)
        return

    order_log.info("سفارش #%s رد شد | user=%s | علت=%s", order_id, order["user_id"], reason or "-")
    await services.mark_admin_card(bot, order, "❌ رد شد")
    text = "❌ رسید شما رد شد."
    if reason:
        text += f"\n\nعلت: {esc(reason)}"
    if order["receipt_type"] == "wallet":
        text += f"\n\n💰 مبلغ {order['price']:,} تومان به کیف پول شما برگشت داده شد."
    try:
        await bot.send_message(order["user_id"], text, reply_markup=kb.only_back("menu:main"))
        await message.answer(f"✅ سفارش #{order_id} رد شد و به مشتری اطلاع داده شد.")
    except TelegramAPIError:
        await message.answer(f"⚠️ سفارش #{order_id} رد شد ولی پیام به مشتری نرسید.")
    backup.schedule_backup(bot)
    await activate_next(bot, state)


@router.message(AdminStates.waiting_reject_reason, F.text)
async def msg_reject_reason(message: Message, state: FSMContext, bot: Bot) -> None:
    if message.text.startswith("/"):
        await message.answer("برای رد بدون علت /skip و برای لغو /cancel بزنید.")
        return
    await _finish_reject(message, state, bot, message.text.strip()[:500])


@router.message(AdminStates.waiting_reject_reason)
async def msg_reject_reason_invalid(message: Message) -> None:
    await message.answer("لطفاً علت را به صورت متن بنویسید، یا /skip بزنید.")


# ------------------------------------------------------------------ ارسال کانفیگ به مشتری
@router.message(AdminStates.waiting_config)
async def msg_config(message: Message, state: FSMContext, bot: Bot) -> None:
    if message.text and message.text.startswith("/"):
        await message.answer("الان منتظر کانفیگ هستم. برای لغو /cancel بزنید.")
        return

    order_id = (await state.get_data()).get("order_id")
    order = await db.get_order(order_id) if order_id else None
    if not order or order["status"] != "pending":
        await state.clear()
        await message.answer("این سفارش دیگر در انتظار نیست.")
        await activate_next(bot, state)
        return

    customer = order["user_id"]
    try:
        await bot.send_message(customer, "✅ پرداخت شما تایید شد. کانفیگ شما در پیام زیر ارسال شد:")
        # پیام ادمین عیناً (متن/عکس/فایل) برای مشتری کپی می‌شود
        await bot.copy_message(chat_id=customer, from_chat_id=message.chat.id,
                               message_id=message.message_id)
    except TelegramForbiddenError:
        await message.answer("⚠️ مشتری ربات را بلاک کرده و پیام نرسید. /cancel بزنید یا بعداً دوباره تلاش کنید.")
        return
    except TelegramAPIError as e:
        await message.answer(f"⚠️ ارسال به مشتری ناموفق بود: {esc(str(e))}\nدوباره بفرستید یا /cancel بزنید.")
        return

    await db.approve_order(order_id)
    inviter = await db.grant_referral_reward(order_id)
    await state.clear()
    if inviter:
        order_log.info("جایزه دعوت: کاربر %s یک کانفیگ رایگان گرفت (خرید #%s)", inviter, order_id)
        try:
            await bot.send_message(
                inviter,
                "🎉 یکی از دوستانی که دعوت کرده بودید اولین پلنش را خرید!\n"
                "یک <b>کانفیگ ۱ گیگ رایگان</b> به شما اضافه شد. از بخش «🎁 دعوت از دوستان» دریافتش کنید.",
                reply_markup=kb.only_back("menu:main"))
        except TelegramAPIError:
            pass
    order_log.info("سفارش #%s تایید و کانفیگ ارسال شد | user=%s", order_id, customer)
    await services.mark_admin_card(bot, order, "✅ تایید شد")
    await message.answer("✅ کانفیگ برای مشتری ارسال شد.")
    backup.schedule_backup(bot)
    await activate_next(bot, state)
