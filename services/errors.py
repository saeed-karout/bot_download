# -*- coding: utf-8 -*-
"""ترجمة أخطاء المحركات إلى رسائل عربية مفهومة وقابلة للتنفيذ."""
import re

from config import ADMIN_CONTACT, TG_UPLOAD_LIMIT_MB
from services import media_tools

# (نمط البحث، الرسالة) — أول تطابق يفوز، لذلك رتّب من الأخص للأعم
RULES = [
    (r'empty media response|login required|requires? (a )?login|rate.?limit.*instagram',
     "🔒 <b>إنستغرام يطلب تسجيل دخول</b>\n\n"
     "هذا المنشور لا يمكن رؤيته بدون حساب.\n"
     "• إن كان الحساب خاصاً فلا يمكن تنزيله\n"
     "• إن كان عاماً: الكوكيز لدينا منتهية — أبلغ الأدمن {admin}"),

    (r'sign in to confirm|confirm you.?re not a bot|bot detection',
     "🤖 <b>يوتيوب يطلب تحققاً</b>\n\n"
     "المنصة تشك أن الطلبات آلية. جرّب بعد بضع دقائق.\n"
     "إن تكرر الأمر أبلغ الأدمن {admin}"),

    (r'private (video|account|profile)|this (video|post) is private',
     "🔒 <b>محتوى خاص</b>\nصاحب الحساب جعله خاصاً — لا يمكن تنزيله."),

    (r'video unavailable|content is not available|no longer available|has been removed|410',
     "🗑️ <b>المحتوى غير متاح</b>\nالمنشور محذوف أو الرابط قديم."),

    (r'404|not found',
     "🔗 <b>الرابط غير صحيح</b>\nتأكد من نسخ رابط المنشور كاملاً."),

    (r'age.?(restricted|gate)|inappropriate for some users',
     "🔞 <b>محتوى مقيّد بالعمر</b>\nيتطلب حساباً موثّقاً — غير مدعوم."),

    (r'429|too many requests|rate.?limit|slow.?down',
     "⏳ <b>المنصة تقيّد الطلبات مؤقتاً</b>\nانتظر ١٠–١٥ دقيقة ثم أعد المحاولة."),

    (r'geo.?(restricted|block)|not available in your country|blocked in your country',
     "🌍 <b>محجوب جغرافياً</b>\nالمحتوى غير متاح من موقع السيرفر."),

    (r'unsupported url|no video (could be )?found|no suitable extractor|unable to extract',
     "❌ <b>الرابط غير مدعوم</b>\n\n"
     "تأكد أنه رابط منشور مباشر وليس صفحة حساب.\n"
     "أرسل /platforms لرؤية المنصات المدعومة."),

    (r'is not a valid url|invalid url',
     "🔗 <b>هذا ليس رابطاً صالحاً</b>\nأرسل رابطاً يبدأ بـ https://"),

    (r'requested format is not available|no video formats',
     "🎞️ <b>لا توجد جودة قابلة للتنزيل</b>\n"
     "قد يكون بثاً مباشراً أو محتوى محمياً. جرّب جودة أخرى."),

    (r'ffmpeg|ffprobe',
     "🛠️ <b>أداة المعالجة ناقصة على السيرفر</b>\nأبلغ الأدمن {admin}"),

    (r'timed? ?out|timeout|connection (reset|aborted|refused)|network|temporary failure|getaddrinfo',
     "🌐 <b>ضعف في الاتصال</b>\nأعد المحاولة بعد قليل."),

    (r'too large|exceeds|larger than|file is too big|413',
     "📦 <b>الملف كبير جداً</b>\n"
     f"الحد الأقصى للإرسال {TG_UPLOAD_LIMIT_MB} ميغابايت.\n"
     "اختر جودة أقل من القائمة."),

    (r'drm|protected content|widevine',
     "🔐 <b>محتوى محمي بحقوق رقمية (DRM)</b>\nلا يمكن تنزيله."),

    (r'live (stream|event)|is live|premiere',
     "🔴 <b>بث مباشر</b>\nلا يمكن تنزيله أثناء البث — انتظر انتهاءه."),

    (r'members.?only|subscribers? only|paid|premium',
     "💳 <b>محتوى مدفوع أو للمشتركين فقط</b>\nغير قابل للتنزيل."),

    (r'unable to download webpage|http error 5\d\d',
     "🏥 <b>خادم المنصة لا يستجيب</b>\nالمشكلة من المنصة نفسها — جرّب لاحقاً."),

    (r'رابط غير آمن|ssrf',
     "🚫 <b>رابط مرفوض لأسباب أمنية</b>"),
]

_COMPILED = [(re.compile(p, re.I), m) for p, m in RULES]


def friendly(error, platform=None):
    """يحوّل استثناءً أو نصاً إلى رسالة HTML للمستخدم."""
    text = str(error or '')

    for rx, msg in _COMPILED:
        if rx.search(text):
            out = msg.format(admin=ADMIN_CONTACT)
            # تلميح إضافي إن كانت الأداة ناقصة فعلاً
            if 'يوتيوب يطلب تحققاً' in out and not media_tools.has_js_runtime():
                out += "\n\n⚙️ (السيرفر ينقصه محرك JS — الأدمن: /installtools)"
            return out

    hint = ""
    if platform is not None and getattr(platform, 'needs_cookies', False):
        hint = (f"\n\n💡 منصة {platform.name} تتطلب كوكيز صالحة على السيرفر.\n"
                f"أبلغ الأدمن {ADMIN_CONTACT}")

    short = re.sub(r'\s+', ' ', text).strip()
    short = re.sub(r'^ERROR:\s*', '', short)
    short = re.sub(r'\[[a-zA-Z0-9_:-]+\]\s*', '', short)[:200]

    return (f"❌ <b>تعذّر التنزيل</b>\n\n<code>{short}</code>{hint}\n\n"
            f"جرّب رابطاً آخر أو أعد المحاولة لاحقاً.")


def summarize_attempts(attempts):
    """ملخّص تقني للأدمن فقط."""
    if not attempts:
        return "لا تفاصيل"
    return "\n".join(f"• {re.sub(chr(10), ' ', str(a))[:150]}" for a in attempts[:6])
