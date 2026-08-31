# -*- coding: utf-8 -*-
"""إدارة الخطط والصلاحيات والحدود اليومية."""
import datetime

from config import PLANS, plan_of, TG_UPLOAD_LIMIT
from database import (get_user, add_user, downloads_today, increment_download,
                      set_tier, is_banned)


def _parse(ts):
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(str(ts))
    except ValueError:
        try:
            return datetime.datetime.combine(
                datetime.date.fromisoformat(str(ts)[:10]), datetime.time.max)
        except ValueError:
            return None


def is_expired(user):
    """هل انتهى اشتراك المستخدم؟

    المقارنة تتم ككائنات زمن لا كنصوص — المقارنة النصية كانت تفشل
    عندما يُخزَّن التاريخ بصيغتين مختلفتين.
    """
    if not user or user.get('tier', 'free') == 'free':
        return False
    exp = _parse(user.get('expires_at'))
    if exp is None:
        return False          # اشتراك دائم مُفعَّل يدوياً
    return exp < datetime.datetime.now()


def get_active_tier(user_id):
    user = get_user(user_id)
    if not user:
        return 'free'
    if is_expired(user):
        # نُنزّله فوراً حتى لا يستفيد من خطة منتهية بين دورتَي المدقّق
        set_tier(user_id, 'free', None)
        return 'free'
    return user.get('tier') or 'free'


def get_plan(user_id):
    return plan_of(get_active_tier(user_id))


def expires_at(user_id):
    user = get_user(user_id)
    return _parse(user.get('expires_at')) if user else None


def days_left(user_id):
    exp = expires_at(user_id)
    if not exp:
        return None
    delta = exp - datetime.datetime.now()
    return max(0, delta.days)


def remaining_today(user_id):
    """كم تنزيلاً بقي اليوم؟ None تعني بلا حدود."""
    plan = get_plan(user_id)
    if not plan['daily_limit']:
        return None
    return max(0, plan['daily_limit'] - downloads_today(user_id))


def can_download(user_id):
    """بوابة ما قبل التنزيل. لا تزيد العدّاد — الزيادة بعد النجاح فقط."""
    add_user(user_id)

    if is_banned(user_id):
        return False, "🚫 حسابك محظور من استخدام البوت."

    tier = get_active_tier(user_id)
    plan = plan_of(tier)

    if not plan['daily_limit']:
        return True, ''

    used = downloads_today(user_id)
    if used >= plan['daily_limit']:
        return False, (
            f"⚠️ <b>وصلت حدّك اليومي</b>\n\n"
            f"خطتك: {plan['emoji']} {plan['name']} — {plan['daily_limit']} تنزيلات/يوم\n"
            f"يتجدّد الحد تلقائياً منتصف الليل.\n\n"
            f"💎 للترقية والحصول على المزيد: /sub")
    return True, ''


def commit_download(user_id, size_bytes=0):
    """يُستدعى بعد نجاح الإرسال فقط."""
    increment_download(user_id, size_bytes)


def max_height(user_id):
    return get_plan(user_id)['max_height']


def max_bytes(user_id):
    """أقصى حجم مسموح: الأصغر بين حد الخطة وحد تيليجرام."""
    plan_mb = get_plan(user_id)['max_file_mb']
    plan_limit = plan_mb * 1024 * 1024 if plan_mb else TG_UPLOAD_LIMIT
    return min(plan_limit, TG_UPLOAD_LIMIT)


def max_duration(user_id):
    return get_plan(user_id)['max_duration']


def allows_mp3(user_id):
    return get_plan(user_id)['mp3']


def allows_playlist(user_id):
    return get_plan(user_id)['playlist']


def account_text(user_id):
    """بطاقة الحساب المعروضة للمستخدم."""
    from utils.helpers import human_size
    from database import get_user as gu

    user = gu(user_id) or {}
    tier = get_active_tier(user_id)
    plan = plan_of(tier)

    left = remaining_today(user_id)
    left_txt = "بلا حدود ♾️" if left is None else f"{left} من {plan['daily_limit']}"

    quality = "بلا حدود (حتى 8K) ♾️" if not plan['max_height'] else f"حتى {plan['max_height']}p"
    size_txt = "بلا حدود" if not plan['max_file_mb'] else f"{plan['max_file_mb']} MB"

    lines = [
        "👤 <b>حسابي</b>",
        "",
        f"💎 الخطة: <b>{plan['emoji']} {plan['name']}</b>",
    ]

    d = days_left(user_id)
    if tier != 'free':
        exp = expires_at(user_id)
        if exp:
            lines.append(f"📅 تنتهي في: <b>{exp.strftime('%Y-%m-%d')}</b> (بقي {d} يوم)")
        else:
            lines.append("📅 اشتراك دائم")

    lines += [
        f"📥 تنزيلات اليوم: <b>{left_txt}</b>",
        f"🎬 أقصى جودة: <b>{quality}</b>",
        f"📦 أقصى حجم: <b>{size_txt}</b>",
        f"🎵 تحويل MP3: {'✅' if plan['mp3'] else '❌'}",
        "",
        f"📊 إجمالي تنزيلاتك: <b>{user.get('total_downloads', 0)}</b>",
        f"💾 إجمالي الحجم: <b>{human_size(user.get('total_bytes', 0))}</b>",
    ]

    if tier == 'free':
        lines += ["", "💎 رقِّ حسابك لجودة أعلى وحدود أكبر: /sub"]

    return "\n".join(lines)
