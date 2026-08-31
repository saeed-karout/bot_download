# -*- coding: utf-8 -*-
"""الدفع: خطة ← طريقة دفع ← تعليمات + QR ← إيصال ← موافقة الأدمن."""
import os
import logging

from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.ext import ContextTypes

from config import (ADMIN_IDS, PLANS, ADMIN_CONTACT, active_payment_methods,
                    PAYMENT_METHODS, PAYMENT_INFO)
from database import create_payment, add_user
from utils.helpers import esc
from utils.keyboards import payment_actions

log = logging.getLogger(__name__)


# ═══════════════════════════ ١) اختيار طريقة الدفع ═══════════════════════════
async def show_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """بعد ضغط buy_<plan> — نعرض طرق الدفع المتاحة."""
    query = update.callback_query
    await query.answer()

    plan_key = query.data.replace('buy_', '', 1)
    plan = PLANS.get(plan_key)
    if not plan or plan['price'] <= 0:
        await query.edit_message_text("❌ خطة غير معروفة — جرّب /sub من جديد.")
        return

    ctx.user_data['selected_plan'] = plan_key
    ctx.user_data.pop('selected_method', None)

    methods = active_payment_methods()

    if not methods:
        await query.edit_message_text(
            f"💳 <b>خطة {plan['emoji']} {plan['name']}</b> — {plan['price']}$\n\n"
            f"⚠️ لم تُضبط طرق الدفع بعد.\n"
            f"تواصل مع الأدمن مباشرة: {esc(ADMIN_CONTACT)}",
            parse_mode='HTML',
            reply_markup=M([[B("🔙 رجوع", callback_data='m_sub')]]))
        return

    rows = [[B(f"{m['emoji']} {m['name']}", callback_data=f"pm_{plan_key}_{key}")]
            for key, m in methods.items()]
    rows.append([B("🔙 رجوع للخطط", callback_data='m_sub')])

    await query.edit_message_text(
        f"💳 <b>خطة {plan['emoji']} {plan['name']}</b>\n\n"
        f"💰 المبلغ: <b>{plan['price']}$</b>\n"
        f"📅 المدة: <b>{plan['days']} يوم</b>\n\n"
        f"👇 اختر طريقة الدفع المناسبة لك:",
        parse_mode='HTML', reply_markup=M(rows))


# ═══════════════════════════ ٢) تعليمات الطريقة المختارة ═══════════════════════════
async def show_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """بعد ضغط pm_<plan>_<method> — نعرض الرقم والتعليمات وصورة QR."""
    query = update.callback_query
    await query.answer()

    try:
        _, plan_key, method_key = query.data.split('_', 2)
    except ValueError:
        await query.answer("طلب غير صالح", show_alert=True)
        return

    plan = PLANS.get(plan_key)
    method = active_payment_methods().get(method_key)
    if not plan or not method:
        await query.edit_message_text("❌ خيار غير معروف — جرّب /sub من جديد.")
        return

    ctx.user_data['selected_plan'] = plan_key
    ctx.user_data['selected_method'] = method_key

    number = method['number']
    text = (
        f"{method['emoji']} <b>الدفع عبر {esc(method['name'])}</b>\n\n"
        f"📦 الخطة: <b>{plan['emoji']} {plan['name']}</b>\n"
        f"💰 المبلغ: <b>{plan['price']}$</b>\n"
        f"📅 المدة: <b>{plan['days']} يوم</b>\n\n"
        f"<b>📱 حوّل إلى الرقم:</b>\n"
        f"<code>{esc(number)}</code>\n"
        f"<i>(اضغط على الرقم لنسخه)</i>\n\n"
        f"<b>📝 الخطوات:</b>\n"
        f"{esc(method['howto'])}\n\n"
        f"<b>📸 بعد التحويل:</b>\n"
        f"أرسل <b>صورة الإيصال</b> هنا مباشرةً، وسيُفعَّل اشتراكك بعد التحقق.\n\n"
    )
    if PAYMENT_INFO:
        text += f"{esc(PAYMENT_INFO)}\n\n"
    text += f"❓ للاستفسار: {esc(ADMIN_CONTACT)}"

    kb = M([
        [B("🔄 تغيير طريقة الدفع", callback_data=f"buy_{plan_key}")],
        [B("🔙 رجوع للخطط", callback_data='m_sub')],
    ])

    qr = method.get('qr')
    has_qr = bool(qr) and os.path.exists(qr)

    # مع QR نرسل صورة جديدة بالتعليق، وبدونه نعدّل الرسالة نفسها
    if has_qr:
        try:
            await query.message.delete()
        except Exception:
            pass
        with open(qr, 'rb') as f:
            await ctx.bot.send_photo(
                query.message.chat_id, f, caption=text,
                parse_mode='HTML', reply_markup=kb)
    else:
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=kb)


# ═══════════════════════════ ٣) استقبال الإيصال ═══════════════════════════
async def receive_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)

    plan_key = ctx.user_data.get('selected_plan')
    if not plan_key or plan_key not in PLANS:
        await update.message.reply_text(
            "⚠️ <b>اختر خطة أولاً</b>\n\n"
            "اضغط /sub ← اختر الخطة ← اختر طريقة الدفع ← ثم أرسل صورة الإيصال.",
            parse_mode='HTML')
        return

    plan = PLANS[plan_key]
    method_key = ctx.user_data.get('selected_method')
    method = PAYMENT_METHODS.get(method_key, {})
    method_name = method.get('name', 'غير محددة')

    photo = update.message.photo[-1]

    pid = create_payment(user.id, user.username or str(user.id), plan_key,
                         photo.file_id, plan['days'], plan['price'], method_key)

    caption = (
        f"💳 <b>طلب دفع جديد</b> #{pid}\n\n"
        f"👤 الاسم: {esc(user.first_name)}\n"
        f"🔗 المعرف: @{esc(user.username) if user.username else '—'}\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"📦 الخطة: <b>{plan['name']}</b>\n"
        f"💰 المبلغ: <b>{plan['price']}$</b>\n"
        f"📅 المدة: <b>{plan['days']} يوم</b>\n"
        f"{method.get('emoji', '💵')} الطريقة: <b>{esc(method_name)}</b>"
    )

    sent_any = False
    for admin in ADMIN_IDS:
        try:
            await ctx.bot.send_photo(
                chat_id=admin, photo=photo.file_id, caption=caption,
                parse_mode='HTML', reply_markup=payment_actions(pid))
            sent_any = True
        except Exception as e:
            log.warning("تعذّر إشعار الأدمن %s: %s", admin, e)

    if sent_any:
        await update.message.reply_text(
            f"✅ <b>تم استلام إيصالك</b> — طلب #{pid}\n\n"
            f"📦 {plan['emoji']} {plan['name']} • {plan['price']}$\n"
            f"{method.get('emoji', '💵')} عبر {esc(method_name)}\n\n"
            f"⏳ سيتم التحقق قريباً وسنبلغك هنا فور التفعيل.",
            parse_mode='HTML')
    else:
        await update.message.reply_text(
            "⚠️ حُفظ طلبك لكن تعذّر إشعار الأدمن.\n"
            f"تواصل معه مباشرة: {esc(ADMIN_CONTACT)}\n"
            f"رقم الطلب: <code>{pid}</code>", parse_mode='HTML')
