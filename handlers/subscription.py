# -*- coding: utf-8 -*-
"""عرض خطط الاشتراك."""
from telegram import Update
from telegram.ext import ContextTypes

from config import PLANS, TG_UPLOAD_LIMIT_MB
from services.tier_manager import get_active_tier
from utils.keyboards import plans_menu
from utils.helpers import human_duration


def _limit_text(p):
    return "بلا حدود ♾️" if not p['daily_limit'] else f"{p['daily_limit']} تنزيل/يوم"


def _quality_text(p):
    return "حتى 8K ♾️" if not p['max_height'] else f"حتى {p['max_height']}p"


def _size_text(p):
    if not p['max_file_mb']:
        return f"حتى حد تيليجرام ({TG_UPLOAD_LIMIT_MB} MB)"
    return f"{p['max_file_mb']} MB"


def _duration_text(p):
    return "بلا حدود ♾️" if not p['max_duration'] else human_duration(p['max_duration'])


async def subscription_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current = get_active_tier(user_id)

    lines = ["💎 <b>خطط الاشتراك</b>\n"]

    for key, p in PLANS.items():
        mark = "  ⬅️ <b>خطتك الحالية</b>" if key == current else ""
        price = "مجاناً" if p['price'] == 0 else f"<b>{p['price']}$</b> / {p['days']} يوم"
        lines += [
            f"{p['emoji']} <b>{p['name']}</b> — {price}{mark}",
            f"   🎬 الجودة: {_quality_text(p)}",
            f"   📥 الحد: {_limit_text(p)}",
            f"   📦 حجم الملف: {_size_text(p)}",
            f"   ⏱️ مدة الفيديو: {_duration_text(p)}",
            f"   🎵 MP3: {'✅' if p['mp3'] else '❌'}",
            "",
        ]

    lines += [
        "✨ <b>مزايا الاشتراك المدفوع:</b>",
        "• جودات 1080p و 2K و 4K",
        "• ملفات أكبر وفيديوهات أطول",
        "• أولوية في طابور التنزيل",
        "",
        "👇 اختر خطة للترقية:",
    ]

    text = "\n".join(lines)
    kb = plans_menu()

    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode='HTML', reply_markup=kb)
        except Exception:
            await update.callback_query.message.reply_text(
                text, parse_mode='HTML', reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=kb)
