# -*- coding: utf-8 -*-
"""طبقة قاعدة البيانات — آمنة للخيوط (thread-safe) مع ترحيل تلقائي للمخطط."""
import os
import sqlite3
import threading
import datetime
from contextlib import contextmanager

from config import DB_PATH

_lock = threading.RLock()
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

db = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA busy_timeout=30000")


@contextmanager
def tx():
    """معاملة واحدة محمية بقفل — تمنع تضارب الخيوط."""
    with _lock:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


def _q(sql, args=()):
    with _lock:
        return db.execute(sql, args).fetchall()


def _q1(sql, args=()):
    with _lock:
        return db.execute(sql, args).fetchone()


def _x(sql, args=()):
    with tx() as c:
        return c.execute(sql, args)


# ═══════════════════════════ المخطط ═══════════════════════════
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id           INTEGER PRIMARY KEY,
    username          TEXT,
    first_name        TEXT,
    tier              TEXT    DEFAULT 'free',
    expires_at        TEXT,
    downloads_today   INTEGER DEFAULT 0,
    last_download_date TEXT,
    total_downloads   INTEGER DEFAULT 0,
    total_bytes       INTEGER DEFAULT 0,
    banned            INTEGER DEFAULT 0,
    lang              TEXT    DEFAULT 'ar',
    prefer_quality    TEXT,
    joined_at         TEXT,
    last_seen         TEXT,
    referred_by       INTEGER,
    trial_used        INTEGER DEFAULT 0,
    referral_rewarded INTEGER DEFAULT 0,
    referral_count    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER,
    username      TEXT,
    plan          TEXT,
    days          INTEGER DEFAULT 30,
    amount        REAL    DEFAULT 0,
    proof_file_id TEXT,
    method        TEXT,
    status        TEXT    DEFAULT 'pending',
    created_at    TEXT,
    handled_at    TEXT,
    handled_by    INTEGER
);

CREATE TABLE IF NOT EXISTS downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    platform    TEXT,
    url         TEXT,
    title       TEXT,
    quality     TEXT,
    kind        TEXT,
    size_bytes  INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    engine      TEXT,
    ok          INTEGER DEFAULT 1,
    error       TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    file_id    TEXT,
    kind       TEXT,
    title      TEXT,
    size_bytes INTEGER DEFAULT 0,
    hits       INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_dl_user  ON downloads(user_id);
CREATE INDEX IF NOT EXISTS idx_dl_date  ON downloads(created_at);
CREATE INDEX IF NOT EXISTS idx_pay_stat ON payments(status);
CREATE INDEX IF NOT EXISTS idx_usr_exp  ON users(expires_at);
"""

# أعمدة يجب أن توجد — تُضاف تلقائياً على القواعد القديمة
MIGRATIONS = {
    'users': {
        'first_name': "TEXT", 'expires_at': "TEXT", 'total_downloads': "INTEGER DEFAULT 0",
        'total_bytes': "INTEGER DEFAULT 0", 'banned': "INTEGER DEFAULT 0",
        'lang': "TEXT DEFAULT 'ar'", 'prefer_quality': "TEXT", 'joined_at': "TEXT",
        'last_seen': "TEXT", 'referred_by': "INTEGER", 'downloads_today': "INTEGER DEFAULT 0",
        'last_download_date': "TEXT", 'tier': "TEXT DEFAULT 'free'",
        'trial_used': "INTEGER DEFAULT 0", 'referral_rewarded': "INTEGER DEFAULT 0",
        'referral_count': "INTEGER DEFAULT 0",
    },
    'payments': {
        'days': "INTEGER DEFAULT 30", 'amount': "REAL DEFAULT 0", 'created_at': "TEXT",
        'handled_at': "TEXT", 'handled_by': "INTEGER", 'method': "TEXT",
    },
}


def _columns(table):
    return {r[1] for r in db.execute("PRAGMA table_info(" + table + ")")}


def init_db():
    with tx() as c:
        c.executescript(SCHEMA)

        for table, cols in MIGRATIONS.items():
            existing = _columns(table)
            if not existing:
                continue
            for col, decl in cols.items():
                if col not in existing:
                    c.execute("ALTER TABLE {} ADD COLUMN {} {}".format(table, col, decl))

        # ── ترحيل الخطأ القديم ──
        # كان هناك عمودان: expiry و expires_at. الأدمن يكتب في expires_at
        # بينما مدقق الانتهاء يقرأ expiry ⇒ الاشتراكات لم تكن تنتهي أبداً.
        if 'expiry' in _columns('users'):
            c.execute("UPDATE users SET expires_at = expiry "
                      "WHERE (expires_at IS NULL OR expires_at = '') "
                      "AND expiry IS NOT NULL AND expiry != ''")

        c.execute("UPDATE users SET tier='free' "
                  "WHERE tier IS NULL OR tier NOT IN ('free','pro','vip')")


init_db()


def now_iso():
    return datetime.datetime.now().isoformat(timespec='seconds')


def today_iso():
    return datetime.date.today().isoformat()


# ═══════════════════════════ المستخدمون ═══════════════════════════
def add_user(user_id, username=None, first_name=None, referred_by=None):
    with tx() as c:
        c.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at, referred_by) "
            "VALUES (?,?,?,?,?)",
            (user_id, username, first_name, now_iso(), referred_by))
        c.execute(
            "UPDATE users SET last_seen=?, username=COALESCE(?, username), "
            "first_name=COALESCE(?, first_name) WHERE user_id=?",
            (now_iso(), username, first_name, user_id))


def get_user(user_id):
    row = _q1("SELECT * FROM users WHERE user_id=?", (user_id,))
    return dict(row) if row else None


def ensure_user(user_id):
    u = get_user(user_id)
    if not u:
        add_user(user_id)
        u = get_user(user_id)
    return u


def set_tier(user_id, tier, expires_at):
    add_user(user_id)
    if isinstance(expires_at, datetime.datetime):
        expires_at = expires_at.isoformat(timespec='seconds')
    elif isinstance(expires_at, datetime.date):
        expires_at = expires_at.isoformat()
    _x("UPDATE users SET tier=?, expires_at=? WHERE user_id=?", (tier, expires_at, user_id))


def set_banned(user_id, banned):
    add_user(user_id)
    _x("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id))


def is_banned(user_id):
    r = _q1("SELECT banned FROM users WHERE user_id=?", (user_id,))
    return bool(r and r['banned'])


def set_pref_quality(user_id, q):
    _x("UPDATE users SET prefer_quality=? WHERE user_id=?", (q, user_id))


def all_user_ids():
    return [r['user_id'] for r in _q("SELECT user_id FROM users WHERE banned=0")]


# ═══════════════════════════ العدّ اليومي ═══════════════════════════
def reset_if_new_day(user_id):
    """يصفّر العدّاد إن تغيّر اليوم. يُستدعى قبل أي قراءة للعدّاد.

    الخطأ القديم: كان التصفير يحدث داخل increment فقط، فالمستخدم الذي بلغ
    حدّه أمس يبقى محجوباً للأبد لأن الفحص يسبق التصفير ولا يصل إليه.
    """
    today = today_iso()
    with tx() as c:
        c.execute(
            "UPDATE users SET downloads_today=0, last_download_date=? "
            "WHERE user_id=? AND (last_download_date IS NULL OR last_download_date != ?)",
            (today, user_id, today))


def downloads_today(user_id):
    reset_if_new_day(user_id)
    r = _q1("SELECT downloads_today FROM users WHERE user_id=?", (user_id,))
    return int(r['downloads_today'] or 0) if r else 0


def increment_download(user_id, size_bytes=0):
    """يُستدعى فقط بعد نجاح التنزيل — لا نحرق حصة المستخدم على محاولة فاشلة."""
    reset_if_new_day(user_id)
    _x("UPDATE users SET downloads_today=downloads_today+1, "
       "total_downloads=total_downloads+1, total_bytes=total_bytes+? WHERE user_id=?",
       (int(size_bytes or 0), user_id))


# ═══════════════════════════ سجل التنزيلات ═══════════════════════════
def log_download(user_id, platform, url, title, quality, kind,
                 size_bytes=0, duration_ms=0, engine='', ok=True, error=None):
    _x("INSERT INTO downloads (user_id, platform, url, title, quality, kind, size_bytes,"
       " duration_ms, engine, ok, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (user_id, platform, (url or '')[:500], (title or '')[:300], quality, kind,
        int(size_bytes or 0), int(duration_ms or 0), engine, 1 if ok else 0,
        (str(error)[:400] if error else None), now_iso()))


def recent_speed_bps(limit=25):
    """السرعة الفعلية المقاسة من آخر التنزيلات الناجحة (بايت/ثانية).

    نستخدم الوسيط لا المتوسط — أمتن ضد القيم الشاذة.
    """
    rows = _q("SELECT size_bytes, duration_ms FROM downloads "
              "WHERE ok=1 AND size_bytes > 1000000 AND duration_ms > 500 "
              "ORDER BY id DESC LIMIT ?", (limit,))
    samples = sorted(r['size_bytes'] / (r['duration_ms'] / 1000.0) for r in rows)
    if not samples:
        return None
    return samples[len(samples) // 2]


# ═══════════════════════════ الكاش (file_id) ═══════════════════════════
def cache_get(key):
    row = _q1("SELECT * FROM cache WHERE key=?", (key,))
    if row:
        _x("UPDATE cache SET hits=hits+1 WHERE key=?", (key,))
        return dict(row)
    return None


def cache_put(key, file_id, kind, title, size_bytes):
    _x("INSERT OR REPLACE INTO cache (key, file_id, kind, title, size_bytes, hits, created_at) "
       "VALUES (?,?,?,?,?,COALESCE((SELECT hits FROM cache WHERE key=?),0),?)",
       (key, file_id, kind, (title or '')[:300], int(size_bytes or 0), key, now_iso()))


def cache_clear():
    _x("DELETE FROM cache")


# ═══════════════════════════ المدفوعات ═══════════════════════════
def create_payment(user_id, username, plan, proof_file_id, days=30, amount=0, method=None):
    with tx() as c:
        cur = c.execute(
            "INSERT INTO payments (user_id, username, plan, days, amount, proof_file_id,"
            " method, status, created_at) VALUES (?,?,?,?,?,?,?,'pending',?)",
            (user_id, username, plan, days, amount, proof_file_id, method, now_iso()))
        return cur.lastrowid


def get_payment(pid):
    row = _q1("SELECT * FROM payments WHERE id=?", (pid,))
    return dict(row) if row else None


def update_payment_status(payment_id, status, handled_by=None):
    """يعيد True فقط إن كان الطلب معلّقاً — يمنع التفعيل المزدوج بضغطتين."""
    with tx() as c:
        cur = c.execute(
            "UPDATE payments SET status=?, handled_at=?, handled_by=? "
            "WHERE id=? AND status='pending'",
            (status, now_iso(), handled_by, payment_id))
        return cur.rowcount > 0


def pending_payments():
    return [dict(r) for r in _q(
        "SELECT * FROM payments WHERE status='pending' ORDER BY id DESC")]


# ═══════════════════════════ الإحصائيات ═══════════════════════════
def get_stats():
    n = now_iso()
    today = today_iso()

    def g(sql, a=()):
        row = _q1(sql, a)
        return row[0] if row else 0

    return {
        'total_users': g("SELECT COUNT(*) FROM users"),
        'active_subs': g("SELECT COUNT(*) FROM users WHERE tier!='free' "
                         "AND expires_at IS NOT NULL AND expires_at>?", (n,)),
        'pro': g("SELECT COUNT(*) FROM users WHERE tier='pro' AND expires_at>?", (n,)),
        'vip': g("SELECT COUNT(*) FROM users WHERE tier='vip' AND expires_at>?", (n,)),
        'banned': g("SELECT COUNT(*) FROM users WHERE banned=1"),
        'pending_pay': g("SELECT COUNT(*) FROM payments WHERE status='pending'"),
        'revenue': g("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='approved'"),
        'dl_total': g("SELECT COUNT(*) FROM downloads"),
        'dl_today': g("SELECT COUNT(*) FROM downloads WHERE created_at>=?", (today,)),
        'dl_ok': g("SELECT COUNT(*) FROM downloads WHERE ok=1"),
        'dl_fail': g("SELECT COUNT(*) FROM downloads WHERE ok=0"),
        'bytes': g("SELECT COALESCE(SUM(size_bytes),0) FROM downloads WHERE ok=1"),
        'new_today': g("SELECT COUNT(*) FROM users WHERE joined_at>=?", (today,)),
        'cache_rows': g("SELECT COUNT(*) FROM cache"),
        'cache_hits': g("SELECT COALESCE(SUM(hits),0) FROM cache"),
    }


def top_platforms(limit=10):
    return [(r['platform'], r['c'], r['f']) for r in _q(
        "SELECT platform, COUNT(*) c, SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) f "
        "FROM downloads GROUP BY platform ORDER BY c DESC LIMIT ?", (limit,))]


def recent_errors(limit=15):
    return [dict(r) for r in _q(
        "SELECT platform, error, created_at FROM downloads WHERE ok=0 "
        "ORDER BY id DESC LIMIT ?", (limit,))]


def expired_users():
    return [dict(r) for r in _q(
        "SELECT user_id, tier, expires_at FROM users "
        "WHERE tier!='free' AND expires_at IS NOT NULL AND expires_at!='' "
        "AND expires_at < ?", (now_iso(),))]


def expiring_soon(days=3):
    n = datetime.datetime.now()
    return [dict(r) for r in _q(
        "SELECT user_id, tier, expires_at FROM users WHERE tier!='free' "
        "AND expires_at > ? AND expires_at <= ?",
        (n.isoformat(timespec='seconds'),
         (n + datetime.timedelta(days=days)).isoformat(timespec='seconds')))]


# ═══════════════════════════ إعدادات عامة ═══════════════════════════
def setting_get(key, default=None):
    r = _q1("SELECT value FROM settings WHERE key=?", (key,))
    return r['value'] if r else default


def setting_set(key, value):
    _x("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))


# ═══════════════════════════ الإحالة والتجربة ═══════════════════════════
def mark_trial_used(user_id):
    _x("UPDATE users SET trial_used=1 WHERE user_id=?", (user_id,))


def trial_used(user_id):
    r = _q1("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
    return bool(r and r['trial_used'])


def referrer_of(user_id):
    """من دعا هذا المستخدم، إن لم تُصرف مكافأته بعد."""
    r = _q1("SELECT referred_by, referral_rewarded FROM users WHERE user_id=?", (user_id,))
    if not r or not r['referred_by'] or r['referral_rewarded']:
        return None
    return r['referred_by']


def mark_referral_rewarded(user_id):
    """يصرف المكافأة مرة واحدة فقط — يعيد True إن كانت هذه أول مرة."""
    with tx() as c:
        cur = c.execute(
            "UPDATE users SET referral_rewarded=1 "
            "WHERE user_id=? AND referred_by IS NOT NULL AND referral_rewarded=0",
            (user_id,))
        return cur.rowcount > 0


def bump_referral_count(user_id):
    _x("UPDATE users SET referral_count=referral_count+1 WHERE user_id=?", (user_id,))


def referral_stats(user_id):
    r = _q1("SELECT referral_count FROM users WHERE user_id=?", (user_id,))
    invited = _q1("SELECT COUNT(*) c FROM users WHERE referred_by=?", (user_id,))
    return {
        'rewarded': int(r['referral_count'] or 0) if r else 0,
        'invited': int(invited['c'] or 0) if invited else 0,
    }


def top_referrers(limit=10):
    return [dict(r) for r in _q(
        "SELECT user_id, username, first_name, referral_count FROM users "
        "WHERE referral_count > 0 ORDER BY referral_count DESC LIMIT ?", (limit,))]
