"""
database.py — لایه دیتابیس SQLite (async با aiosqlite)
هر تابع یک اتصال کوتاه‌مدت باز می‌کند؛ بنابراین جایگزین کردن فایل دیتابیس (ریستور) امن است.
"""
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite

import config

log = logging.getLogger("db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    balance     INTEGER NOT NULL DEFAULT 0,
    referred_by INTEGER,
    joined_at   TEXT NOT NULL,
    free_configs INTEGER NOT NULL DEFAULT 0   -- تعداد کانفیگ رایگان ۱ گیگی (جایزه دعوت)
);
CREATE TABLE IF NOT EXISTS referral_rewards (
    invitee_id INTEGER PRIMARY KEY,   -- هر دعوت‌شده فقط یک‌بار جایزه می‌دهد (اولین خرید)
    inviter_id INTEGER NOT NULL,
    order_id   INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    plan_label      TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN ('normal','static_ip','topup')),
    duration        TEXT,
    price           INTEGER NOT NULL,
    type            TEXT NOT NULL CHECK (type IN ('config','topup')),
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    receipt_file_id TEXT,
    receipt_type    TEXT,            -- photo | document | wallet
    admin_msg_id    INTEGER,
    reject_reason   TEXT,
    created_at      TEXT NOT NULL,
    decided_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_user   ON orders(user_id, status);
CREATE INDEX IF NOT EXISTS idx_users_referer ON users(referred_by);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@asynccontextmanager
async def connect():
    db = await aiosqlite.connect(config.DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db() -> bool:
    """جدول‌ها را می‌سازد. اگر دیتابیس کاملاً جدید بود True برمی‌گرداند."""
    folder = os.path.dirname(config.DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    fresh = not os.path.exists(config.DB_PATH) or os.path.getsize(config.DB_PATH) == 0
    async with connect() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(SCHEMA)
        # مهاجرت: دیتابیس‌های قدیمی ستون free_configs را ندارند
        cur = await db.execute("PRAGMA table_info(users)")
        cols = {r["name"] for r in await cur.fetchall()}
        if "free_configs" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN free_configs INTEGER NOT NULL DEFAULT 0")
        await db.commit()
    return fresh


# ------------------------------------------------------------------ کاربران
async def upsert_user(user_id: int, username: str | None, first_name: str | None,
                      referred_by: int | None = None) -> bool:
    """کاربر را ثبت یا به‌روز می‌کند. اگر کاربر جدید بود True برمی‌گرداند."""
    async with connect() as db:
        if referred_by is not None:
            if referred_by == user_id:
                referred_by = None
            else:
                cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (referred_by,))
                if await cur.fetchone() is None:
                    referred_by = None
        cur = await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, balance, referred_by, joined_at) "
            "VALUES (?,?,?,0,?,?)",
            (user_id, username, first_name, referred_by, _now()),
        )
        created = cur.rowcount > 0
        if not created:
            await db.execute(
                "UPDATE users SET username=?, first_name=? WHERE user_id=?",
                (username, first_name, user_id),
            )
        await db.commit()
        return created


async def get_user(user_id: int) -> dict | None:
    async with connect() as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def count_invited(user_id: int) -> int:
    async with connect() as db:
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,))
        return (await cur.fetchone())[0]


async def count_referral_buyers(user_id: int) -> int:
    """تعداد دعوت‌شدگانی که حداقل یک پلن خریده‌اند."""
    async with connect() as db:
        cur = await db.execute("SELECT COUNT(*) FROM referral_rewards WHERE inviter_id=?", (user_id,))
        return (await cur.fetchone())[0]


async def grant_referral_reward(order_id: int) -> int | None:
    """
    اگر خریدار توسط کسی دعوت شده و این اولین خرید تاییدشده‌اش است،
    ۱ کانفیگ رایگان به دعوت‌کننده می‌دهد و آیدی او را برمی‌گرداند (وگرنه None).
    """
    async with connect() as db:
        cur = await db.execute(
            "SELECT o.user_id, u.referred_by FROM orders o JOIN users u ON u.user_id=o.user_id "
            "WHERE o.id=? AND o.type='config' AND o.price>0 AND o.receipt_type!='reward'", (order_id,))
        row = await cur.fetchone()
        if not row or not row["referred_by"]:
            return None
        cur = await db.execute(
            "INSERT OR IGNORE INTO referral_rewards (invitee_id, inviter_id, order_id, created_at) "
            "VALUES (?,?,?,?)", (row["user_id"], row["referred_by"], order_id, _now()))
        if cur.rowcount == 0:
            return None
        await db.execute("UPDATE users SET free_configs = free_configs + 1 WHERE user_id=?",
                         (row["referred_by"],))
        await db.commit()
        return row["referred_by"]


async def claim_free_config(user_id: int) -> bool:
    """یک کانفیگ رایگان را اتمیک مصرف می‌کند."""
    async with connect() as db:
        cur = await db.execute(
            "UPDATE users SET free_configs = free_configs - 1 WHERE user_id=? AND free_configs > 0",
            (user_id,))
        await db.commit()
        return cur.rowcount > 0


async def deduct_balance(user_id: int, amount: int) -> bool:
    """کسر اتمیک موجودی؛ اگر موجودی کافی نباشد False."""
    async with connect() as db:
        cur = await db.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?",
            (amount, user_id, amount),
        )
        await db.commit()
        return cur.rowcount > 0


# ------------------------------------------------------------------ سفارش‌ها
async def create_order(user_id: int, plan_label: str, category: str, duration: str, price: int,
                       order_type: str, receipt_file_id: str | None, receipt_type: str) -> int:
    async with connect() as db:
        cur = await db.execute(
            "INSERT INTO orders (user_id, plan_label, category, duration, price, type, status, "
            "receipt_file_id, receipt_type, created_at) VALUES (?,?,?,?,?,?,'pending',?,?,?)",
            (user_id, plan_label, category, duration, price, order_type,
             receipt_file_id, receipt_type, _now()),
        )
        await db.commit()
        return cur.lastrowid


async def get_order(order_id: int) -> dict | None:
    async with connect() as db:
        cur = await db.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def set_admin_msg(order_id: int, message_id: int) -> None:
    async with connect() as db:
        await db.execute("UPDATE orders SET admin_msg_id=? WHERE id=?", (message_id, order_id))
        await db.commit()


async def count_pending(user_id: int) -> int:
    async with connect() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id=? AND status='pending'", (user_id,))
        return (await cur.fetchone())[0]


async def list_pending(limit: int = 30) -> list[dict]:
    async with connect() as db:
        cur = await db.execute(
            "SELECT id, user_id, plan_label, price, type FROM orders "
            "WHERE status='pending' ORDER BY id LIMIT ?", (limit,))
        return [dict(r) for r in await cur.fetchall()]


async def approve_order(order_id: int) -> bool:
    """سفارش خرید کانفیگ را تایید می‌کند (فقط اگر هنوز pending باشد)."""
    async with connect() as db:
        cur = await db.execute(
            "UPDATE orders SET status='approved', decided_at=? WHERE id=? AND status='pending'",
            (_now(), order_id))
        await db.commit()
        return cur.rowcount > 0


async def approve_topup(order_id: int) -> int | None:
    """
    سفارش شارژ را در یک تراکنش تایید و موجودی را زیاد می‌کند.
    موجودی جدید را برمی‌گرداند؛ اگر سفارش قبلاً بررسی شده بود None.
    """
    async with connect() as db:
        cur = await db.execute(
            "UPDATE orders SET status='approved', decided_at=? "
            "WHERE id=? AND status='pending' AND type='topup'", (_now(), order_id))
        if cur.rowcount == 0:
            await db.rollback()
            return None
        cur = await db.execute("SELECT user_id, price FROM orders WHERE id=?", (order_id,))
        order = await cur.fetchone()
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?",
                         (order["price"], order["user_id"]))
        cur = await db.execute("SELECT balance FROM users WHERE user_id=?", (order["user_id"],))
        balance = (await cur.fetchone())["balance"]
        await db.commit()
        return balance


async def reject_order(order_id: int, reason: str | None) -> bool:
    """
    سفارش را رد می‌کند. اگر سفارش با کیف پول پرداخت شده بود، مبلغ برگردانده می‌شود.
    """
    async with connect() as db:
        cur = await db.execute(
            "UPDATE orders SET status='rejected', reject_reason=?, decided_at=? "
            "WHERE id=? AND status='pending'", (reason, _now(), order_id))
        if cur.rowcount == 0:
            await db.rollback()
            return False
        cur = await db.execute("SELECT user_id, price, receipt_type, type FROM orders WHERE id=?",
                               (order_id,))
        order = await cur.fetchone()
        if order["receipt_type"] == "wallet" and order["type"] == "config":
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?",
                             (order["price"], order["user_id"]))
        elif order["receipt_type"] == "reward":  # کانفیگ رایگان رد شد → حق او برمی‌گردد
            await db.execute("UPDATE users SET free_configs = free_configs + 1 WHERE user_id=?",
                             (order["user_id"],))
        await db.commit()
        return True


async def stats() -> dict:
    async with connect() as db:
        out = {}
        cur = await db.execute("SELECT COUNT(*) FROM users")
        out["users"] = (await cur.fetchone())[0]
        cur = await db.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
        out["orders"] = {r[0]: r[1] for r in await cur.fetchall()}
        cur = await db.execute(
            "SELECT COALESCE(SUM(price),0) FROM orders WHERE status='approved' AND type='config'")
        out["sales"] = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COALESCE(SUM(price),0) FROM orders WHERE status='approved' AND type='topup'")
        out["topups"] = (await cur.fetchone())[0]
        return out


async def make_snapshot(path: str) -> None:
    """یک کپی کاملاً سازگار از دیتابیس در مسیر path می‌سازد (برای بکاپ)."""
    if os.path.exists(path):
        os.remove(path)
    async with connect() as db:
        await db.execute("VACUUM INTO ?", (path,))
