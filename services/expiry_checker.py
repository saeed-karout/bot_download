# -*- coding: utf-8 -*-
"""مدقّق انتهاء الاشتراكات + تذكير التجديد.

الخطأ القديم: كانت الدالة متزامنة وتستدعي bot.send_message (وهي كوروتين)
بلا await، فلم تُرسل أي إشعار قط — وكانت تقرأ العمود الخطأ فلم تنتهِ أي خطة.
"""
import logging

from config import PLANS
from database import (expired_users, expiring_soon, set_tier,
                      setting_get, setting_set, today_iso)
from services.downloader import cleanup_orphans

log = logging.getLogger(__name__)


async def check_expiries(bot=None):
    """تُشغَّل كل بضع ساعات: تخفّض المنتهين وتذكّر من قارب على الانتهاء."""
    downgraded = 0

    for row in expired_users():
        uid = row['user_id']
        old = row.get('tier') or 'free'
        set_tier(uid, 'free', None)
        downgraded += 1

        if bot:
            plan = PLANS.get(old, {})
            try:
                await bot.send_message(
                    uid,
                    f"⌛ <b>انتهى اشتراكك</b>\n\n"
                    f"الخطة المنتهية: {plan.get('emoji', '')} {plan.get('name', old)}\n"
                    f"تم تحويلك للخطة المجانية.\n\n"
                    f"💎 جدّد الآن للعودة للجودة العالية: /sub",
                    parse_mode='HTML')
            except Exception as e:
                log.debug("تعذّر إشعار الانتهاء %s: %s", uid, e)

    reminded = 0
    for row in expiring_soon(days=3):
        uid = row['user_id']
        plan = PLANS.get(row.get('tier'), {})
        if not bot:
            break

        # تذكير واحد يومياً كحد أقصى — المدقّق يعمل كل ٦ ساعات
        key = f"reminded_{uid}"
        if setting_get(key) == today_iso():
            continue
        setting_set(key, today_iso())

        try:
            await bot.send_message(
                uid,
                f"⏰ <b>اشتراكك يقارب على الانتهاء</b>\n\n"
                f"الخطة: {plan.get('emoji', '')} {plan.get('name', '')}\n"
                f"ينتهي في: <b>{str(row.get('expires_at'))[:10]}</b>\n\n"
                f"💎 جدّد الآن لتجنّب الانقطاع: /sub",
                parse_mode='HTML')
            reminded += 1
        except Exception:
            pass

    cleanup_orphans()

    if downgraded or reminded:
        log.info("مدقّق الاشتراكات: خُفّض %s، ذُكّر %s", downgraded, reminded)
