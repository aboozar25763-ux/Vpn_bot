"""
handlers — ترتیب روترها مهم است: ادمین، شروع، فروشگاه، پرداخت، و در آخر fallback
"""
from aiogram import Router

from . import admin, fallback, payment, shop, start


def get_routers() -> list[Router]:
    return [admin.router, start.router, shop.router, payment.router, fallback.router]
