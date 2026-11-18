"""
keyboards.py — همه دکمه‌ها شیشه‌ای (Inline) هستند.
"""
from aiogram.types import CopyTextButton, InlineKeyboardButton as Btn, InlineKeyboardMarkup

import config
import plans


def _kb(rows: list[list[Btn]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_btn(cb: str = "menu:main", text: str = "🔙 بازگشت") -> list[Btn]:
    return [Btn(text=text, callback_data=cb)]


def main_menu() -> InlineKeyboardMarkup:
    return _kb([
        [Btn(text="🛒 ساخت کانفیگ جدید", callback_data="menu:buy")],
        [Btn(text="💰 کیف پول / شارژ حساب", callback_data="menu:wallet")],
        [Btn(text="🎁 دعوت از دوستان", callback_data="menu:ref")],
        [Btn(text="🆘 پشتیبانی", callback_data="menu:support")],
    ])


def join_kb(missing: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[Btn(text=f"📢 عضویت در کانال {n}", url=url)] for n, url in missing]
    rows.append([Btn(text="✅ عضو شدم", callback_data="check_sub")])
    return _kb(rows)


def category_kb() -> InlineKeyboardMarkup:
    return _kb([
        [Btn(text="📦 پلن‌های معمولی", callback_data="cat:normal")],
        [Btn(text="🔒 پلن آی‌پی ثابت 🇩🇪", callback_data="cat:static")],
        back_btn("menu:main"),
    ])


def durations_kb() -> InlineKeyboardMarkup:
    rows = [[Btn(text=f"⏱ {g['title']}", callback_data=f"dur:{key}")]
            for key, g in plans.NORMAL_PLANS.items()]
    rows.append(back_btn("menu:buy"))
    return _kb(rows)


def items_kb(duration_key: str) -> InlineKeyboardMarkup:
    group = plans.NORMAL_PLANS[duration_key]
    rows, row = [], []
    for value, price in group["items"].items():
        name = f"{value} گیگ" if group["kind"] == "volume" else f"{value} روزه"
        row.append(Btn(text=f"{name} — {price:,} تومان", callback_data=f"plan:n:{duration_key}:{value}"))
        if len(row) == 1:  # هر پلن یک ردیف، تا قیمت‌ها کامل دیده شوند
            rows.append(row)
            row = []
    rows.append(back_btn("cat:normal"))
    return _kb(rows)


def static_kb() -> InlineKeyboardMarkup:
    rows = [[Btn(text=f"{gb} گیگ نامحدود — {price:,} تومان", callback_data=f"plan:s:{gb}")]
            for gb, price in plans.STATIC_PLANS.items()]
    rows.append(back_btn("menu:buy"))
    return _kb(rows)


def payment_kb(code: str, price: int, balance: int = 0) -> InlineKeyboardMarkup:
    rows = [
        [Btn(text="🔢 کپی شماره کارت", copy_text=CopyTextButton(text=config.CARD_NUMBER))],
        [Btn(text="💰 کپی مبلغ", copy_text=CopyTextButton(text=str(price)))],
    ]
    if balance >= price > 0:
        rows.append([Btn(text=f"💼 پرداخت از کیف پول ({balance:,} تومان)", callback_data=f"wpay:{code}")])
    rows.append([Btn(text="📤 ارسال رسید", callback_data=f"rcpt:{code}")])
    rows.append(back_btn("menu:main"))
    return _kb(rows)


def wallet_kb() -> InlineKeyboardMarkup:
    return _kb([
        [Btn(text="➕ شارژ حساب", callback_data="topup:start")],
        back_btn("menu:main"),
    ])


def only_back(cb: str = "menu:main") -> InlineKeyboardMarkup:
    return _kb([back_btn(cb)])


def referral_kb(share_url: str, free_configs: int = 0) -> InlineKeyboardMarkup:
    rows = []
    if free_configs > 0:
        rows.append([Btn(text=f"🎁 دریافت کانفیگ ۱ گیگ رایگان ({free_configs})", callback_data="ref:claim")])
    rows.append([Btn(text="📤 اشتراک‌گذاری لینک", url=share_url)])
    rows.append(back_btn("menu:main"))
    return _kb(rows)


def support_kb(url: str | None) -> InlineKeyboardMarkup:
    rows = []
    if url:
        rows.append([Btn(text="🆘 ارتباط با پشتیبانی", url=url)])
    rows.append(back_btn("menu:main"))
    return _kb(rows)


# ---------------------------------------------------------------- فقط برای ادمین
def admin_order_kb(order_id: int) -> InlineKeyboardMarkup:
    return _kb([[
        Btn(text="✅ تایید", callback_data=f"adm:ok:{order_id}"),
        Btn(text="❌ رد", callback_data=f"adm:no:{order_id}"),
    ]])


def admin_done_kb(text: str) -> InlineKeyboardMarkup:
    """بعد از تصمیم‌گیری، دکمه‌ها با یک برچسب غیرفعال جایگزین می‌شوند."""
    return _kb([[Btn(text=text, callback_data="noop")]])
