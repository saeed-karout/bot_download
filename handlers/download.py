# -*- coding: utf-8 -*-
"""المعالج الرئيسي: رابط → فحص → قائمة جودات → تنزيل بتقدّم حي → إرسال."""
import os
import time
import asyncio
import logging
import secrets

from telegram import Update, InputFile
from telegram.constants import ChatAction
from telegram.error import TelegramError, BadRequest
from telegram.ext import ContextTypes

from config import (MAX_DOWNLOAD_SECONDS, MAX_CONCURRENT_DOWNLOADS,
                    MAX_PER_USER_CONCURRENT, PROGRESS_EDIT_INTERVAL,
                    TG_UPLOAD_LIMIT, TG_UPLOAD_LIMIT_MB, USING_LOCAL_API)
from database import log_download, cache_get, cache_put
from services import downloader, extractor, errors
from services import platforms as P
from services.extractor import ExtractError
from services.tier_manager import (can_download, commit_download, get_plan,
                                   max_height, max_bytes, max_duration,
                                   allows_mp3, get_active_tier)
from utils.helpers import (first_url, extract_urls, esc, human_size, human_time,
                           human_duration, progress_bar, shorten, is_safe_url,
                           quality_label)
from utils.keyboards import quality_menu, back_menu

log = logging.getLogger(__name__)

# بوابة التزامن: تمنع إغراق السيرفر
_global_sem = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
_user_active = {}          # user_id → عدد العمليات الجارية
_sessions = {}             # token → معلومات الجلسة
SESSION_TTL = 30 * 60


def _purge_sessions():
    now = time.time()
    for tok in [t for t, s in _sessions.items() if now - s['at'] > SESSION_TTL]:
        _sessions.pop(tok, None)


def _new_session(user_id, info):
    _purge_sessions()
    # hex فقط — لأن callback_data يُقسَّم على '_' وtoken_urlsafe قد يحوي '_'
    token = secrets.token_hex(5)
    _sessions[token] = {'user_id': user_id, 'info': info, 'at': time.time()}
    return token


def _get_session(token, user_id):
    s = _sessions.get(token)
    if not s or s['user_id'] != user_id:
        return None
    if time.time() - s['at'] > SESSION_TTL:
        _sessions.pop(token, None)
        return None
    return s


# ═══════════════════════════════════════════════════════════════
#  1) استقبال الرابط  →  عرض الجودات
# ═══════════════════════════════════════════════════════════════
async def handle_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    url = first_url(update.message.text)
    if not url:
        return

    from database import add_user
    add_user(user.id, user.username, user.first_name)

    if not is_safe_url(url):
        await update.message.reply_text("🚫 هذا الرابط مرفوض لأسباب أمنية.")
        return

    ok, err = can_download(user.id)
    if not ok:
        await update.message.reply_text(err, parse_mode='HTML')
        return

    plat = P.detect(url)
    msg = await update.message.reply_text(
        f"🔍 <b>جاري فحص الرابط...</b>\n{plat.label}",
        parse_mode='HTML')

    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(extractor.probe, url),
            timeout=extractor.PROBE_TIMEOUT + 30)
    except asyncio.TimeoutError:
        await msg.edit_text(
            "⏳ <b>استغرق الفحص وقتاً طويلاً</b>\nالمنصة بطيئة الآن — أعد المحاولة.",
            parse_mode='HTML')
        log_download(user.id, plat.key, url, '', '', '', ok=False, error='probe timeout')
        return
    except ExtractError as e:
        await msg.edit_text(errors.friendly(e.last, plat), parse_mode='HTML')
        log_download(user.id, plat.key, url, '', '', '', ok=False, error=e.joined()[:400])
        return
    except Exception as e:
        await msg.edit_text(errors.friendly(e, plat), parse_mode='HTML')
        log_download(user.id, plat.key, url, '', '', '', ok=False, error=str(e)[:400])
        return

    if info.live:
        await msg.edit_text(
            "🔴 <b>هذا بث مباشر</b>\nلا يمكن تنزيله أثناء البث — انتظر انتهاءه.",
            parse_mode='HTML')
        return

    # سقف المدة حسب الخطة
    dur_cap = max_duration(user.id)
    if dur_cap and info.duration and info.duration > dur_cap:
        await msg.edit_text(
            f"⏱️ <b>الفيديو طويل جداً لخطتك</b>\n\n"
            f"مدته: {human_duration(info.duration)}\n"
            f"الحد المسموح: {human_duration(dur_cap)}\n\n"
            f"💎 رقِّ حسابك: /sub", parse_mode='HTML')
        return

    token = _new_session(user.id, info)
    speed = extractor.current_speed_bps()
    await msg.edit_text(
        _info_text(info, user.id, speed),
        parse_mode='HTML',
        reply_markup=quality_menu(
            info.options, token, speed,
            max_height=max_height(user.id),
            allow_mp3=allows_mp3(user.id),
            max_bytes=max_bytes(user.id)),
        disable_web_page_preview=True)


def _info_text(info, user_id, speed):
    """بطاقة المعلومات فوق أزرار الجودة."""
    plan = get_plan(user_id)
    lines = [
        f"{info.platform.label}",
        f"🎬 <b>{esc(shorten(info.title, 70))}</b>",
    ]
    if info.uploader:
        lines.append(f"👤 {esc(shorten(info.uploader, 40))}")
    if info.duration:
        lines.append(f"⏱️ المدة: {human_duration(info.duration)}")
    if info.is_playlist:
        lines.append(f"📚 قائمة تحتوي {info.entries} عنصراً (سيُنزَّل الأول)")

    vids = [o for o in info.options if not o.is_audio]
    best = max((o.height for o in vids), default=0)
    if best:
        lines.append(f"📺 أعلى جودة في المصدر: <b>{best}p</b> ({quality_label(best)})")

    lines += [
        "",
        f"⚡ سرعة السيرفر الحالية: <b>{human_size(speed)}/ث</b>",
        f"📤 حد الإرسال: <b>{TG_UPLOAD_LIMIT_MB} MB</b>",
        f"💎 خطتك: {plan['emoji']} {plan['name']}"
        + ("" if not plan['max_height'] else f" — حتى {plan['max_height']}p"),
    ]

    # تنبيه صريح عندما يفوت المستخدمَ جودات موجودة فعلاً في هذا الفيديو
    cap = plan['max_height']
    missed = [o.height for o in vids if cap and o.height > cap]
    if missed:
        lines += [
            "",
            f"🔒 <b>يفوتك {len(missed)} جودة أعلى</b> في هذا الفيديو "
            f"(حتى <b>{max(missed)}p</b>) — اضغط أي زر مقفل لرؤية التفاصيل.",
        ]

    lines += [
        "",
        "👇 <b>اختر الجودة المطلوبة:</b>",
        "<i>(الأزرار تعرض: الدقة • الحجم • الزمن المتوقع)</i>",
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  2) اختيار الجودة  →  التنزيل
# ═══════════════════════════════════════════════════════════════
async def on_quality(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    data = query.data

    if data in ('big', 'noop'):
        await query.answer(
            f"📦 هذه الجودة أكبر من حد الإرسال ({TG_UPLOAD_LIMIT_MB} ميغابايت).\n\n"
            f"تيليجرام يمنع البوتات من رفع ملفات أكبر من ذلك.\n\n"
            f"✅ الحل: اختر جودة أقل من القائمة.",
            show_alert=True)
        return

    await query.answer()

    if data.startswith('cx_'):
        _sessions.pop(data[3:], None)
        await query.edit_message_text("❌ أُلغيت العملية.")
        return

    if data.startswith('up_'):
        await _show_upgrade_offer(update, ctx, data[3:])
        return

    as_document = data.startswith('df_')
    if as_document:
        token, key = data[3:], None
    else:
        rest = data[3:]
        token, _, key = rest.partition('_')

    session = _get_session(token, user.id)
    if not session:
        await query.edit_message_text(
            "⏰ انتهت صلاحية هذه القائمة.\nأرسل الرابط من جديد.")
        return

    info = session['info']
    option = info.find(key) if key else info.best_under(max_height(user.id))
    if option is None:
        await query.answer("خيار غير معروف", show_alert=True)
        return

    # فحص الحد اليومي مجدداً (قد يكون استهلكه في نافذة أخرى)
    ok, err = can_download(user.id)
    if not ok:
        await query.edit_message_text(err, parse_mode='HTML')
        return

    if _user_active.get(user.id, 0) >= MAX_PER_USER_CONCURRENT:
        await query.answer("⏳ لديك تنزيل جارٍ — انتظر انتهاءه.", show_alert=True)
        return

    _sessions.pop(token, None)
    await _run_download(update, ctx, info, option, as_document)


async def _show_upgrade_offer(update, ctx, payload):
    """عرض ترقية مبني على هذا الفيديو تحديداً — لا إعلان عام.

    نُري المستخدم بالضبط الجودة التي يفوتها وأي خطة تفتحها.
    """
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    from config import PLANS, TIER_ORDER
    from services.tier_manager import get_active_tier

    query = update.callback_query
    user = update.effective_user
    token, _, key = payload.partition('_')

    session = _get_session(token, user.id)
    if not session:
        await query.edit_message_text("⏰ انتهت صلاحية القائمة.\nأرسل الرابط من جديد.")
        return

    info = session['info']
    option = info.find(key)
    if not option:
        await query.answer()
        return

    current = get_active_tier(user.id)
    cur_plan = PLANS[current]

    # أرخص خطة تفتح هذه الجودة فعلاً
    target = None
    for t in TIER_ORDER:
        p = PLANS[t]
        if p['price'] > cur_plan['price'] and (not p['max_height']
                                               or p['max_height'] >= option.height):
            target = t
            break
    if not target:
        target = TIER_ORDER[-1]

    tp = PLANS[target]
    speed = extractor.current_speed_bps()
    unlocked = [o for o in info.options
                if not o.is_audio and o.height > (cur_plan['max_height'] or 0)
                and (not tp['max_height'] or o.height <= tp['max_height'])]

    lines = [
        f"🔒 <b>{option.name} غير متاحة في خطتك</b>",
        "",
        f"🎬 {esc(shorten(info.title, 55))}",
        "",
        f"خطتك الآن: <b>{cur_plan['emoji']} {cur_plan['name']}</b> — حتى "
        f"<b>{cur_plan['max_height']}p</b>",
        f"هذا الفيديو متاح حتى <b>{max(o.height for o in info.options if not o.is_audio)}p</b>",
        "",
        f"<b>{tp['emoji']} خطة {tp['name']} تفتح لك:</b>",
    ]

    for o in unlocked[:4]:
        lines.append(f"  ✅ {o.button_text(speed)}")

    lines += [
        f"  ✅ {'بلا حدود ♾️' if not tp['daily_limit'] else str(tp['daily_limit']) + ' تنزيل'} يومياً"
        f" <i>(بدل {cur_plan['daily_limit']})</i>",
    ]
    if tp['max_duration'] == 0:
        lines.append("  ✅ فيديوهات بلا حد للمدة")
    if tp['priority'] > cur_plan['priority']:
        lines.append("  ✅ أولوية في طابور التنزيل")

    lines += [
        "",
        f"💰 <b>{tp['price']}$</b> فقط لمدة <b>{tp['days']} يوم</b>",
    ]

    rows = [[B(f"💎 ترقية إلى {tp['name']} — {tp['price']}$", callback_data=f"buy_{target}")]]

    # التجربة المجانية: أقوى محفّز لمن لم يجرّب بعد
    from config import TRIAL_ENABLED
    from database import trial_used
    if TRIAL_ENABLED and current == 'free' and not trial_used(user.id):
        rows.append([B("🎁 جرّب مجاناً ٢٤ ساعة", callback_data='trial')])
        lines += ["", "🎁 أو جرّب كل المزايا <b>مجاناً ٢٤ ساعة</b> — مرة واحدة."]

    rows.append([B("🎟️ ادعُ أصدقاءك واربح أياماً مجانية", callback_data='m_ref')])
    rows.append([B(f"🔙 رجوع للجودات المتاحة", callback_data=f"bk_{token}")])

    await query.edit_message_text("\n".join(lines), parse_mode='HTML',
                                  reply_markup=M(rows))


async def back_to_qualities(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """رجوع من عرض الترقية إلى قائمة الجودات نفسها."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    token = query.data[3:]

    session = _get_session(token, user.id)
    if not session:
        await query.edit_message_text("⏰ انتهت صلاحية القائمة.\nأرسل الرابط من جديد.")
        return

    info = session['info']
    speed = extractor.current_speed_bps()
    await query.edit_message_text(
        _info_text(info, user.id, speed), parse_mode='HTML',
        reply_markup=quality_menu(
            info.options, token, speed,
            max_height=max_height(user.id),
            allow_mp3=allows_mp3(user.id),
            max_bytes=max_bytes(user.id)),
        disable_web_page_preview=True)


async def _run_download(update, ctx, info, option, as_document):
    user = update.effective_user
    query = update.callback_query
    chat_id = query.message.chat_id
    plat = info.platform

    # ── الكاش: نفس الرابط بنفس الجودة يُرسل فوراً بلا تنزيل ──
    ckey = f"{plat.key}|{info.url}|{option.key}|{'doc' if as_document else 'auto'}"
    cached = cache_get(ckey)
    if cached and cached.get('file_id'):
        try:
            await _send_cached(ctx, chat_id, cached, info)
            await query.edit_message_text(
                f"⚡ <b>تم الإرسال فوراً من الذاكرة المؤقتة</b>\n"
                f"🎬 {esc(shorten(info.title, 60))}", parse_mode='HTML')
            commit_download(user.id, cached.get('size_bytes') or 0)
            log_download(user.id, plat.key, info.url, info.title, option.name,
                         cached.get('kind'), cached.get('size_bytes') or 0,
                         0, 'cache', True)
            return
        except Exception as e:
            log.info("فشل إرسال الكاش، سنعيد التنزيل: %s", e)

    _user_active[user.id] = _user_active.get(user.id, 0) + 1
    started = time.time()
    out_dir = None
    result = None

    try:
        async with _global_sem:
            await query.edit_message_text(
                f"⏳ <b>جاري التنزيل...</b>\n"
                f"🎬 {esc(shorten(info.title, 55))}\n"
                f"📥 الجودة: {option.name}",
                parse_mode='HTML')

            progress = _ProgressReporter(ctx, chat_id, query.message.message_id,
                                         info, option)
            loop = asyncio.get_running_loop()

            def hook(d):
                progress.push(d, loop)

            try:
                result, out_dir = await asyncio.wait_for(
                    asyncio.to_thread(
                        downloader.download,
                        info.url, user.id,
                        max_height=option.height,
                        want_audio=option.is_audio,
                        progress_cb=hook,
                        playlist=False,
                        max_bytes=max_bytes(user.id)),
                    timeout=MAX_DOWNLOAD_SECONDS)
            except asyncio.TimeoutError:
                raise downloader.DownloadError(
                    f"تجاوز التنزيل المهلة ({MAX_DOWNLOAD_SECONDS // 60} دقيقة)")

        # ── فحص الحجم قبل الرفع ──
        size = os.path.getsize(result.path)
        limit = max_bytes(user.id)
        if size > limit:
            await query.edit_message_text(
                f"📦 <b>الملف أكبر من الحد المسموح</b>\n\n"
                f"حجمه: <b>{human_size(size)}</b>\n"
                f"الحد: <b>{human_size(limit)}</b>\n\n"
                + ("💎 رقِّ حسابك لحد أكبر: /sub"
                   if limit < TG_UPLOAD_LIMIT else
                   "اختر جودة أقل من القائمة."),
                parse_mode='HTML')
            log_download(user.id, plat.key, info.url, info.title, option.name,
                         result.kind, size, 0, result.engine, False, 'too large')
            return

        # ── الرفع ──
        await query.edit_message_text(
            f"📤 <b>جاري الرفع إلى تيليجرام...</b>\n"
            f"🎬 {esc(shorten(info.title, 55))}\n"
            f"📦 {human_size(size)}", parse_mode='HTML')

        sent = await _send_result(ctx, chat_id, result, info, option,
                                  as_document, out_dir)

        elapsed = time.time() - started
        commit_download(user.id, size)
        log_download(user.id, plat.key, info.url, info.title, option.name,
                     result.kind, size, result.duration_ms, result.engine, True)

        # خزّن file_id لإعادة الإرسال الفوري لاحقاً
        fid = _extract_file_id(sent)
        if fid:
            cache_put(ckey, fid, result.kind, info.title, size)

        avg = size / elapsed if elapsed > 0 else 0
        await query.edit_message_text(
            f"✅ <b>تم بنجاح</b>\n\n"
            f"🎬 {esc(shorten(info.title, 60))}\n"
            f"📥 الجودة: <b>{option.name}</b>\n"
            f"📦 الحجم: <b>{human_size(size)}</b>\n"
            f"⏱️ استغرق: <b>{human_time(elapsed)}</b>\n"
            f"⚡ السرعة: <b>{human_size(avg)}/ث</b>",
            parse_mode='HTML')

        # مكافأة الإحالة عند أول تنزيل ناجح
        try:
            from handlers.growth import reward_referral
            await reward_referral(ctx, user.id)
        except Exception as e:
            log.debug("تعذّرت مكافأة الإحالة: %s", e)

        await _maybe_upsell(ctx, chat_id, user.id, info, option)

    except downloader.DownloadError as e:
        await _fail(query, e, plat)
        log_download(user.id, plat.key, info.url, info.title, option.name,
                     '', 0, 0, 'multi', False, str(e)[:400])
    except TelegramError as e:
        await _fail(query, f"تيليجرام رفض الإرسال: {e}", plat)
        log_download(user.id, plat.key, info.url, info.title, option.name,
                     '', 0, 0, 'telegram', False, str(e)[:400])
    except Exception as e:
        log.exception("خطأ غير متوقع في التنزيل")
        await _fail(query, e, plat)
        log_download(user.id, plat.key, info.url, info.title, option.name,
                     '', 0, 0, 'unknown', False, str(e)[:400])
    finally:
        _user_active[user.id] = max(0, _user_active.get(user.id, 1) - 1)
        if out_dir:
            downloader.cleanup(out_dir)


async def _maybe_upsell(ctx, chat_id, user_id, info, option):
    """اقتراح ترقية بعد التنزيل — بشرطين حتى لا يكون إزعاجاً:
    أن يكون المستخدم مجانياً فعلاً، وأن يكون قد فوّت جودة أعلى في هذا الفيديو.
    ويظهر مرة كل عدة تنزيلات فقط.
    """
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    from config import PLANS, TRIAL_ENABLED
    from database import downloads_today, trial_used
    from services.tier_manager import get_active_tier

    try:
        if get_active_tier(user_id) != 'free':
            return

        cap = PLANS['free']['max_height']
        better = [o.height for o in info.options if not o.is_audio and o.height > cap]
        if not better:
            return

        # كل تنزيل ثالث فقط
        if downloads_today(user_id) % 3 != 0:
            return

        rows = []
        if TRIAL_ENABLED and not trial_used(user_id):
            rows.append([B("🎁 جرّب VIP مجاناً ٢٤ ساعة", callback_data='trial')])
        rows.append([B("💎 عرض الخطط", callback_data='m_sub')])
        rows.append([B("🎟️ اربح أياماً بدعوة صديق", callback_data='m_ref')])

        await ctx.bot.send_message(
            chat_id,
            f"💡 <b>هل تعلم؟</b>\n\n"
            f"هذا الفيديو كان متاحاً بجودة <b>{max(better)}p</b>، "
            f"لكن خطتك المجانية تسمح حتى <b>{cap}p</b> فقط.",
            parse_mode='HTML', reply_markup=M(rows))
    except Exception as e:
        log.debug("تعذّر عرض الترقية: %s", e)


async def _fail(query, err, plat):
    try:
        await query.edit_message_text(errors.friendly(err, plat), parse_mode='HTML')
    except BadRequest:
        pass


# ═══════════════════════════════════════════════════════════════
#  تقرير التقدّم الحي
# ═══════════════════════════════════════════════════════════════
class _ProgressReporter:
    """يحدّث رسالة التقدّم كل بضع ثوانٍ — من داخل خيط yt-dlp بأمان."""

    def __init__(self, ctx, chat_id, message_id, info, option):
        self.ctx = ctx
        self.chat_id = chat_id
        self.message_id = message_id
        self.info = info
        self.option = option
        self.last = 0.0
        self.last_text = ''

    def push(self, d, loop):
        if d.get('status') != 'downloading':
            return
        now = time.time()
        if now - self.last < PROGRESS_EDIT_INTERVAL:
            return
        self.last = now

        done = d.get('downloaded_bytes') or 0
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        speed = d.get('speed') or 0
        eta = d.get('eta') or 0

        if total:
            frac = min(done / total, 1.0)
            head = f"{progress_bar(frac)}  {frac * 100:.0f}%"
            body = f"{human_size(done)} / {human_size(total)}"
        else:
            head = "⏳ جاري التنزيل..."
            body = human_size(done)

        lines = [
            "⏳ <b>جاري التنزيل</b>",
            f"🎬 {esc(shorten(self.info.title, 50))}",
            f"📥 {self.option.name}",
            "",
            f"<code>{head}</code>",
            f"📦 {body}",
        ]
        if speed:
            lines.append(f"⚡ {human_size(speed)}/ث")
        if eta:
            lines.append(f"⏱️ يتبقى ~{human_time(eta)}")
        text = "\n".join(lines)

        if text == self.last_text:
            return
        self.last_text = text

        asyncio.run_coroutine_threadsafe(self._edit(text), loop)

    async def _edit(self, text):
        try:
            await self.ctx.bot.edit_message_text(
                chat_id=self.chat_id, message_id=self.message_id,
                text=text, parse_mode='HTML')
        except Exception:
            pass   # رسالة محذوفة أو تعديل متكرر — نتجاهل


# ═══════════════════════════════════════════════════════════════
#  الإرسال
# ═══════════════════════════════════════════════════════════════
TIMEOUTS = dict(read_timeout=900, write_timeout=900,
                connect_timeout=90, pool_timeout=900)


def _extract_file_id(msg):
    if not msg:
        return None
    for attr in ('video', 'audio', 'document', 'animation'):
        obj = getattr(msg, attr, None)
        if obj:
            return obj.file_id
    if getattr(msg, 'photo', None):
        return msg.photo[-1].file_id
    return None


async def _send_cached(ctx, chat_id, cached, info):
    kind = cached.get('kind')
    fid = cached['file_id']
    cap = f"🎬 {esc(shorten(info.title, 80))}"
    if kind == 'audio':
        return await ctx.bot.send_audio(chat_id, fid, caption=cap, parse_mode='HTML')
    if kind == 'photo':
        return await ctx.bot.send_photo(chat_id, fid, caption=cap, parse_mode='HTML')
    if kind == 'video':
        return await ctx.bot.send_video(chat_id, fid, caption=cap, parse_mode='HTML',
                                        supports_streaming=True)
    return await ctx.bot.send_document(chat_id, fid, caption=cap, parse_mode='HTML')


async def _send_result(ctx, chat_id, result, info, option, as_document, out_dir):
    path = result.path
    kind = 'document' if as_document else result.kind
    title = shorten(info.title or result.title, 80)
    caption = f"🎬 <b>{esc(title)}</b>\n📥 {option.name} • {human_size(result.size)}"

    action = {'video': ChatAction.UPLOAD_VIDEO, 'audio': ChatAction.UPLOAD_VOICE,
              'photo': ChatAction.UPLOAD_PHOTO}.get(kind, ChatAction.UPLOAD_DOCUMENT)
    try:
        await ctx.bot.send_chat_action(chat_id, action)
    except Exception:
        pass

    if kind == 'audio':
        with open(path, 'rb') as f:
            return await ctx.bot.send_audio(
                chat_id, InputFile(f, filename=os.path.basename(path)),
                caption=caption, parse_mode='HTML',
                title=title, performer=info.uploader or None,
                duration=result.media_duration or info.duration or None,
                **TIMEOUTS)

    if kind == 'photo':
        with open(path, 'rb') as f:
            return await ctx.bot.send_photo(
                chat_id, f, caption=caption, parse_mode='HTML', **TIMEOUTS)

    if kind == 'video':
        w, h, dur = downloader.probe_dimensions(path)
        thumb = downloader.make_thumbnail(path, out_dir)
        thumb_f = open(thumb, 'rb') if thumb else None
        try:
            with open(path, 'rb') as f:
                return await ctx.bot.send_video(
                    chat_id, InputFile(f, filename=os.path.basename(path)),
                    caption=caption, parse_mode='HTML',
                    width=w or None, height=h or None,
                    duration=dur or result.media_duration or None,
                    thumbnail=thumb_f, supports_streaming=True, **TIMEOUTS)
        finally:
            if thumb_f:
                thumb_f.close()

    with open(path, 'rb') as f:
        return await ctx.bot.send_document(
            chat_id, InputFile(f, filename=os.path.basename(path)),
            caption=caption, parse_mode='HTML', **TIMEOUTS)


# ═══════════════════════════════════════════════════════════════
#  رسالة عندما يرسل المستخدم نصاً بلا رابط
# ═══════════════════════════════════════════════════════════════
async def handle_plain_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    urls = extract_urls(update.message.text)

    if len(urls) > 1:
        await _handle_batch(update, ctx, urls)
        return

    if urls:
        await handle_url(update, ctx)
        return
    await update.message.reply_text(
        "📥 <b>أرسل لي رابطاً وسأنزّله لك</b>\n\n"
        "مثال:\n"
        "<code>https://youtube.com/watch?v=...</code>\n"
        "<code>https://instagram.com/reel/...</code>\n"
        "<code>https://tiktok.com/@user/video/...</code>\n\n"
        "🌐 /platforms — كل المنصات المدعومة\n"
        "ℹ️ /help — المساعدة",
        parse_mode='HTML', reply_markup=back_menu())


# ═══════════════════════════════════════════════════════════════
#  التنزيل المتعدد (عدة روابط في رسالة واحدة)
# ═══════════════════════════════════════════════════════════════
MAX_BATCH = 10


async def _handle_batch(update, ctx, urls):
    """يعالج عدة روابط دفعةً واحدة — ميزة للمشتركين."""
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    from config import PLANS
    from services.tier_manager import get_active_tier

    user = update.effective_user
    from database import add_user
    add_user(user.id, user.username, user.first_name)

    tier = get_active_tier(user.id)
    if not PLANS[tier]['batch']:
        await update.message.reply_text(
            f"📦 <b>وجدتُ {len(urls)} روابط في رسالتك</b>\n\n"
            f"التنزيل المتعدد ميزة للمشتركين — الخطة المجانية تنزّل رابطاً واحداً في كل مرة.\n\n"
            f"سأتعامل مع الرابط الأول الآن 👇",
            parse_mode='HTML',
            reply_markup=M([[B("💎 فعّل التنزيل المتعدد", callback_data='m_sub')]]))
        await handle_url(update, ctx)
        return

    urls = urls[:MAX_BATCH]
    ok, err = can_download(user.id)
    if not ok:
        await update.message.reply_text(err, parse_mode='HTML')
        return

    status = await update.message.reply_text(
        f"📦 <b>تنزيل متعدد</b>\n"
        f"وجدتُ <b>{len(urls)}</b> روابط — جاري فحصها...",
        parse_mode='HTML')

    lines = []
    for i, u in enumerate(urls, 1):
        plat = P.detect(u)
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(extractor.probe, u), timeout=45)
            token = _new_session(user.id, info)
            opt = info.best_under(max_height(user.id))
            lines.append(
                f"{i}. {plat.emoji} <b>{esc(shorten(info.title, 38))}</b>\n"
                f"    ▸ /go_{token}  ({opt.name if opt else '—'})")
        except Exception as e:
            lines.append(f"{i}. {plat.emoji} ❌ <i>تعذّر الفحص</i>")
            log.debug("فشل فحص دفعة: %s", e)

        try:
            await status.edit_text(
                f"📦 <b>تنزيل متعدد</b> — {i}/{len(urls)}\n\n" + "\n".join(lines),
                parse_mode='HTML')
        except Exception:
            pass

    await status.edit_text(
        f"📦 <b>جاهز — {len(urls)} روابط</b>\n\n"
        + "\n".join(lines)
        + "\n\n💡 اضغط أمر <code>/go_...</code> تحت أي رابط لاختيار جودته وتنزيله.",
        parse_mode='HTML')


async def go_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """‎/go_<token> — يفتح قائمة الجودات لعنصر من دفعة."""
    user = update.effective_user
    token = (update.message.text or '').strip().split('@')[0].replace('/go_', '', 1)

    session = _get_session(token, user.id)
    if not session:
        await update.message.reply_text(
            "⏰ انتهت صلاحية هذا العنصر — أعد إرسال الرابط.")
        return

    info = session['info']
    speed = extractor.current_speed_bps()
    await update.message.reply_text(
        _info_text(info, user.id, speed), parse_mode='HTML',
        reply_markup=quality_menu(
            info.options, token, speed,
            max_height=max_height(user.id),
            allow_mp3=allows_mp3(user.id),
            max_bytes=max_bytes(user.id)),
        disable_web_page_preview=True)
