# -*- coding: utf-8 -*-
"""الإعدادات المركزية للبوت — كل شيء قابل للضبط من ملف .env"""
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _p(*parts) -> str:
    return os.path.join(BASE_DIR, *parts)


def _env_int(key: str, default: int) -> int:
    try:
        return int(str(os.getenv(key, default)).strip())
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(str(os.getenv(key, default)).strip())
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on', 'y')


# ═══════════════════════════ الأساسيات ═══════════════════════════
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID = _env_int("ADMIN_ID", 0)
# أدمن إضافيون: ADMIN_IDS=111,222
ADMIN_IDS = {ADMIN_ID} | {
    int(x) for x in (os.getenv("ADMIN_IDS", "") or "").replace(" ", "").split(",") if x.isdigit()
}
ADMIN_IDS.discard(0)

ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "@Saeed_karout1")

# ═══════════════════════════ المسارات ═══════════════════════════
# قابلة للضبط من البيئة — ضروري داخل الحاويات لتوجيه البيانات إلى قرص دائم.
def _path_env(key, *default_parts):
    val = (os.getenv(key) or '').strip()
    if not val:
        return _p(*default_parts)
    return val if os.path.isabs(val) else _p(val)


DATA_DIR = _path_env("DATA_DIR", 'data') if os.getenv("DATA_DIR") else None

DOWNLOAD_DIR = _path_env("DOWNLOAD_DIR", 'downloads')
COOKIES_DIR = _path_env("COOKIES_DIR", 'cookies')
DB_PATH = _path_env("DB_PATH", 'database', 'bot.db')
LOG_PATH = _path_env("LOG_PATH", 'logs', 'bot.log')
TOOLS_DIR = _path_env("TOOLS_DIR", 'tools')

# DATA_DIR يجمع كل ما يجب أن يبقى بعد إعادة النشر في مكان واحد
if DATA_DIR:
    if not os.getenv("DB_PATH"):
        DB_PATH = os.path.join(DATA_DIR, 'bot.db')
    if not os.getenv("COOKIES_DIR"):
        COOKIES_DIR = os.path.join(DATA_DIR, 'cookies')

# منفذ فحص الصحة — تطلبه بعض منصات الاستضافة لتعتبر الخدمة حيّة
PORT = _env_int("PORT", 0)

for _d in (DOWNLOAD_DIR, COOKIES_DIR, os.path.dirname(DB_PATH), os.path.dirname(LOG_PATH), TOOLS_DIR):
    os.makedirs(_d, exist_ok=True)

# ═══════════════════════════ حدود تيليجرام ═══════════════════════════
# Bot API الرسمي يسمح برفع 50 ميغا فقط.
# إن شغّلت Local Bot API Server تصبح 2000 ميغا — عندها اضبط:
#   LOCAL_BOT_API=http://127.0.0.1:8081/bot
LOCAL_BOT_API = (os.getenv("LOCAL_BOT_API", "") or "").strip()
USING_LOCAL_API = bool(LOCAL_BOT_API)

TG_UPLOAD_LIMIT_MB = _env_int("TG_UPLOAD_LIMIT_MB", 2000 if USING_LOCAL_API else 50)
TG_UPLOAD_LIMIT = TG_UPLOAD_LIMIT_MB * 1024 * 1024

# ═══════════════════════════ التنزيل ═══════════════════════════
MAX_DOWNLOAD_SECONDS = _env_int("MAX_DOWNLOAD_SECONDS", 20 * 60)
PROBE_TIMEOUT = _env_int("PROBE_TIMEOUT", 60)
MAX_CONCURRENT_DOWNLOADS = _env_int("MAX_CONCURRENT_DOWNLOADS", 4)
MAX_PER_USER_CONCURRENT = _env_int("MAX_PER_USER_CONCURRENT", 1)
ORPHAN_FILE_AGE = _env_int("ORPHAN_FILE_AGE", 3600)
PROGRESS_EDIT_INTERVAL = _env_float("PROGRESS_EDIT_INTERVAL", 3.5)

# سرعة السيرفر التقديرية (ميغابت/ثانية) — تُستخدم لتقدير زمن التنزيل
# يتم تحديثها تلقائياً من التنزيلات الفعلية
DEFAULT_SPEED_MBPS = _env_float("DEFAULT_SPEED_MBPS", 25.0)

ENABLE_GALLERY_DL = _env_bool("ENABLE_GALLERY_DL", True)
ENABLE_INSTALOADER = _env_bool("ENABLE_INSTALOADER", True)
ENABLE_PLAYLISTS = _env_bool("ENABLE_PLAYLISTS", False)

PROXY = (os.getenv("PROXY", "") or "").strip()

# ═══════════════════════════ الدفع ═══════════════════════════
SHAMCASH_NUMBER = os.getenv("SHAMCASH_NUMBER", "")
SHAMCASH_QR_PATH = os.getenv("SHAMCASH_QR_PATH", "qr.jpg")
if SHAMCASH_QR_PATH and not os.path.isabs(SHAMCASH_QR_PATH):
    SHAMCASH_QR_PATH = _p(SHAMCASH_QR_PATH)

SYRIATEL_NUMBER = os.getenv("SYRIATEL_NUMBER", "")
SYRIATEL_QR_PATH = os.getenv("SYRIATEL_QR_PATH", "")
if SYRIATEL_QR_PATH and not os.path.isabs(SYRIATEL_QR_PATH):
    SYRIATEL_QR_PATH = _p(SYRIATEL_QR_PATH)

# طرق الدفع المعروضة للمستخدم — يظهر فقط ما له رقم مضبوط
PAYMENT_METHODS = {
    'sham': {
        'name': 'شام كاش', 'emoji': '🟣',
        'number': SHAMCASH_NUMBER,
        'qr': SHAMCASH_QR_PATH,
        'howto': 'افتح تطبيق شام كاش ← تحويل ← الصق الرقم ← أدخل المبلغ',
    },
    'syriatel': {
        'name': 'سيرياتيل كاش', 'emoji': '🔴',
        'number': SYRIATEL_NUMBER,
        'qr': SYRIATEL_QR_PATH,
        'howto': 'اطلب #666# أو افتح تطبيق سيرياتيل كاش ← تحويل ← أدخل الرقم والمبلغ',
    },
}


def active_payment_methods():
    """الطرق المتاحة فعلاً — نخفي ما لم يُضبط رقمه بدل عرض حقل فارغ."""
    return {k: v for k, v in PAYMENT_METHODS.items() if (v.get('number') or '').strip()}


PAYMENT_INFO = os.getenv("PAYMENT_INFO", "")

# ═══════════════════════════ النمو ═══════════════════════════
# الإحالة: كم يوماً يربح المُحيل والمَدعوّ عند أول تفعيل
REFERRAL_DAYS = _env_int("REFERRAL_DAYS", 3)
REFERRAL_TIER = os.getenv("REFERRAL_TIER", "pro")

# تجربة مجانية لمرة واحدة
TRIAL_ENABLED = _env_bool("TRIAL_ENABLED", True)
TRIAL_TIER = os.getenv("TRIAL_TIER", "vip")
TRIAL_HOURS = _env_int("TRIAL_HOURS", 24)

# ═══════════════════════════ الخطط ═══════════════════════════
# max_height=0 يعني بلا حد   |   daily_limit=0 يعني بلا حد
PLANS = {
    'free': {
        'name': 'مجاني', 'emoji': '🆓', 'price': 0, 'days': 0,
        'max_height': _env_int("FREE_MAX_HEIGHT", 480),
        'daily_limit': _env_int("FREE_DAILY_LIMIT", 5), 'mp3': True,
        'max_file_mb': 200, 'max_duration': 20 * 60,
        'playlist': False, 'priority': 0, 'batch': False,
    },
    'pro': {
        'name': 'برو', 'emoji': '💼', 'price': 5, 'days': 30,
        'max_height': 1080, 'daily_limit': 40, 'mp3': True,
        'max_file_mb': 1000, 'max_duration': 3 * 60 * 60,
        'playlist': True, 'priority': 1, 'batch': True,
    },
    'vip': {
        'name': 'VIP', 'emoji': '👑', 'price': 10, 'days': 30,
        'max_height': 0, 'daily_limit': 0, 'mp3': True,
        'max_file_mb': 0, 'max_duration': 0,
        'playlist': True, 'priority': 2, 'batch': True,
    },
}
TIER_ORDER = ['free', 'pro', 'vip']


def plan_of(tier: str) -> dict:
    return PLANS.get(tier, PLANS['free'])
