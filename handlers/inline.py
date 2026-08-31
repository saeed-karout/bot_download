# -*- coding: utf-8 -*-
"""الوضع المضمّن (Inline) — استخدام البوت داخل أي محادثة.

يكتب المستخدم ‎@BotName ثم الرابط في أي دردشة، فتظهر له الجودات المتاحة.
هذه أقوى قناة نمو: كل استخدام يعرض اسم البوت لكل من في المحادثة.
"""
import logging
import asyncio

from telegram import (Update, InlineQueryResultArticle, InputTextMessageContent,
                      InlineKeyboardButton as B, InlineKeyboardMarkup as M)
from telegram.ext import ContextTypes

from services import extractor
from services import platforms as P
from utils.helpers import first_url, esc, shorten, human_size, human_duration

log = logging.getLogger(__name__)

CACHE_SECONDS = 300


async def inline_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    text = (query.query or '').strip()
    me = await ctx.bot.get_me()
    open_bot = M([[B("🚀 افتح البوت وحمّل", url=f"https://t.me/{me.username}")]])

    if not text:
        await query.answer(
            [InlineQueryResultArticle(
                id='hint',
                title='📥 الصق رابط فيديو هنا',
                description='يوتيوب · تيك توك · إنستغرام · وأكثر من ١٨٠٠ موقع',
                input_message_content=InputTextMessageContent(
                    f"🤖 بوت تنزيل الفيديوهات\n"
                    f"يوتيوب · تيك توك · إنستغرام · سناب شات وأكثر\n\n"
                    f"👈 https://t.me/{me.username}"),
                reply_markup=open_bot,
            )],
            cache_time=CACHE_SECONDS, is_personal=False)
        return

    url = first_url(text)
    if not url:
        await query.answer(
            [InlineQueryResultArticle(
                id='norul',
                title='⚠️ هذا ليس رابطاً',
                description='الصق رابط منشور كاملاً',
                input_message_content=InputTextMessageContent(
                    f"🤖 جرّب بوت التنزيل: https://t.me/{me.username}"),
                reply_markup=open_bot,
            )],
            cache_time=30, is_personal=True)
        return

    plat = P.detect(url)

    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(extractor.probe, url), timeout=25)
    except Exception as e:
        log.debug("فشل الفحص المضمّن: %s", e)
        await query.answer(
            [InlineQueryResultArticle(
                id='fail',
                title=f'❌ تعذّر قراءة الرابط',
                description='افتح البوت لمحاولة أعمق مع محركات احتياطية',
                input_message_content=InputTextMessageContent(
                    f"🤖 حمّل هذا الرابط عبر البوت:\n{url}\n\n"
                    f"👈 https://t.me/{me.username}"),
                reply_markup=open_bot,
            )],
            cache_time=30, is_personal=True)
        return

    speed = extractor.current_speed_bps()
    vids = [o for o in info.options if not o.is_audio]
    best = max((o.height for o in vids), default=0)

    deep = f"https://t.me/{me.username}?start=dl"
    results = [InlineQueryResultArticle(
        id='main',
        title=f"{plat.emoji} {shorten(info.title, 55)}",
        description=(f"أعلى جودة {best}p"
                     + (f" · {human_duration(info.duration)}" if info.duration else "")
                     + f" · {len(info.options)} خيار متاح"),
        thumbnail_url=info.thumbnail or None,
        input_message_content=InputTextMessageContent(
            f"🎬 <b>{esc(shorten(info.title, 70))}</b>\n"
            f"{plat.emoji} {esc(plat.name)}"
            + (f" · ⏱️ {human_duration(info.duration)}" if info.duration else "")
            + f"\n📺 متاح حتى <b>{best}p</b>\n\n"
            f"🔗 {esc(url)}",
            parse_mode='HTML', disable_web_page_preview=True),
        reply_markup=M([[B("⬇️ حمّل عبر البوت", url=deep)]]),
    )]

    # خيارات الجودة كنتائج منفصلة — معاينة سريعة للأحجام
    for o in vids[-4:][::-1]:
        results.append(InlineQueryResultArticle(
            id=f"q{o.key}",
            title=f"🎬 {o.name} — {human_size(o.filesize)}",
            description=o.button_text(speed),
            input_message_content=InputTextMessageContent(
                f"🎬 <b>{esc(shorten(info.title, 60))}</b>\n"
                f"📥 الجودة: <b>{o.name}</b> · {human_size(o.filesize)}\n\n"
                f"🔗 {esc(url)}",
                parse_mode='HTML', disable_web_page_preview=True),
            reply_markup=M([[B("⬇️ حمّل عبر البوت", url=deep)]]),
        ))

    await query.answer(results, cache_time=CACHE_SECONDS, is_personal=True)
