# -*- coding: utf-8 -*-
"""الترحيب والقوائم وصفحات المعلومات."""
from telegram import Update
from telegram.ext import ContextTypes

from config import PLANS, ADMIN_IDS, TG_UPLOAD_LIMIT_MB, ADMIN_CONTACT
from database import add_user
from services import platforms as P
from services import extractor, media_tools
from services.tier_manager import account_text, get_plan
from utils.helpers import esc, human_size
from utils.keyboards import main_menu, back_menu, plans_menu


def is_admin(user_id):
    return user_id in ADMIN_IDS


# ═══════════════════════════ /start ═══════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # إحالة: /start ref_12345
    referred = None
    if ctx.args and ctx.args[0].startswith('ref_'):
        try:
            rid = int(ctx.args[0][4:])
            if rid != user.id:
                referred = rid
        except ValueError:
            pass

    add_user(user.id, user.username, user.first_name, referred)
    plan = get_plan(user.id)

    from config import TRIAL_ENABLED, TRIAL_HOURS
    from database import trial_used
    from services.tier_manager import get_active_tier
    show_trial = (TRIAL_ENABLED and get_active_tier(user.id) == 'free'
                  and not trial_used(user.id))

    text = (
        f"👋 أهلاً <b>{esc(user.first_name)}</b>!\n\n"
        f"📥 أنا بوت تنزيل الفيديو والصوت من أكثر من <b>1800 موقع</b>.\n\n"
        f"<b>كيف أستخدمه؟</b>\n"
        f"فقط أرسل لي أي رابط — وسأعرض لك كل الجودات المتاحة\n"
        f"مع <b>الحجم والزمن المتوقع</b> لكل واحدة، ثم اختر ما يناسبك.\n\n"
        f"💎 خطتك الحالية: <b>{plan['emoji']} {plan['name']}</b>\n"
        f"📤 حد الإرسال: <b>{TG_UPLOAD_LIMIT_MB} MB</b>\n"
    )

    if show_trial:
        text += (f"\n🎁 <b>هدية ترحيب:</b> جرّب كل مزايا VIP "
                 f"<b>مجاناً {TRIAL_HOURS} ساعة</b> — بضغطة واحدة.\n")

    text += "\n👇 اختر من القائمة:"

    await _reply(update, text, main_menu(is_admin(user.id), show_trial))


async def _reply(update, text, markup=None):
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode='HTML', reply_markup=markup,
                disable_web_page_preview=True)
        except Exception:
            await update.callback_query.message.reply_text(
                text, parse_mode='HTML', reply_markup=markup,
                disable_web_page_preview=True)
    else:
        await update.message.reply_text(
            text, parse_mode='HTML', reply_markup=markup,
            disable_web_page_preview=True)


# ═══════════════════════════ المنصات ═══════════════════════════
async def platforms_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = ["🌐 <b>المنصات المدعومة</b>\n"]

    lines.append("<b>⭐ الأكثر استخداماً:</b>")
    for p in P.featured_list():
        note = f" — <i>{esc(p.notes)}</i>" if p.notes else ""
        lines.append(f"{p.emoji} {esc(p.name)}{note}")

    others = [p for p in P.PLATFORMS if p.key not in P.FEATURED]
    lines.append("\n<b>➕ وأيضاً:</b>")
    lines.append("، ".join(f"{p.emoji} {esc(p.name)}" for p in others))

    lines += [
        "\n<b>🌍 وأي موقع آخر</b> يدعمه yt-dlp (أكثر من 1800 موقع):",
        "منصات إخبارية، تعليمية، رياضية، مواقع استضافة الفيديو، وروابط الملفات المباشرة",
        "(mp4, mp3, pdf, zip, apk ...)",
        "",
        "💡 <b>نصيحة:</b> انسخ رابط <b>المنشور نفسه</b>، لا رابط الحساب أو الصفحة الرئيسية.",
    ]
    await _reply(update, "\n".join(lines), back_menu())


# ═══════════════════════════ المساعدة ═══════════════════════════
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    speed = extractor.current_speed_bps()
    text = (
        "ℹ️ <b>دليل الاستخدام</b>\n\n"

        "<b>1️⃣ التنزيل</b>\n"
        "أرسل الرابط ← ستظهر قائمة الجودات ← اضغط الجودة المطلوبة.\n\n"

        "<b>2️⃣ ماذا تعني الأزرار؟</b>\n"
        "كل زر يعرض ثلاث معلومات:\n"
        "<code>🎬 1080p (Full HD) • 119 MB • ~39 ثانية</code>\n"
        "• <b>الدقة</b> — وضوح الصورة\n"
        "• <b>الحجم</b> — كم سيشغل من مساحة\n"
        "• <b>الزمن</b> — تقدير مدة التنزيل بسرعة السيرفر الحالية\n\n"

        "<b>3️⃣ دليل الجودات</b>\n"
        "<code>144p / 240p</code> — أصغر حجم، جودة ضعيفة\n"
        "<code>360p / 480p</code> — مناسبة للإنترنت البطيء\n"
        "<code>720p  (HD)</code> — جودة جيدة متوازنة ⭐\n"
        "<code>1080p (Full HD)</code> — جودة عالية ممتازة ⭐\n"
        "<code>1440p (2K)</code> — جودة احترافية\n"
        "<code>2160p (4K)</code> — أعلى جودة، حجم ضخم\n"
        "<code>🎵 MP3</code> — الصوت فقط (للأغاني والبودكاست)\n\n"

        f"⚡ <b>سرعة السيرفر الآن:</b> {human_size(speed)}/ث\n"
        f"📤 <b>حد الإرسال:</b> {TG_UPLOAD_LIMIT_MB} MB\n\n"

        "<b>4️⃣ ميزات إضافية</b>\n"
        "📦 <b>تنزيل متعدد</b> — أرسل عدة روابط في رسالة واحدة (للمشتركين)\n"
        "⚡ <b>إرسال فوري</b> — الرابط المُنزَّل سابقاً يصلك بلا انتظار\n"
        "🔗 <b>داخل أي محادثة</b> — اكتب اسم البوت ثم الرابط في أي دردشة\n"
        "🎁 <b>تجربة مجانية</b> — كل مزايا VIP ٢٤ ساعة\n"
        "🎟️ <b>ادعُ واربح</b> — أيام مجانية لك ولصديقك\n\n"

        "<b>5️⃣ الأوامر</b>\n"
        "/start — القائمة الرئيسية\n"
        "/platforms — المنصات المدعومة\n"
        "/me — حسابي وحدودي\n"
        "/sub — خطط الاشتراك\n"
        "/trial — 🎁 تجربة مجانية ٢٤ ساعة\n"
        "/invite — 🎟️ رابط دعوتك وأرباحك\n"
        "/top — 🏆 لوحة المتصدّرين\n"
        "/speed — سرعة السيرفر الحالية\n"
        "/help — هذه الصفحة\n\n"

        "<b>❓ مشاكل شائعة</b>\n"
        "• <b>«محتوى خاص»</b> — الحساب مقفل، لا حل\n"
        "• <b>«الملف كبير»</b> — اختر جودة أقل\n"
        "• <b>«المنصة تقيّد الطلبات»</b> — انتظر ١٠ دقائق\n\n"

        f"📮 للدعم: {esc(ADMIN_CONTACT)}"
    )
    await _reply(update, text, back_menu())


async def how_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "⬇️ <b>كيف أنزّل؟ — ثلاث خطوات</b>\n\n"
        "<b>1.</b> افتح المنشور في التطبيق واضغط «مشاركة» ← «نسخ الرابط»\n"
        "<b>2.</b> الصق الرابط هنا وأرسله\n"
        "<b>3.</b> اختر الجودة من القائمة التي ستظهر\n\n"
        "✅ <b>روابط صحيحة:</b>\n"
        "<code>youtube.com/watch?v=abc123</code>\n"
        "<code>youtube.com/shorts/abc123</code>\n"
        "<code>instagram.com/reel/ABC123</code>\n"
        "<code>tiktok.com/@user/video/123</code>\n"
        "<code>snapchat.com/spotlight/...</code>\n\n"
        "❌ <b>روابط خاطئة:</b>\n"
        "<code>youtube.com</code> — الصفحة الرئيسية\n"
        "<code>instagram.com/username</code> — صفحة حساب\n\n"
        "💡 يمكنك أيضاً إرسال رابط ملف مباشر (mp4, mp3, pdf, zip, apk)."
    )
    await _reply(update, text, back_menu())


# ═══════════════════════════ حسابي ═══════════════════════════
async def me_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    await _reply(update, account_text(user.id), back_menu())


# ═══════════════════════════ السرعة ═══════════════════════════
async def speed_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    speed = extractor.current_speed_bps()
    from database import recent_speed_bps
    measured = recent_speed_bps()

    def eta(mb):
        return (mb * 1024 * 1024) / speed

    from utils.helpers import human_time
    text = (
        "⚡ <b>سرعة السيرفر</b>\n\n"
        f"السرعة الحالية: <b>{human_size(speed)}/ث</b>\n"
        f"المصدر: {'قياس فعلي من آخر التنزيلات' if measured else 'تقدير افتراضي'}\n\n"
        "<b>⏱️ الزمن المتوقع:</b>\n"
        f"• فيديو 10 MB — {human_time(eta(10))}\n"
        f"• فيديو 50 MB — {human_time(eta(50))}\n"
        f"• فيديو 100 MB — {human_time(eta(100))}\n"
        f"• فيديو 500 MB — {human_time(eta(500))}\n\n"
        f"📤 حد الإرسال: <b>{TG_UPLOAD_LIMIT_MB} MB</b>\n\n"
        "<i>ملاحظة: الزمن الفعلي يعتمد أيضاً على سرعة المنصة المصدر.</i>"
    )
    await _reply(update, text, back_menu())


# ═══════════════════════════ موجّه الأزرار ═══════════════════════════
async def menu_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data

    if data == 'm_home':
        await start(update, ctx)
    elif data == 'm_how':
        await how_cmd(update, ctx)
    elif data == 'm_platforms':
        await platforms_cmd(update, ctx)
    elif data == 'm_help':
        await help_cmd(update, ctx)
    elif data == 'm_account':
        await me_cmd(update, ctx)
    elif data == 'm_sub':
        from handlers.subscription import subscription_menu
        await subscription_menu(update, ctx)
    elif data == 'm_ref':
        from handlers.growth import invite_cmd
        await invite_cmd(update, ctx)
    elif data == 'm_top':
        from handlers.growth import leaderboard_cmd
        await leaderboard_cmd(update, ctx)
    elif data == 'm_admin':
        from handlers.admin import admin_panel
        await admin_panel(update, ctx)
    else:
        await update.callback_query.answer()
