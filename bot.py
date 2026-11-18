"""
bot.py — نقطه شروع ربات.   اجرا:  python bot.py
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage

import backup
import config
import database as db
import services
from handlers import get_routers
from middlewares import MembershipMiddleware, ThrottleMiddleware

log = logging.getLogger("bot")


async def startup_checks(bot: Bot) -> None:
    """بررسی تنظیمات و اطلاع‌رسانی مشکلات به ادمین."""
    problems = []
    me = await bot.me()
    for number, url in enumerate(config.CHANNELS, start=1):
        chat_id = services.channel_chat_id(url)
        try:
            member = await bot.get_chat_member(chat_id, me.id)
            if member.status not in ("administrator", "creator"):
                problems.append(f"ربات در کانال {number} ({chat_id}) ادمین نیست.")
        except TelegramAPIError:
            problems.append(f"دسترسی به کانال {number} ({chat_id}) ممکن نیست؛ ربات را ادمین کانال کنید.")
    if problems:
        text = "⚠️ <b>هشدار تنظیمات</b>\n\n" + "\n".join(f"• {p}" for p in problems) + \
               "\n\nتا زمان رفع، بررسی عضویت درست کار نمی‌کند و کاربران نمی‌توانند وارد منو شوند."
        log.warning(text)
        try:
            await bot.send_message(config.ADMIN_ID, text)
        except TelegramAPIError:
            pass


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    if not config.BOT_TOKEN:
        log.error("BOT_TOKEN تنظیم نشده است. آن را در .env یا Variables بگذارید.")
        sys.exit(1)

    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.outer_middleware(ThrottleMiddleware())
    dp.callback_query.outer_middleware(ThrottleMiddleware())
    dp.callback_query.outer_middleware(MembershipMiddleware())
    for router in get_routers():
        dp.include_router(router)

    # --- دیتابیس (و ریستور خودکار اگر هاست دیتابیس را پاک کرده بود)
    fresh = await db.init_db()
    if fresh:
        log.warning("دیتابیس جدید ساخته شد؛ تلاش برای بازیابی از آخرین بکاپ پین‌شده...")
        if await backup.try_auto_restore(bot):
            await db.init_db()
            stats = await db.stats()
            log.info("دیتابیس از بکاپ بازیابی شد.")
            try:
                await bot.send_message(
                    config.ADMIN_ID,
                    f"♻️ دیتابیس خودکار از آخرین بکاپ بازیابی شد.\n👥 کاربران: {stats['users']}")
            except TelegramAPIError:
                pass
        else:
            try:
                await bot.send_message(
                    config.ADMIN_ID,
                    "ℹ️ ربات با دیتابیس خالی شروع شد.\n"
                    "اگر بکاپ قدیمی دارید، فایل .db را با کپشن /restore برای من بفرستید.")
            except TelegramAPIError:
                pass

    await services.resolve_support_url(bot)
    await startup_checks(bot)
    backup_task = asyncio.create_task(backup.backup_loop(bot))

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("ربات شروع به کار کرد.")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        backup_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
