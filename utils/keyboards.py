# -*- coding: utf-8 -*-
"""لوحات الأزرار."""
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from config import PLANS


def main_menu(is_admin=False, show_trial=False):
    rows = []
    if show_trial:
        rows.append([B("🎁 جرّب VIP مجاناً ٢٤ ساعة", callback_data='trial')])
    rows += [
        [B("⬇️ كيف أنزّل؟", callback_data='m_how'),
         B("🌐 المنصات المدعومة", callback_data='m_platforms')],
        [B("👤 حسابي", callback_data='m_account'),
         B("💎 خطط الاشتراك", callback_data='m_sub')],
        [B("🎟️ ادعُ واربح", callback_data='m_ref'),
         B("🏆 المتصدّرون", callback_data='m_top')],
        [B("ℹ️ المساعدة", callback_data='m_help')],
    ]
    if is_admin:
        rows.append([B("🛠️ لوحة الأدمن", callback_data='m_admin')])
    return M(rows)


def back_menu(target='m_home'):
    return M([[B("🔙 رجوع", callback_data=target)]])


def plans_menu():
    rows = [[B(f"{p['emoji']} {p['name']} — {p['price']}$ / {p['days']} يوم",
               callback_data=f"buy_{k}")]
            for k, p in PLANS.items() if p['price'] > 0]
    rows.append([B("🔙 رجوع", callback_data='m_home')])
    return M(rows)


def quality_menu(options, token, speed_bps, max_height, allow_mp3=True,
                 max_bytes=0, show_document=True):
    """أزرار الجودة — كل زر يعرض الدقة والحجم والزمن المتوقع.

    الجودات فوق سقف الخطة تظهر بقفل 🔒 وتقود لصفحة الترقية.
    """
    rows = []
    for o in options:
        if o.is_audio and not allow_mp3:
            continue

        locked = bool(max_height) and not o.is_audio and o.height > max_height
        too_big = bool(max_bytes) and o.filesize and o.filesize > max_bytes

        if locked:
            # نعرض الحجم أيضاً — ليرى المستخدم بالضبط ما يفوته، لا مجرد قفل
            from utils.helpers import human_size
            size = f" • {human_size(o.filesize)}" if o.filesize else ""
            rows.append([B(f"🔒 {o.name}{size} — اضغط للترقية",
                           callback_data=f"up_{token}_{o.key}")])
        elif too_big:
            from utils.helpers import human_size
            rows.append([B(f"⚠️ {o.name} — {human_size(o.filesize)} أكبر من الحد",
                           callback_data='big')])
        else:
            rows.append([B(o.button_text(speed_bps), callback_data=f"dl_{token}_{o.key}")])

    if show_document:
        rows.append([B("📄 إرسال كملف (بدون ضغط)", callback_data=f"df_{token}")])

    rows.append([B("❌ إلغاء", callback_data=f"cx_{token}")])
    return M(rows)


def admin_menu():
    return M([
        [B("📊 إحصائيات", callback_data='a_stats'),
         B("🩺 صحة السيرفر", callback_data='a_health')],
        [B("💳 طلبات معلّقة", callback_data='a_pending'),
         B("📉 آخر الأخطاء", callback_data='a_errors')],
        [B("🌐 أداء المنصات", callback_data='a_plat'),
         B("🍪 الكوكيز", callback_data='a_cookies')],
        [B("🔙 رجوع", callback_data='m_home')],
    ])


def payment_actions(payment_id):
    return M([[
        B("✅ موافقة", callback_data=f"pay_ok_{payment_id}"),
        B("❌ رفض", callback_data=f"pay_no_{payment_id}"),
    ]])
