# -*- coding: utf-8 -*-
"""ميزات النمو: التجربة المجانية، نظام الإحالة، لوحة المتصدّرين."""
import logging
import datetime

from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.ext import ContextTypes

from config import (PLANS, TRIAL_ENABLED, TRIAL_TIER, TRIAL_HOURS,
                    REFERRAL_DAYS, REFERRAL_TIER)
from database import (add_user, trial_used, mark_trial_used, set_tier, get_user,
                      referral_stats, top_referrers, referrer_of,
                      mark_referral_rewarded, bump_referral_count)
from services.tier_manager import get_active_tier, expires_at
from utils.helpers import esc
from utils.keyboards import back_menu

log = logging.getLogger(__name__)


async def _out(update, text, markup=None):
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode='HTML', reply_markup=markup,
                disable_web_page_preview=True)
            return
        except Exception:
            pass
        await update.callback_query.message.reply_text(
            text, parse_mode='HTML', reply_markup=markup)
    else:
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=markup,
                                        disable_web_page_preview=True)


# ═══════════════════════════ التجربة المجانية ═══════════════════════════
async def trial_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)

    if not TRIAL_ENABLED:
        await _out(update, "🚫 التجربة المجانية غير مفعّلة حالياً.", back_menu())
        return

    current = get_active_tier(user.id)
    if current != 'free':
        exp = expires_at(user.id)
        await _out(update,
                   f"✨ لديك اشتراك <b>{PLANS[current]['name']}</b> نشط بالفعل"
                   + (f" حتى <b>{exp.strftime('%Y-%m-%d')}</b>." if exp else ".")
                   + "\n\nاستمتع! 🚀", back_menu())
        return

    if trial_used(user.id):
        await _out(update,
                   "🎁 <b>استخدمت تجربتك المجانية مسبقاً</b>\n\n"
                   "التجربة متاحة مرة واحدة لكل حساب.\n\n"
                   "💎 للاشتراك: /sub\n"
                   "🎟️ أو اربح أياماً مجانية بدعوة أصدقائك: /invite",
                   M([[B("💎 عرض الخطط", callback_data='m_sub')],
                      [B("🎟️ ادعُ أصدقاءك", callback_data='m_ref')]]))
        return

    plan = PLANS.get(TRIAL_TIER, PLANS['vip'])
    until = datetime.datetime.now() + datetime.timedelta(hours=TRIAL_HOURS)
    mark_trial_used(user.id)
    set_tier(user.id, TRIAL_TIER, until)

    quality = "بلا حدود (حتى 8K)" if not plan['max_height'] else f"حتى {plan['max_height']}p"
    limit = "بلا حدود ♾️" if not plan['daily_limit'] else f"{plan['daily_limit']} تنزيل/يوم"

    await _out(update,
               f"🎉 <b>بدأت تجربتك المجانية!</b>\n\n"
               f"💎 الخطة: <b>{plan['emoji']} {plan['name']}</b>\n"
               f"⏳ لمدة: <b>{TRIAL_HOURS} ساعة</b>\n"
               f"📅 حتى: <b>{until.strftime('%Y-%m-%d  %H:%M')}</b>\n\n"
               f"<b>ما فُتح لك الآن:</b>\n"
               f"  ✅ جودة {quality}\n"
               f"  ✅ {limit}\n"
               f"  ✅ تحويل MP3\n"
               f"  ✅ أولوية في التنزيل\n\n"
               f"🚀 جرّبها الآن — أرسل أي رابط!",
               back_menu())
    log.info("تجربة مجانية بدأت للمستخدم %s", user.id)


# ═══════════════════════════ الإحالة ═══════════════════════════
async def invite_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)

    me = await ctx.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user.id}"
    stats = referral_stats(user.id)
    plan = PLANS.get(REFERRAL_TIER, PLANS['pro'])

    text = (
        "🎟️ <b>ادعُ أصدقاءك — واربح أياماً مجانية</b>\n\n"
        f"<b>كيف يعمل؟</b>\n"
        f"١. شارك رابطك الخاص مع أصدقائك\n"
        f"٢. يبدأ صديقك البوت من رابطك\n"
        f"٣. عند أول تنزيل ناجح له:\n"
        f"   🎁 تربح أنت <b>{REFERRAL_DAYS} أيام {plan['name']}</b>\n"
        f"   🎁 ويربح صديقك <b>{REFERRAL_DAYS} أيام {plan['name']}</b> أيضاً\n\n"
        f"<b>🔗 رابطك الخاص:</b>\n"
        f"<code>{link}</code>\n"
        f"<i>(اضغط عليه لنسخه)</i>\n\n"
        f"<b>📊 إنجازك:</b>\n"
        f"👥 من انضم عبرك: <b>{stats['invited']}</b>\n"
        f"🎁 مكافآت حصلت عليها: <b>{stats['rewarded']}</b>\n"
        f"📅 مجموع الأيام المربوحة: <b>{stats['rewarded'] * REFERRAL_DAYS}</b>\n\n"
        f"💡 لا حد لعدد الدعوات — كل صديق يزيد رصيدك."
    )

    share = (f"https://t.me/share/url?url={link}"
             f"&text=" + "أفضل بوت تنزيل فيديوهات — يوتيوب وتيك توك وإنستغرام بأعلى جودة 🎬")

    await _out(update, text, M([
        [B("📤 مشاركة الرابط الآن", url=share)],
        [B("🏆 لوحة المتصدّرين", callback_data='m_top')],
        [B("🔙 رجوع", callback_data='m_home')],
    ]))


async def reward_referral(ctx, user_id):
    """تُستدعى بعد أول تنزيل ناجح — تمنح المكافأة للطرفين مرة واحدة."""
    referrer = referrer_of(user_id)
    if not referrer:
        return
    if not mark_referral_rewarded(user_id):
        return   # صُرفت مسبقاً

    bump_referral_count(referrer)
    plan = PLANS.get(REFERRAL_TIER, PLANS['pro'])

    for uid, msg in (
        (referrer, f"🎉 <b>صديق انضم عبر رابطك!</b>\n\n"
                   f"🎁 ربحت <b>{REFERRAL_DAYS} أيام {plan['emoji']} {plan['name']}</b>\n\n"
                   f"ادعُ المزيد واربح أكثر: /invite"),
        (user_id, f"🎁 <b>هدية ترحيب!</b>\n\n"
                  f"لأنك انضممت عبر دعوة صديق، ربحت\n"
                  f"<b>{REFERRAL_DAYS} أيام {plan['emoji']} {plan['name']}</b> مجاناً.\n\n"
                  f"ادعُ أصدقاءك أنت أيضاً: /invite"),
    ):
        try:
            _extend(uid, REFERRAL_TIER, REFERRAL_DAYS)
            await ctx.bot.send_message(uid, msg, parse_mode='HTML')
        except Exception as e:
            log.debug("تعذّر إشعار مكافأة الإحالة %s: %s", uid, e)

    log.info("مكافأة إحالة: %s ← %s", referrer, user_id)


def _extend(user_id, tier, days):
    """يمدّد الاشتراك: يضيف الأيام لما تبقّى بدل إهداره.

    الترقية لا تُخفَّض أبداً — من هو VIP لا يصير برو بمكافأة إحالة.
    """
    from config import TIER_ORDER
    user = get_user(user_id) or {}
    current = get_active_tier(user_id)
    exp = expires_at(user_id)
    now = datetime.datetime.now()

    base = exp if (exp and exp > now) else now
    new_exp = base + datetime.timedelta(days=days)

    # نحتفظ بالخطة الأعلى بين الحالية والمكافأة
    keep = current if TIER_ORDER.index(current) >= TIER_ORDER.index(tier) else tier
    if keep == 'free':
        keep = tier
    set_tier(user_id, keep, new_exp)


# ═══════════════════════════ لوحة المتصدّرين ═══════════════════════════
async def leaderboard_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = top_referrers(10)
    if not rows:
        await _out(update,
                   "🏆 <b>لوحة المتصدّرين</b>\n\n"
                   "لا أحد دعا أصدقاء بعد — كن أنت الأول!\n\n"
                   "/invite للحصول على رابطك.",
                   M([[B("🎟️ ابدأ الدعوة", callback_data='m_ref')],
                      [B("🔙 رجوع", callback_data='m_home')]]))
        return

    medals = ['🥇', '🥈', '🥉']
    lines = ["🏆 <b>أكثر الأعضاء دعوةً للأصدقاء</b>\n"]
    for i, r in enumerate(rows):
        mark = medals[i] if i < 3 else f"{i + 1}."
        name = r.get('first_name') or (('@' + r['username']) if r.get('username') else 'عضو')
        lines.append(f"{mark} {esc(str(name)[:22])} — <b>{r['referral_count']}</b> دعوة")

    lines.append("\n🎟️ انضم للمنافسة: /invite")
    await _out(update, "\n".join(lines),
               M([[B("🎟️ رابط دعوتي", callback_data='m_ref')],
                  [B("🔙 رجوع", callback_data='m_home')]]))
