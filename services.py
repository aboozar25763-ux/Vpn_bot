"""
services.py — منطق مشترک: بررسی عضویت، ارسال سفارش به ادمین، لینک پشتیبانی
"""
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import config
import database as db
import keyboards as kb
from utils import esc, to_iran_time

log = logging.getLogger("services")
order_log = logging.getLogger("orders")

# ---------------------------------------------------------------- عضویت در کانال
_member_cache: dict[int, float] = {}  # فقط نتیجه «عضو هستند» را چند دقیقه نگه می‌داریم
_CACHE_SECONDS = 120


def channel_chat_id(url: str) -> str:
    """https://t.me/Name  →  @Name"""
    name = url.strip().rstrip("/").split("/")[-1].lstrip("@")
    if name.lstrip("-").isdigit():
        return name
    return "@" + name


async def is_member(bot: Bot, chat_id: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError as e:
        # معمولاً یعنی ربات در کانال ادمین نیست یا آدرس کانال اشتباه است
        log.error("getChatMember برای %s ناموفق بود: %s", chat_id, e)
        return False
    if member.status in ("creator", "administrator", "member"):
        return True
    return member.status == "restricted" and bool(getattr(member, "is_member", False))


async def missing_channels(bot: Bot, user_id: int, force: bool = False) -> list[tuple[int, str]]:
    """لیست کانال‌هایی که کاربر هنوز عضو آن‌ها نیست: [(شماره, لینک), ...]"""
    if not force and _member_cache.get(user_id, 0) > time.monotonic():
        return []
    missing = []
    for number, url in enumerate(config.CHANNELS, start=1):
        if not await is_member(bot, channel_chat_id(url), user_id):
            missing.append((number, url))
    if not missing:
        if len(_member_cache) > 20000:
            _member_cache.clear()
        _member_cache[user_id] = time.monotonic() + _CACHE_SECONDS
    return missing


JOIN_TEXT = (
    "👋 برای استفاده از ربات، ابتدا در کانال‌های زیر عضو شوید و سپس روی «✅ عضو شدم» بزنید."
)
JOIN_WARN = "⚠️ هنوز در همه کانال‌ها عضو نشده‌اید. لطفاً عضو شوید و دوباره روی «✅ عضو شدم» بزنید."

# ---------------------------------------------------------------- پشتیبانی
support_url: str | None = None


async def resolve_support_url(bot: Bot) -> None:
    """یوزرنیم ادمین را از .env یا از تلگرام پیدا می‌کند."""
    global support_url
    username = config.ADMIN_USERNAME
    if not username:
        try:
            chat = await bot.get_chat(config.ADMIN_ID)
            username = chat.username or ""
        except TelegramAPIError:
            username = ""
    support_url = f"https://t.me/{username}" if username else None


# ---------------------------------------------------------------- ارسال سفارش به ادمین
def order_card_text(order: dict, user: dict | None) -> str:
    username = f"@{esc(user['username'])}" if user and user.get("username") else "ندارد"
    kind = "🛒 خرید کانفیگ" if order["type"] == "config" else "💰 شارژ کیف پول"
    method = {"wallet": "💼 کیف پول", "reward": "🎁 جایزه دعوت (کانفیگ رایگان)"}.get(
        order["receipt_type"], "💳 کارت به کارت (رسید پیوست)")
    return (
        f"🧾 <b>سفارش جدید #{order['id']}</b>\n\n"
        f"👤 نام: {esc(user.get('first_name') if user else '-')}\n"
        f"🔖 یوزرنیم: {username}\n"
        f"🆔 آیدی: <code>{order['user_id']}</code>\n\n"
        f"{kind}\n"
        f"📋 پلن: {esc(order['plan_label'])}\n"
        f"💵 مبلغ: <b>{order['price']:,} تومان</b>\n"
        f"{method}\n"
        f"🕒 زمان: {to_iran_time(order['created_at'])}"
    )


async def send_order_to_admin(bot: Bot, order_id: int) -> bool:
    """کارت سفارش (با رسید و دکمه‌های تایید/رد) را فقط برای ادمین می‌فرستد."""
    order = await db.get_order(order_id)
    if not order:
        return False
    user = await db.get_user(order["user_id"])
    text = order_card_text(order, user)
    markup = kb.admin_order_kb(order_id)
    try:
        if order["receipt_type"] == "photo":
            msg = await bot.send_photo(config.ADMIN_ID, order["receipt_file_id"],
                                       caption=text, reply_markup=markup)
        elif order["receipt_type"] == "document":
            msg = await bot.send_document(config.ADMIN_ID, order["receipt_file_id"],
                                          caption=text, reply_markup=markup)
        else:
            msg = await bot.send_message(config.ADMIN_ID, text, reply_markup=markup)
    except TelegramAPIError as e:
        order_log.error("ارسال سفارش #%s به ادمین ناموفق بود: %s", order_id, e)
        return False
    await db.set_admin_msg(order_id, msg.message_id)
    return True


async def mark_admin_card(bot: Bot, order: dict, label: str) -> None:
    """دکمه‌های کارت سفارش را با وضعیت نهایی جایگزین می‌کند."""
    if not order.get("admin_msg_id"):
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=config.ADMIN_ID, message_id=order["admin_msg_id"],
            reply_markup=kb.admin_done_kb(label))
    except TelegramAPIError:
        pass
