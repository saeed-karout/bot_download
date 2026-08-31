# -*- coding: utf-8 -*-
"""نقطة تشغيل البوت."""
import os
import sys
import html
import logging
import logging.handlers

from telegram import Update, BotCommand
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut, Conflict
from telegram.ext import (Application, ApplicationBuilder, CommandHandler,
                          MessageHandler, CallbackQueryHandler, InlineQueryHandler,
                          ContextTypes, filters, Defaults)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import (BOT_TOKEN, ADMIN_IDS, ADMIN_ID, LOG_PATH, LOCAL_BOT_API,
                    USING_LOCAL_API, TG_UPLOAD_LIMIT_MB, PORT)
from handlers import (start, download, subscription, payment, admin,
                      growth, inline)
from services import media_tools
from services.expiry_checker import check_expiries
from services.downloader import cleanup_orphans

# ═══════════════════════════ السجلّ ═══════════════════════════
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s',
    handlers=[
        logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ])

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.INFO)
logging.getLogger('apscheduler').setLevel(logging.WARNING)

log = logging.getLogger('bot')

scheduler = AsyncIOScheduler()


# ═══════════════════════════ معالج الأخطاء ═══════════════════════════
_net_errors = {'count': 0, 'notified': False}


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    err = ctx.error

    # ── أخطاء الشبكة ليست أعطالاً في البوت ──
    # الاتصال بـ api.telegram.org ينقطع أحياناً (شبكة ضعيفة أو حجب).
    # مكتبة تيليجرام تعيد المحاولة تلقائياً، فلا داعي لتتبّع كامل ولا لإزعاج
    # الأدمن. نسجّل سطراً واحداً مختصراً فقط.
    if isinstance(err, (NetworkError, TimedOut)):
        _net_errors['count'] += 1
        log.warning("انقطاع شبكة مؤقت مع تيليجرام (%s) — إعادة المحاولة تلقائياً: %s",
                    _net_errors['count'], type(err).__name__)
        # تنبيه واحد فقط إن تكرر كثيراً — قد يعني حجباً يحتاج بروكسي
        if _net_errors['count'] == 20 and not _net_errors['notified'] and ADMIN_ID:
            _net_errors['notified'] = True
            try:
                await ctx.bot.send_message(
                    ADMIN_ID,
                    "📡 <b>اتصالك بتيليجرام غير مستقر</b>\n\n"
                    "تكرر انقطاع الشبكة ٢٠ مرة. البوت يعيد المحاولة تلقائياً "
                    "ولا يفقد رسائل، لكن الاستجابة ستكون بطيئة.\n\n"
                    "إن استمر: جرّب إنترنت آخر، أو أضف بروكسي في <code>.env</code>:\n"
                    "<code>PROXY=socks5://127.0.0.1:1080</code>",
                    parse_mode=ParseMode.HTML)
            except Exception:
                pass
        return

    if isinstance(err, Conflict):
        log.error("نسخة أخرى من البوت تعمل بنفس التوكن — أوقف إحداهما.")
        return

    log.error("استثناء أثناء معالجة التحديث", exc_info=err)

    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ حدث خطأ غير متوقع. جرّب مجدداً — وإن تكرر أبلغ الأدمن.")
    except Exception:
        pass

    try:
        if ADMIN_ID:
            text = html.escape(str(err))[:1200]
            await ctx.bot.send_message(
                ADMIN_ID, f"🐞 <b>خطأ في البوت</b>\n<code>{text}</code>",
                parse_mode=ParseMode.HTML)
    except Exception:
        pass


# ═══════════════════════════ التهيئة ═══════════════════════════
async def post_init(app: Application):
    cleanup_orphans()

    await app.bot.set_my_commands([
        BotCommand("start", "القائمة الرئيسية"),
        BotCommand("help", "المساعدة ودليل الجودات"),
        BotCommand("platforms", "المنصات المدعومة"),
        BotCommand("me", "حسابي وحدودي"),
        BotCommand("sub", "خطط الاشتراك"),
        BotCommand("trial", "🎁 تجربة مجانية ٢٤ ساعة"),
        BotCommand("invite", "🎟️ ادعُ أصدقاءك واربح أياماً"),
        BotCommand("top", "🏆 لوحة المتصدّرين"),
        BotCommand("speed", "سرعة السيرفر"),
    ])

    scheduler.add_job(check_expiries, 'interval', hours=6, args=[app.bot],
                      id='expiry', replace_existing=True)
    scheduler.add_job(cleanup_orphans, 'interval', hours=2,
                      id='cleanup', replace_existing=True)
    scheduler.start()

    # فحص الأدوات وتنبيه الأدمن إن نقص شيء
    ff = media_tools.has_ffmpeg()
    js = media_tools.has_js_runtime()
    pot = media_tools.has_pot()

    log.info("ffmpeg=%s | deno=%s | pot=%s | upload_limit=%sMB",
             ff, js, pot, TG_UPLOAD_LIMIT_MB)

    if pot:
        import asyncio
        asyncio.create_task(asyncio.to_thread(media_tools.warm_pot_cache))

    if not (ff and js) and ADMIN_ID:
        try:
            await app.bot.send_message(
                ADMIN_ID,
                "⚠️ <b>البوت يعمل لكن ينقصه أدوات</b>\n\n"
                + media_tools.status_text()
                + "\n\n🔧 أرسل /installtools للتثبيت التلقائي",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass

    try:
        me = await app.bot.get_me()
        from utils import health
        health.set_ready(f"@{me.username}")
    except Exception:
        pass

    print("=" * 55)
    print("🤖 البوت يعمل الآن")
    print(f"   ffmpeg : {'✅' if ff else '❌'}")
    print(f"   Deno   : {'✅' if js else '❌'}  (لازم ليوتيوب)")
    print(f"   PO Token: {'✅' if pot else '⚠️'}")
    print(f"   حد الرفع: {TG_UPLOAD_LIMIT_MB} MB"
          + ("  (Local API)" if USING_LOCAL_API else "  (Bot API الرسمي)"))
    print("=" * 55)


async def post_shutdown(app: Application):
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
    except Exception:
        pass
    cleanup_orphans()
    log.info("تم إيقاف البوت")


# ═══════════════════════════ التسجيل ═══════════════════════════
def build_app():
    if not BOT_TOKEN:
        sys.exit("❌ BOT_TOKEN غير موجود في ملف .env")
    if not ADMIN_IDS:
        log.warning("⚠️ ADMIN_ID غير مضبوط — لن تصل إشعارات الدفع لأحد")

    builder = (ApplicationBuilder()
               .token(BOT_TOKEN)
               .defaults(Defaults(parse_mode=None, block=False))
               .concurrent_updates(True)
               .connect_timeout(30).read_timeout(60)
               .write_timeout(120).pool_timeout(60)
               .connection_pool_size(32)
               .get_updates_connect_timeout(30)
               .get_updates_read_timeout(50)
               .get_updates_pool_timeout(30)
               .post_init(post_init)
               .post_shutdown(post_shutdown))

    if USING_LOCAL_API:
        builder = builder.base_url(LOCAL_BOT_API)
        log.info("يستخدم Local Bot API: %s", LOCAL_BOT_API)

    app = builder.build()

    # ── الأوامر ──
    app.add_handler(CommandHandler("start", start.start))
    app.add_handler(CommandHandler("help", start.help_cmd))
    app.add_handler(CommandHandler("platforms", start.platforms_cmd))
    app.add_handler(CommandHandler("me", start.me_cmd))
    app.add_handler(CommandHandler("speed", start.speed_cmd))
    app.add_handler(CommandHandler(["sub", "plans"], subscription.subscription_menu))

    # ── أوامر الأدمن ──
    app.add_handler(CommandHandler("admin", admin.admin_panel))
    app.add_handler(CommandHandler("stats", admin.stats_cmd))
    app.add_handler(CommandHandler("health", admin.health_cmd))
    app.add_handler(CommandHandler("activate", admin.activate_cmd))
    app.add_handler(CommandHandler("revoke", admin.revoke_cmd))
    app.add_handler(CommandHandler(["ban", "unban"], admin.ban_cmd))
    app.add_handler(CommandHandler("user", admin.user_cmd))
    app.add_handler(CommandHandler("broadcast", admin.broadcast_cmd))
    app.add_handler(CommandHandler("pending", admin.pending_cmd))
    app.add_handler(CommandHandler("cookies", admin.cookies_cmd))
    app.add_handler(CommandHandler("installtools", admin.install_tools_cmd))
    app.add_handler(CommandHandler("clearcache", admin.clearcache_cmd))
    app.add_handler(CommandHandler("errors", admin.errors_cmd))

    # ── ميزات النمو ──
    app.add_handler(CommandHandler("trial", growth.trial_cmd))
    app.add_handler(CommandHandler(["invite", "ref"], growth.invite_cmd))
    app.add_handler(CommandHandler("top", growth.leaderboard_cmd))

    # ── الأزرار ──
    # الترتيب مهم: الأنماط الأخص أولاً
    app.add_handler(CallbackQueryHandler(download.on_quality,
                                         pattern=r'^(dl_|df_|cx_|up_|big$|noop$)'))
    app.add_handler(CallbackQueryHandler(download.back_to_qualities, pattern=r'^bk_'))
    app.add_handler(CallbackQueryHandler(admin.payment_action, pattern=r'^pay_(ok|no)_\d+$'))
    app.add_handler(CallbackQueryHandler(admin.admin_router, pattern=r'^a_'))
    app.add_handler(CallbackQueryHandler(payment.show_method, pattern=r'^pm_'))
    app.add_handler(CallbackQueryHandler(payment.show_payment, pattern=r'^buy_'))
    app.add_handler(CallbackQueryHandler(growth.trial_cmd, pattern=r'^trial$'))
    app.add_handler(CallbackQueryHandler(start.menu_router, pattern=r'^m_'))

    # ── الوضع المضمّن (داخل أي محادثة) ──
    app.add_handler(InlineQueryHandler(inline.inline_query))

    # ── التنزيل المتعدد: /go_<token> ──
    app.add_handler(MessageHandler(
        filters.Regex(r'^/go_[0-9a-f]+') & filters.TEXT, download.go_cmd))

    # ── الرسائل ──
    # ملف كوكيز من الأدمن
    app.add_handler(MessageHandler(
        filters.Document.ALL & filters.User(list(ADMIN_IDS) or [0]),
        admin.receive_cookie_file))
    # إيصال دفع
    app.add_handler(MessageHandler(filters.PHOTO, payment.receive_proof))
    # أي نص: نبحث فيه عن رابط
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, download.handle_plain_text))

    app.add_error_handler(on_error)
    return app


def main():
    # قفل النسخة الواحدة — تيليجرام يسمح باتصال getUpdates واحد لكل توكن،
    # ونسختان تتنازعان إلى الأبد بخطأ Conflict فلا تعمل أي منهما.
    from utils import single_instance
    force = '--force' in sys.argv
    ok, msg = single_instance.acquire(
        os.path.join(os.path.dirname(LOG_PATH), 'bot.lock'), kill_stale=force)

    if not ok:
        print()
        print("=" * 55)
        print("⛔ لم يبدأ البوت")
        print("=" * 55)
        print(msg)
        print("=" * 55)
        sys.exit(1)

    log.info(msg)

    if PORT:
        from utils import health
        health.start(PORT)

    try:
        app = build_app()
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    finally:
        single_instance.release()


if __name__ == '__main__':
    main()
