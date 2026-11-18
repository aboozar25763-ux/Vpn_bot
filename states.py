"""
states.py — حالت‌های FSM
"""
from aiogram.fsm.state import State, StatesGroup


class PaymentStates(StatesGroup):
    waiting_amount = State()   # کاربر مبلغ شارژ را تایپ می‌کند
    waiting_receipt = State()  # کاربر عکس/فایل رسید را می‌فرستد


class AdminStates(StatesGroup):
    waiting_config = State()         # ادمین کانفیگ سفارش مشخصی را می‌فرستد
    waiting_reject_reason = State()  # ادمین علت رد را می‌نویسد
