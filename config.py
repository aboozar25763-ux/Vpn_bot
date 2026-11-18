"""
config.py — تنظیمات کلی ربات
هر مقدار از فایل .env (یا Variables در Railway) خوانده می‌شود.
"""
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # اگر python-dotenv نصب نبود، فقط از متغیرهای محیطی استفاده می‌شود
    pass


def _int(name: str, default: int) -> int:
    """خواندن یک عدد صحیح از محیط، با مقدار پیش‌فرض."""
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- پایه
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID: int = _int("ADMIN_ID", 7125276979)
# اگر ادمین یوزرنیم عمومی دارد اینجا (بدون @) بنویسید؛ در غیر این صورت ربات خودش تلاش می‌کند پیدا کند.
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "").strip().lstrip("@")

# ---------------------------------------------------------------- کانال‌های اجباری
CHANNEL_1: str = os.getenv("CHANNEL_1", "https://t.me/KanfingAF").strip()
CHANNEL_2: str = os.getenv("CHANNEL_2", "https://t.me/DollarChiFA").strip()
CHANNELS: list[str] = [CHANNEL_1, CHANNEL_2]

# ---------------------------------------------------------------- پرداخت
CARD_NUMBER: str = os.getenv("CARD_NUMBER", "6219861880185136").strip()
CARD_HOLDER: str = os.getenv("CARD_HOLDER", "حکیمه زکریایی شورکایی").strip()
MIN_TOPUP: int = _int("MIN_TOPUP", 10_000)  # حداقل مبلغ شارژ (تومان)
MAX_TOPUP: int = _int("MAX_TOPUP", 100_000_000)  # حداکثر مبلغ شارژ (تومان)
MAX_PENDING_ORDERS: int = _int("MAX_PENDING_ORDERS", 5)  # سقف سفارش‌های در انتظار هر کاربر (ضد اسپم)

# ---------------------------------------------------------------- دیتابیس و بکاپ
# اگر پوشه /data وجود داشته باشد (Volume در Railway) از آن استفاده می‌شود.
_default_dir = "/data" if os.path.isdir("/data") else "data"
DB_PATH: str = os.getenv("DB_PATH") or os.path.join(_default_dir, "bot.db")
BACKUP_HOURS: float = _float("BACKUP_HOURS", 3)  # هر چند ساعت یک بکاپ برای ادمین فرستاده شود
