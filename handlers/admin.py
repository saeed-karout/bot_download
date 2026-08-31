# -*- coding: utf-8 -*-
"""لوحة الأدمن: إحصائيات، تفعيل، حظر، بث، كوكيز، صحة السيرفر."""
import os
import asyncio
import logging
import datetime

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_IDS, PLANS, COOKIES_DIR, TG_UPLOAD_LIMIT_MB, USING_LOCAL_API
from database import (get_stats, top_platforms, recent_errors, set_tier,
                      set_banned, get_user, all_user_ids, pending_payments,
                      get_payment, update_payment_status, cache_clear, add_user)
from services import media_tools, platforms as P
from services.tier_manager import get_active_tier, expires_at
from utils.helpers import esc, human_size, shorten
from utils.keyboards import admin_menu, back_menu

log = logging.getLogger(__name__)


def is_admin(user_id):
    return user_id in ADMIN_IDS


def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else 0
        if not is_admin(uid):
            if update.callback_query:
                await update.callback_query.answer("غير مصرّح", show_alert=True)
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


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


# ═══════════════════════════ اللوحة ═══════════════════════════
@admin_only
async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🛠️ <b>لوحة الأدمن</b>\n\n"
        "<b>الأوامر:</b>\n"
        "<code>/activate &lt;id&gt; &lt;pro|vip&gt; &lt;أيام&gt;</code> — تفعيل\n"
        "<code>/revoke &lt;id&gt;</code> — إلغاء اشتراك\n"
        "<code>/ban &lt;id&gt;</code> / <code>/unban &lt;id&gt;</code>\n"
        "<code>/user &lt;id&gt;</code> — بيانات مستخدم\n"
        "<code>/broadcast &lt;نص&gt;</code> — رسالة للجميع\n"
        "<code>/cookies</code> — إدارة الكوكيز\n"
        "<code>/installtools</code> — تثبيت ffmpeg و Deno\n"
        "<code>/health</code> — صحة السيرفر\n"
        "<code>/clearcache</code> — مسح الكاش\n"
    )
    await _out(update, text, admin_menu())


# ═══════════════════════════ إحصائيات ═══════════════════════════
def _stats_text():
    s = get_stats()
    rate = (s['dl_ok'] * 100 // s['dl_total']) if s['dl_total'] else 0
    return (
        "📊 <b>الإحصائيات</b>\n\n"
        "<b>👥 المستخدمون</b>\n"
        f"الإجمالي: <b>{s['total_users']}</b>  |  جدد اليوم: <b>{s['new_today']}</b>\n"
        f"محظورون: {s['banned']}\n\n"
        "<b>💎 الاشتراكات</b>\n"
        f"نشطة: <b>{s['active_subs']}</b>  (برو: {s['pro']} | VIP: {s['vip']})\n"
        f"طلبات معلّقة: <b>{s['pending_pay']}</b>\n"
        f"الإيرادات: <b>{s['revenue']:.0f}$</b>\n\n"
        "<b>📥 التنزيلات</b>\n"
        f"الإجمالي: <b>{s['dl_total']}</b>  |  اليوم: <b>{s['dl_today']}</b>\n"
        f"نجاح: {s['dl_ok']} | فشل: {s['dl_fail']} | النسبة: <b>{rate}%</b>\n"
        f"إجمالي الحجم: <b>{human_size(s['bytes'])}</b>\n\n"
        "<b>⚡ الكاش</b>\n"
        f"ملفات محفوظة: {s['cache_rows']} | إعادة إرسال فوري: {s['cache_hits']}"
    )


@admin_only
async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _out(update, _stats_text(), admin_menu())


# ═══════════════════════════ صحة السيرفر ═══════════════════════════
def _health_text():
    import shutil as sh
    from config import DOWNLOAD_DIR
    try:
        usage = sh.disk_usage(DOWNLOAD_DIR)
        disk = f"{human_size(usage.free)} حرة من {human_size(usage.total)}"
    except Exception:
        disk = "غير معروف"

    cookies = []
    for p in P.PLATFORMS:
        if not p.cookie_file:
            continue
        path = os.path.join(COOKIES_DIR, p.cookie_file)
        if os.path.exists(path):
            age = (datetime.datetime.now()
                   - datetime.datetime.fromtimestamp(os.path.getmtime(path))).days
            cookies.append(f"✅ {p.name} ({age} يوم)")
        elif p.needs_cookies:
            cookies.append(f"❌ {p.name} — <b>مطلوبة!</b>")

    return (
        "🩺 <b>صحة السيرفر</b>\n\n"
        + media_tools.status_text() +
        f"\n\n💾 <b>القرص:</b> {disk}\n"
        f"📤 <b>حد الرفع:</b> {TG_UPLOAD_LIMIT_MB} MB"
        + (" (Local API ✅)" if USING_LOCAL_API else " (Bot API الرسمي)") +
        "\n\n🍪 <b>الكوكيز:</b>\n" + ("\n".join(cookies) if cookies else "لا شيء")
    )


@admin_only
async def health_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _out(update, _health_text(), admin_menu())


# ═══════════════════════════ أداء المنصات ═══════════════════════════
@admin_only
async def platforms_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = top_platforms(15)
    if not rows:
        await _out(update, "لا توجد بيانات بعد.", admin_menu())
        return
    lines = ["🌐 <b>أداء المنصات</b>\n"]
    for key, count, fails in rows:
        plat = P.get(key)
        fails = fails or 0
        rate = ((count - fails) * 100 // count) if count else 0
        icon = "🟢" if rate >= 90 else ("🟡" if rate >= 60 else "🔴")
        lines.append(f"{icon} {plat.emoji} {esc(plat.name)}: {count} طلب — نجاح {rate}%")
    await _out(update, "\n".join(lines), admin_menu())


@admin_only
async def errors_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = recent_errors(12)
    if not rows:
        await _out(update, "✅ لا أخطاء مسجّلة.", admin_menu())
        return
    lines = ["📉 <b>آخر الأخطاء</b>\n"]
    for r in rows:
        plat = P.get(r['platform'])
        lines.append(f"{plat.emoji} <b>{esc(plat.name)}</b> — {r['created_at'][11:16]}\n"
                     f"<code>{esc(shorten(r['error'], 110))}</code>\n")
    await _out(update, "\n".join(lines), admin_menu())


# ═══════════════════════════ تفعيل / إلغاء ═══════════════════════════
@admin_only
async def activate_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        target = int(ctx.args[0])
        plan_key = ctx.args[1].lower()
        days = int(ctx.args[2]) if len(ctx.args) > 2 else PLANS[plan_key]['days']
        if plan_key not in PLANS or PLANS[plan_key]['price'] <= 0:
            raise ValueError("خطة غير صالحة")
    except (IndexError, ValueError, KeyError):
        await update.message.reply_text(
            "<b>الاستخدام:</b>\n"
            "<code>/activate &lt;user_id&gt; &lt;pro|vip&gt; [أيام]</code>\n\n"
            "مثال: <code>/activate 123456789 vip 30</code>",
            parse_mode='HTML')
        return

    expiry = datetime.datetime.now() + datetime.timedelta(days=days)
    add_user(target)
    set_tier(target, plan_key, expiry)

    await update.message.reply_text(
        f"✅ تم تفعيل <code>{target}</code>\n"
        f"الخطة: <b>{PLANS[plan_key]['name']}</b>\n"
        f"تنتهي: <b>{expiry.strftime('%Y-%m-%d')}</b>", parse_mode='HTML')

    try:
        await ctx.bot.send_message(
            target,
            f"🎉 <b>تم تفعيل اشتراكك!</b>\n\n"
            f"💎 الخطة: <b>{PLANS[plan_key]['emoji']} {PLANS[plan_key]['name']}</b>\n"
            f"📅 حتى: <b>{expiry.strftime('%Y-%m-%d')}</b>\n\n"
            f"استمتع! أرسل أي رابط للبدء.", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"⚠️ لم يصل الإشعار للمستخدم: {e}")


@admin_only
async def revoke_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        target = int(ctx.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("الاستخدام: <code>/revoke &lt;user_id&gt;</code>",
                                        parse_mode='HTML')
        return
    set_tier(target, 'free', None)
    await update.message.reply_text(f"✅ أُلغي اشتراك <code>{target}</code>", parse_mode='HTML')


@admin_only
async def ban_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    banning = update.message.text.startswith('/ban')
    try:
        target = int(ctx.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(
            f"الاستخدام: <code>/{'ban' if banning else 'unban'} &lt;user_id&gt;</code>",
            parse_mode='HTML')
        return
    set_banned(target, banning)
    await update.message.reply_text(
        f"{'🚫 حُظر' if banning else '✅ رُفع الحظر عن'} <code>{target}</code>",
        parse_mode='HTML')


@admin_only
async def user_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        target = int(ctx.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("الاستخدام: <code>/user &lt;user_id&gt;</code>",
                                        parse_mode='HTML')
        return

    u = get_user(target)
    if not u:
        await update.message.reply_text("❌ مستخدم غير موجود.")
        return

    exp = expires_at(target)
    await update.message.reply_text(
        f"👤 <b>بيانات المستخدم</b>\n\n"
        f"🆔 <code>{u['user_id']}</code>\n"
        f"👤 {esc(u.get('first_name') or '—')} (@{esc(u.get('username') or '—')})\n"
        f"💎 الخطة: <b>{get_active_tier(target)}</b>\n"
        f"📅 تنتهي: {exp.strftime('%Y-%m-%d') if exp else '—'}\n"
        f"📥 اليوم: {u.get('downloads_today', 0)} | الإجمالي: {u.get('total_downloads', 0)}\n"
        f"💾 الحجم: {human_size(u.get('total_bytes', 0))}\n"
        f"🚫 محظور: {'نعم' if u.get('banned') else 'لا'}\n"
        f"📆 انضم: {u.get('joined_at') or '—'}", parse_mode='HTML')


# ═══════════════════════════ الطلبات المعلّقة ═══════════════════════════
@admin_only
async def pending_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = pending_payments()
    if not rows:
        await _out(update, "✅ لا طلبات معلّقة.", admin_menu())
        return
    lines = ["💳 <b>طلبات معلّقة</b>\n"]
    for r in rows[:20]:
        lines.append(f"#{r['id']} — <code>{r['user_id']}</code> @{esc(r['username'] or '—')}\n"
                     f"   {r['plan']} • {r['amount']}$ • {r['created_at'][:16]}")
    lines.append("\nاستخدم أزرار الإيصال، أو <code>/activate &lt;id&gt; &lt;خطة&gt; &lt;أيام&gt;</code>")
    await _out(update, "\n".join(lines), admin_menu())


@admin_only
async def payment_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """أزرار ✅/❌ تحت إيصال الدفع."""
    query = update.callback_query
    await query.answer()

    _, action, pid_s = query.data.split('_', 2)
    try:
        pid = int(pid_s)
    except ValueError:
        return

    pay = get_payment(pid)
    if not pay:
        await query.edit_message_caption(caption="❌ طلب غير موجود.")
        return

    approved = (action == 'ok')
    status = 'approved' if approved else 'rejected'

    # يمنع التفعيل المزدوج إن ضغط أدمنان معاً
    if not update_payment_status(pid, status, update.effective_user.id):
        await query.answer("⚠️ هذا الطلب عولج مسبقاً", show_alert=True)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    uid = pay['user_id']
    plan_key = pay['plan']
    days = pay['days'] or 30
    plan = PLANS.get(plan_key, {})

    if approved:
        expiry = datetime.datetime.now() + datetime.timedelta(days=days)
        add_user(uid)
        set_tier(uid, plan_key, expiry)
        caption = (f"✅ <b>تمت الموافقة</b> — طلب #{pid}\n"
                   f"👤 <code>{uid}</code>\n"
                   f"📦 {plan.get('name', plan_key)} • {days} يوم\n"
                   f"📅 حتى {expiry.strftime('%Y-%m-%d')}")
        user_msg = (f"🎉 <b>تم تأكيد دفعك وتفعيل اشتراكك!</b>\n\n"
                    f"💎 الخطة: <b>{plan.get('emoji','')} {plan.get('name', plan_key)}</b>\n"
                    f"📅 حتى: <b>{expiry.strftime('%Y-%m-%d')}</b>\n\n"
                    f"استمتع! أرسل أي رابط للبدء 🚀")
    else:
        caption = f"❌ <b>مرفوض</b> — طلب #{pid}\n👤 <code>{uid}</code>"
        user_msg = ("❌ <b>لم يتم تأكيد طلب الدفع</b>\n\n"
                    "تأكد من وضوح صورة الإيصال وصحة المبلغ، ثم أعد المحاولة.\n"
                    "للاستفسار تواصل مع الأدمن.")

    try:
        await query.edit_message_caption(caption=caption, parse_mode='HTML')
    except Exception:
        await query.message.reply_text(caption, parse_mode='HTML')

    try:
        await ctx.bot.send_message(uid, user_msg, parse_mode='HTML')
    except Exception as e:
        await query.message.reply_text(f"⚠️ تعذّر إشعار المستخدم: {e}")


# ═══════════════════════════ البث ═══════════════════════════
@admin_only
async def broadcast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.partition(' ')[2].strip()
    if not text:
        await update.message.reply_text(
            "الاستخدام: <code>/broadcast &lt;الرسالة&gt;</code>", parse_mode='HTML')
        return

    users = all_user_ids()
    status = await update.message.reply_text(f"📢 جاري الإرسال إلى {len(users)} مستخدم...")

    sent = failed = 0
    for i, uid in enumerate(users, 1):
        try:
            await ctx.bot.send_message(uid, text, parse_mode='HTML')
            sent += 1
        except Exception:
            failed += 1
        # 25 رسالة/ثانية هو حد تيليجرام العملي
        await asyncio.sleep(0.05)
        if i % 50 == 0:
            try:
                await status.edit_text(f"📢 {i}/{len(users)} — نجح {sent}، فشل {failed}")
            except Exception:
                pass

    await status.edit_text(f"✅ <b>انتهى البث</b>\nنجح: {sent}\nفشل: {failed}",
                           parse_mode='HTML')


# ═══════════════════════════ الكوكيز ═══════════════════════════
COOKIE_TARGETS = {p.cookie_file: p for p in P.PLATFORMS if p.cookie_file}


def _cookies_text():
    lines = ["🍪 <b>إدارة الكوكيز</b>\n"]
    for fname, plat in sorted(COOKIE_TARGETS.items()):
        path = os.path.join(COOKIES_DIR, fname)
        if os.path.exists(path):
            age = (datetime.datetime.now()
                   - datetime.datetime.fromtimestamp(os.path.getmtime(path))).days
            warn = " ⚠️ قديمة" if age > 25 else ""
            lines.append(f"✅ <code>{fname}</code> — {plat.name} ({age} يوم){warn}")
        else:
            mark = "❌" if plat.needs_cookies else "⬜"
            need = " — <b>مطلوبة!</b>" if plat.needs_cookies else ""
            lines.append(f"{mark} <code>{fname}</code> — {plat.name}{need}")

    lines += [
        "",
        "<b>📤 كيف أضيف كوكيز؟</b>",
        "١. ثبّت إضافة <b>Get cookies.txt LOCALLY</b> في المتصفح",
        "٢. سجّل دخولك للمنصة",
        "٣. صدّر الكوكيز بصيغة Netscape",
        "٤. <b>أرسل الملف هنا كمستند</b> باسمه الصحيح",
        "   (مثلاً <code>instagram.txt</code>)",
        "",
        "⚠️ استخدم حساباً ثانوياً — قد تُقيّده المنصات.",
        "🔄 كوكيز إنستغرام تنتهي كل ٢–٤ أسابيع، جدّدها دورياً.",
    ]
    return "\n".join(lines)


@admin_only
async def cookies_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _out(update, _cookies_text(), admin_menu())


@admin_only
async def receive_cookie_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """يستقبل ملف كوكيز مرسلاً كمستند من الأدمن."""
    doc = update.message.document
    name = (doc.file_name or '').strip().lower()

    if not name.endswith('.txt'):
        await update.message.reply_text(
            "❌ يجب أن يكون ملف <code>.txt</code> بصيغة Netscape.", parse_mode='HTML')
        return

    if name not in COOKIE_TARGETS:
        await update.message.reply_text(
            "❌ اسم غير معروف.\n\n<b>الأسماء المقبولة:</b>\n"
            + "\n".join(f"• <code>{f}</code>" for f in sorted(COOKIE_TARGETS)),
            parse_mode='HTML')
        return

    if doc.file_size > 2 * 1024 * 1024:
        await update.message.reply_text("❌ الملف كبير جداً (الحد 2MB).")
        return

    dest = os.path.join(COOKIES_DIR, name)
    tmp = dest + '.tmp'
    try:
        f = await ctx.bot.get_file(doc.file_id)
        await f.download_to_drive(tmp)

        with open(tmp, 'r', encoding='utf-8', errors='ignore') as fh:
            head = fh.read(4096)
        if 'netscape' not in head.lower() and '\t' not in head:
            os.remove(tmp)
            await update.message.reply_text(
                "❌ الملف ليس بصيغة Netscape المطلوبة.\n"
                "استخدم إضافة «Get cookies.txt LOCALLY».")
            return

        os.replace(tmp, dest)
        plat = COOKIE_TARGETS[name]
        await update.message.reply_text(
            f"✅ <b>تم حفظ كوكيز {plat.emoji} {plat.name}</b>\n\n"
            f"جرّب الآن رابطاً من {plat.name} للتأكد.", parse_mode='HTML')
        log.info("حُدّثت كوكيز %s", name)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        await update.message.reply_text(f"❌ فشل الحفظ: {e}")


# ═══════════════════════════ الأدوات ═══════════════════════════
@admin_only
async def install_tools_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔧 جاري فحص الأدوات...")

    async def say(t):
        try:
            await msg.edit_text(t)
        except Exception:
            pass

    loop = asyncio.get_running_loop()

    def push(t):
        asyncio.run_coroutine_threadsafe(say(t), loop)

    report = []

    if media_tools.has_ffmpeg():
        report.append("✅ ffmpeg موجود مسبقاً")
    else:
        ok, m = await asyncio.to_thread(media_tools.install_ffmpeg_windows, push)
        report.append(m)

    if media_tools.has_js_runtime():
        report.append("✅ Deno موجود مسبقاً")
    else:
        ok, m = await asyncio.to_thread(media_tools.install_deno, push)
        report.append(m)

    if media_tools.has_pot():
        await say("🔄 جاري تهيئة مزوّد PO Token...")
        ok = await asyncio.to_thread(media_tools.warm_pot_cache)
        report.append("✅ مزوّد PO Token جاهز" if ok else "⚠️ تعذّرت تهيئة مزوّد PO Token")
    else:
        report.append("⚠️ مزوّد PO Token غير مثبّت (اختياري لكنه يحسّن يوتيوب)")

    await say("\n".join(report) + "\n\n" + _health_text())


@admin_only
async def clearcache_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cache_clear()
    from services.downloader import cleanup_orphans
    cleanup_orphans()
    await update.message.reply_text("🧹 تم مسح الكاش والملفات المؤقتة.")


# ═══════════════════════════ موجّه أزرار الأدمن ═══════════════════════════
@admin_only
async def admin_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == 'a_stats':
        await stats_cmd(update, ctx)
    elif data == 'a_health':
        await health_cmd(update, ctx)
    elif data == 'a_pending':
        await pending_cmd(update, ctx)
    elif data == 'a_errors':
        await errors_cmd(update, ctx)
    elif data == 'a_plat':
        await platforms_stats(update, ctx)
    elif data == 'a_cookies':
        await cookies_cmd(update, ctx)
    else:
        await update.callback_query.answer()
