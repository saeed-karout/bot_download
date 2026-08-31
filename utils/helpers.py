# -*- coding: utf-8 -*-
"""أدوات مساعدة: تنسيق الأحجام والسرعات، استخراج الروابط، تنظيف أسماء الملفات."""
import os
import re
import html
import ipaddress
import unicodedata
from urllib.parse import urlparse

# ═══════════════════════════ الروابط ═══════════════════════════
URL_RE = re.compile(
    r'(?:https?://|www\.)[^\s<>"\'؀-ۿ]+',
    re.IGNORECASE)

# نطاقات معروفة بدون بروتوكول: youtube.com/watch...
BARE_DOMAIN_RE = re.compile(
    r'\b((?:[\w-]+\.)+(?:com|net|org|tv|to|me|io|be|co|app|watch|gg|ru|cc|fm|link|live|xyz|club|video|media|art|is|sh|in|ly))'
    r'(/[^\s<>"\']*)',
    re.IGNORECASE)


def extract_urls(text):
    """يستخرج كل الروابط من نص — بما فيها التي بلا http:// ."""
    if not text:
        return []
    found = []
    for m in URL_RE.finditer(text):
        found.append(m.group(0))
    if not found:
        for m in BARE_DOMAIN_RE.finditer(text):
            found.append(m.group(0))

    out, seen = [], set()
    for u in found:
        u = u.rstrip('.,;:!؟)»]}‏‎')
        if not u.lower().startswith(('http://', 'https://')):
            u = 'https://' + u
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def first_url(text):
    urls = extract_urls(text)
    return urls[0] if urls else None


def is_safe_url(url):
    """يمنع SSRF: لا localhost ولا شبكات داخلية ولا بروتوكولات غريبة."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ('http', 'https'):
        return False
    host = (p.hostname or '').lower()
    if not host:
        return False
    if host in ('localhost', 'localhost.localdomain', '0.0.0.0', 'metadata.google.internal'):
        return False
    if host.endswith('.local') or host.endswith('.internal'):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            return False
    except ValueError:
        pass  # اسم نطاق عادي
    return True


# ═══════════════════════════ أسماء الملفات ═══════════════════════════
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WIN_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


def safe_filename(name, fallback='file', max_len=80):
    """يمنع اختراق المسار (path traversal) ويزيل المحارف الممنوعة."""
    name = os.path.basename(str(name or '')).strip()
    name = unicodedata.normalize('NFKC', name)
    name = _BAD_CHARS.sub('_', name).strip('. ')
    name = re.sub(r'\s+', ' ', name)

    stem, ext = os.path.splitext(name)
    if stem.upper() in _WIN_RESERVED:
        stem = '_' + stem
    stem = stem[:max_len]
    name = (stem + ext[:12]).strip()
    return name or fallback


# ═══════════════════════════ التنسيق ═══════════════════════════
def human_size(n):
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return '—'
    if n <= 0:
        return '—'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return f"{n:.0f} {unit}" if unit in ('B', 'KB') else f"{n:.1f} {unit}"
        n /= 1024.0


def human_speed(bps):
    if not bps or bps <= 0:
        return '—'
    return human_size(bps) + '/ث'


def human_time(seconds):
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError):
        return '—'
    if s <= 0:
        return '—'
    if s < 60:
        return f"{s} ثانية"
    if s < 3600:
        m, sec = divmod(s, 60)
        return f"{m}:{sec:02d} دقيقة"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}"


def human_duration(seconds):
    """مدة الفيديو بصيغة مضغوطة 03:45 أو 1:02:11"""
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError):
        return '—'
    if s <= 0:
        return '—'
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def progress_bar(fraction, width=12):
    try:
        f = min(max(float(fraction or 0), 0.0), 1.0)
    except (TypeError, ValueError):
        f = 0.0
    filled = int(round(f * width))
    return '█' * filled + '░' * (width - filled)


def eta_from_size(size_bytes, speed_bps):
    """تقدير زمن التنزيل بالثواني."""
    if not size_bytes or not speed_bps or speed_bps <= 0:
        return None
    return size_bytes / float(speed_bps)


def esc(text):
    """تهريب HTML — نستخدم parse_mode=HTML في كل الرسائل بدل Markdown
    لأن Markdown ينكسر مع الأسماء التي فيها _ أو *."""
    return html.escape(str(text or ''), quote=False)


def shorten(text, limit=60):
    text = str(text or '').strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


def quality_label(height):
    """يحوّل الارتفاع إلى اسم مألوف: 1080p → Full HD"""
    if not height:
        return ''
    h = int(height)
    if h >= 4320:
        return '8K'
    if h >= 2160:
        return '4K'
    if h >= 1440:
        return '2K'
    if h >= 1080:
        return 'Full HD'
    if h >= 720:
        return 'HD'
    if h >= 480:
        return 'SD'
    return 'منخفضة'
