"""
backup.py — بکاپ خودکار دیتابیس برای ادمین در تلگرام + ریستور خودکار

چرا؟ روی هاست‌های رایگان ممکن است فایل دیتابیس با هر دیپلوی/ری‌استارت پاک شود.
روش کار:
  ۱) ربات هر BACKUP_HOURS ساعت (و ۱۵ ثانیه پس از هر تغییر مهم) یک نسخه از دیتابیس برای ادمین می‌فرستد
     و آن را در چت ادمین «پین» می‌کند.
  ۲) اگر ربات با دیتابیس خالی بالا بیاید، آخرین فایل پین‌شده را خودش می‌خواند و بازیابی می‌کند.
  ۳) دستی: ادمین فایل .db را با کپشن /restore برای ربات بفرستد.
"""
import asyncio
import hashlib
import logging
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

import config
import database as db
from utils import IRAN_TZ

log = logging.getLogger("backup")

_last_hash: str | None = None
_pending = False
_lock = asyncio.Lock()


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def make_backup(bot: Bot, force: bool = False) -> bool:
    """یک بکاپ می‌سازد و برای ادمین می‌فرستد. اگر چیزی تغییر نکرده باشد (و force نباشد) ارسال نمی‌شود."""
    global _last_hash
    async with _lock:
        stats = await db.stats()
        if stats["users"] == 0 and not force:
            return False  # دیتابیس خالی هرگز جای بکاپ سالم را نمی‌گیرد
        tmp_dir = tempfile.mkdtemp(prefix="botbackup_")
        stamp = datetime.now(IRAN_TZ).strftime("%Y%m%d_%H%M")
        path = os.path.join(tmp_dir, f"bot_backup_{stamp}.db")
        try:
            await db.make_snapshot(path)
            digest = _file_hash(path)
            if digest == _last_hash and not force:
                return False
            # پین قبلی را بخوانیم تا بعد از پین جدید برداشته شود
            old_pin_id = None
            try:
                chat = await bot.get_chat(config.ADMIN_ID)
                if chat.pinned_message:
                    old_pin_id = chat.pinned_message.message_id
            except TelegramAPIError:
                pass
            msg = await bot.send_document(
                config.ADMIN_ID, FSInputFile(path),
                caption=f"💾 بکاپ دیتابیس — {stamp}\n"
                        f"👥 کاربران: {stats['users']}\n"
                        "این فایل را نگه دارید و پاک نکنید.",
                disable_notification=True,
            )
            _last_hash = digest
            try:
                await bot.pin_chat_message(config.ADMIN_ID, msg.message_id, disable_notification=True)
                if old_pin_id:
                    await bot.unpin_chat_message(config.ADMIN_ID, message_id=old_pin_id)
            except TelegramAPIError as e:
                log.warning("پین کردن بکاپ ممکن نشد: %s", e)
            log.info("بکاپ ارسال شد (%s)", path)
            return True
        except Exception:
            log.exception("ساخت/ارسال بکاپ ناموفق بود")
            return False
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def schedule_backup(bot: Bot, delay: int = 15) -> None:
    """بعد از تغییرات مهم (تایید سفارش و...) با کمی تاخیر یک بکاپ می‌گیرد؛ درخواست‌های پشت‌سرهم یکی می‌شوند."""
    global _pending
    if _pending:
        return
    _pending = True

    async def _job():
        global _pending
        try:
            await asyncio.sleep(delay)
            await make_backup(bot)
        finally:
            _pending = False

    asyncio.create_task(_job())


async def backup_loop(bot: Bot) -> None:
    """بکاپ دوره‌ای."""
    interval = max(config.BACKUP_HOURS, 0.05) * 3600
    while True:
        await asyncio.sleep(interval)
        await make_backup(bot)


# ------------------------------------------------------------------ ریستور
def _validate_db(path: str) -> bool:
    """بررسی می‌کند فایل یک دیتابیس سالم از همین ربات باشد."""
    try:
        con = sqlite3.connect(path)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return {"users", "orders"} <= tables
        finally:
            con.close()
    except sqlite3.Error:
        return False


def restore_from_file(path: str) -> bool:
    """فایل بکاپ را جایگزین دیتابیس فعلی می‌کند (بعدش باید init_db دوباره صدا زده شود)."""
    if not _validate_db(path):
        return False
    folder = os.path.dirname(config.DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(config.DB_PATH + suffix)
        except FileNotFoundError:
            pass
    shutil.copyfile(path, config.DB_PATH)
    return True


async def try_auto_restore(bot: Bot) -> bool:
    """اگر دیتابیس خالی بود، آخرین بکاپ پین‌شده در چت ادمین را بازیابی می‌کند."""
    try:
        chat = await bot.get_chat(config.ADMIN_ID)
        pinned = chat.pinned_message
        if not pinned or not pinned.document:
            return False
        name = pinned.document.file_name or ""
        if not name.endswith(".db"):
            return False
        tmp_dir = tempfile.mkdtemp(prefix="botrestore_")
        try:
            path = os.path.join(tmp_dir, "restore.db")
            await bot.download(pinned.document, destination=path)
            return restore_from_file(path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        log.exception("ریستور خودکار ناموفق بود")
        return False
