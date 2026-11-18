"""
handlers/start.py — /start، عضویت اجباری، منوی اصلی، دعوت دوستان، پشتیبانی
"""
import logging
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
import database as db
import keyboards as kb
import services
from utils import esc, show

log = logging.getLogger("start")
router = Router()


def welcome_text(name: str) -> str:
    return (
        f"سلام {esc(name)} عزیز 👋\n"
        "به ربات فروش کانفیگ VPN خوش آمدید 🌐\n\n"
        "از منوی زیر یکی از گزینه‌ها را انتخاب کنید:"
    )


def parse_referrer(args: str | None) -> int | None:
    """/start ref_123456  →  123456"""
    if args and args.startswith("ref_") and args[4:].isdigit():
        return int(args[4:])
    return None


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    await db.upsert_user(user.id, user.username, user.first_name, parse_referrer(command.args))

    if user.id != config.ADMIN_ID:
        missing = await services.missing_channels(bot, user.id, force=True)
        if missing:
            await message.answer(services.JOIN_TEXT, reply_markup=kb.join_kb(missing))
            return
    await message.answer(welcome_text(user.first_name), reply_markup=kb.main_menu())


@router.callback_query(F.data == "check_sub")
async def cb_check_sub(cb: CallbackQuery, bot: Bot) -> None:
    user = cb.from_user
    await db.upsert_user(user.id, user.username, user.first_name)
    missing = await services.missing_channels(bot, user.id, force=True)
    if missing:
        await cb.answer("❌ هنوز عضو نشده‌اید.", show_alert=True)
        await show(cb, services.JOIN_WARN, kb.join_kb(missing))
        return
    await cb.answer("✅ عضویت شما تایید شد.")
    await show(cb, welcome_text(user.first_name), kb.main_menu())


@router.callback_query(F.data == "menu:main")
async def cb_main(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    await show(cb, welcome_text(cb.from_user.first_name), kb.main_menu())


@router.callback_query(F.data == "menu:ref")
async def cb_referral(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    await _show_referral(cb, bot)


async def _show_referral(cb: CallbackQuery, bot: Bot) -> None:
    uid = cb.from_user.id
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    invited = await db.count_invited(uid)
    buyers = await db.count_referral_buyers(uid)
    user = await db.get_user(uid)
    free = user["free_configs"] if user else 0
    text = (
        "🎁 <b>دعوت از دوستان</b>\n\n"
        "لینک اختصاصی شما:\n"
        f"<code>{link}</code>\n\n"
        "هر دوستی که با لینک شما وارد شود و <b>اولین پلنش را بخرد</b>، "
        "یک <b>کانفیگ ۱ گیگ رایگان</b> برای شما می‌آورد.\n\n"
        f"👥 تعداد دعوت‌شدگان: <b>{invited}</b> نفر\n"
        f"🛍 دعوت‌شدگانی که خرید کرده‌اند: <b>{buyers}</b> نفر\n"
        f"🎁 کانفیگ رایگان قابل دریافت: <b>{free}</b>"
    )
    share = f"https://t.me/share/url?url={quote(link)}&text={quote('ربات فروش کانفیگ VPN 🌐')}"
    await show(cb, text, kb.referral_kb(share, free))


@router.callback_query(F.data == "ref:claim")
async def cb_claim_free(cb: CallbackQuery, bot: Bot) -> None:
    user = cb.from_user
    if await db.count_pending(user.id) >= config.MAX_PENDING_ORDERS:
        await cb.answer("شما چند سفارش در حال بررسی دارید. کمی صبر کنید.", show_alert=True)
        return
    if not await db.claim_free_config(user.id):
        await cb.answer("کانفیگ رایگانی برای دریافت ندارید.", show_alert=True)
        return
    order_id = await db.create_order(user.id, "🎁 کانفیگ رایگان ۱ گیگ (جایزه دعوت)", "normal",
                                     "reward", 0, "config", None, "reward")
    logging.getLogger("orders").info("درخواست کانفیگ رایگان #%s | user=%s", order_id, user.id)
    await cb.answer("✅ ثبت شد")
    await show(cb, "✅ درخواست کانفیگ رایگان شما ثبت شد و برای ادمین ارسال شد. "
                   "به‌زودی کانفیگ برایتان ارسال می‌شود.", kb.only_back("menu:main"))
    await services.send_order_to_admin(bot, order_id)


@router.callback_query(F.data == "menu:support")
async def cb_support(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    url = services.support_url
    if url:
        text = "🆘 <b>پشتیبانی</b>\n\nبرای ارتباط با پشتیبانی روی دکمه زیر بزنید."
    else:
        text = (
            "🆘 <b>پشتیبانی</b>\n\n"
            "پشتیبانی به‌زودی خودش با شما ارتباط می‌گیرد. "
            "اگر سفارشی دارید، منتظر پیام ربات بمانید."
        )
    await cb.answer()
    await show(cb, text, kb.support_kb(url))
