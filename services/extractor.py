# -*- coding: utf-8 -*-
"""استخراج معلومات الوسائط وبناء قائمة الجودات المتاحة.

المخرَج الرئيسي: MediaInfo يحمل عنواناً ومدةً وقائمة QualityOption،
كل خيار يعرف ارتفاعه وحجمه التقريبي وامتداده — وهذا ما نعرضه للمستخدم.
"""
import time
import logging

import yt_dlp

from config import PROBE_TIMEOUT, PROXY, DEFAULT_SPEED_MBPS
from services import platforms as P
from services import media_tools
from utils.helpers import human_size, human_time, quality_label, eta_from_size

log = logging.getLogger(__name__)

# الارتفاعات التي نعرضها كأزرار
LADDER = [144, 240, 360, 480, 720, 1080, 1440, 2160, 4320]


class QualityOption:
    """خيار جودة واحد يُعرض كزر للمستخدم."""

    def __init__(self, key, height, ext, filesize, fps=None, vcodec=None,
                 acodec=None, note='', is_audio=False, abr=None, needs_merge=False):
        self.key = key                  # مفتاح مختصر للـ callback_data
        self.height = height or 0
        self.ext = ext or 'mp4'
        self.filesize = filesize or 0   # تقديري إن لم يُصرَّح
        self.fps = fps
        self.vcodec = vcodec
        self.acodec = acodec
        self.note = note
        self.is_audio = is_audio
        self.abr = abr
        self.needs_merge = needs_merge

    @property
    def name(self):
        if self.is_audio:
            return f"MP3 {int(self.abr)}k" if self.abr else "MP3"
        if not self.height:
            return "الأفضل تلقائياً"
        fps_tag = f"{int(self.fps)}fps" if self.fps and self.fps >= 50 else ""
        return f"{self.height}p{(' ' + fps_tag) if fps_tag else ''}"

    def button_text(self, speed_bps=None, locked=False):
        """نص الزر: الجودة • الحجم • الزمن المتوقع"""
        if locked:
            return f"🔒 {self.name} — يتطلب ترقية"

        icon = '🎵' if self.is_audio else '🎬'
        parts = [f"{icon} {self.name}"]

        if self.height and not self.is_audio:
            tag = quality_label(self.height)
            if tag:
                parts[0] += f" ({tag})"

        parts.append(human_size(self.filesize) if self.filesize else "حجم غير معلوم")

        eta = eta_from_size(self.filesize, speed_bps)
        if eta and eta >= 1:
            parts.append(f"~{human_time(eta)}")
        elif self.filesize:
            parts.append("~فوري")

        return " • ".join(parts)

    def to_dict(self):
        return {
            'key': self.key, 'height': self.height, 'ext': self.ext,
            'filesize': self.filesize, 'fps': self.fps, 'is_audio': self.is_audio,
            'abr': self.abr, 'needs_merge': self.needs_merge, 'note': self.note,
        }


class MediaInfo:
    def __init__(self, url, platform, title='', duration=0, thumbnail=None,
                 uploader='', options=None, is_playlist=False, entries=0,
                 live=False, raw=None):
        self.url = url
        self.platform = platform
        self.title = title or 'ملف'
        self.duration = duration or 0
        self.thumbnail = thumbnail
        self.uploader = uploader or ''
        self.options = options or []
        self.is_playlist = is_playlist
        self.entries = entries
        self.live = live
        self.raw = raw or {}

    def best_under(self, max_height):
        """أفضل خيار فيديو ضمن سقف الخطة."""
        vids = [o for o in self.options if not o.is_audio]
        if not vids:
            return None
        if max_height:
            allowed = [o for o in vids if o.height and o.height <= max_height]
            if allowed:
                return max(allowed, key=lambda o: (o.height, o.filesize))
        return max(vids, key=lambda o: (o.height, o.filesize))

    def find(self, key):
        for o in self.options:
            if o.key == key:
                return o
        return None


# ═══════════════════════════════════════════════════════════════
def base_opts(url, plat=None):
    """إعدادات yt-dlp المشتركة."""
    plat = plat or P.detect(url)
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'noplaylist': True,
        'socket_timeout': 30,
        'retries': 3,
        'fragment_retries': 5,
        'extractor_retries': 2,
        'concurrent_fragment_downloads': 5,
        'http_chunk_size': 10 * 1024 * 1024,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'geo_bypass': True,
        'http_headers': {
            'User-Agent': P.UA_DESKTOP,
            'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
        },
    }
    # محرك JS + مزوّد PO Token + ffmpeg — بدونها يوتيوب لا يعمل
    for k, v in media_tools.ytdlp_runtime_opts().items():
        if k == 'extractor_args':
            merged = dict(opts.get('extractor_args') or {})
            merged.update(v)
            opts['extractor_args'] = merged
        else:
            opts[k] = v

    opts = _merge(opts, plat.opts or {})

    cookie = plat.cookie_path()
    if cookie:
        opts['cookiefile'] = cookie

    if PROXY:
        opts['proxy'] = PROXY

    return opts


def _merge(base, extra):
    """دمج عميق بسيط للترويسات والوسائط."""
    out = dict(base)
    for k, v in (extra or {}).items():
        if k in ('http_headers', 'extractor_args') and isinstance(v, dict):
            merged = dict(out.get(k) or {})
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


def _estimate_size(fmt, duration):
    """تقدير الحجم عندما لا تصرّح المنصة به — من معدل البت."""
    size = fmt.get('filesize') or fmt.get('filesize_approx')
    if size:
        return int(size)
    tbr = fmt.get('tbr') or 0
    if tbr and duration:
        return int(tbr * 1000 / 8 * duration)
    return 0


def _collect_options(info, has_ffmpeg):
    """يحوّل صيغ yt-dlp إلى قائمة خيارات نظيفة بلا تكرار."""
    duration = info.get('duration') or 0
    formats = info.get('formats') or []

    # ملف واحد بلا صيغ (صورة مباشرة مثلاً)
    if not formats:
        return [QualityOption('best', info.get('height') or 0,
                              info.get('ext') or 'mp4',
                              info.get('filesize') or info.get('filesize_approx') or 0)]

    best_by_h = {}          # ارتفاع → أفضل صيغة
    best_audio = None

    for f in formats:
        vcodec = f.get('vcodec') or 'none'
        acodec = f.get('acodec') or 'none'
        proto = (f.get('protocol') or '')

        # نتجاهل البث الحي المجزّأ غير القابل للتنزيل الفوري
        if 'm3u8' in proto and f.get('is_live'):
            continue

        # ─ صيغ صوت فقط ─
        if vcodec == 'none' and acodec != 'none':
            abr = f.get('abr') or 0
            if best_audio is None or abr > (best_audio.get('abr') or 0):
                best_audio = f
            continue

        if vcodec == 'none':
            continue

        h = f.get('height') or 0
        if not h:
            continue

        # صيغة فيديو-فقط تحتاج دمجاً — لا تصلح بلا ffmpeg
        video_only = (acodec == 'none')
        if video_only and not has_ffmpeg:
            continue

        # نطابق أقرب درجة في السُلّم لتجميع 1078p مع 1080p
        slot = min(LADDER, key=lambda x: abs(x - h))
        cur = best_by_h.get(slot)

        score = (
            _estimate_size(f, duration) > 0,
            0 if video_only else 1,             # نفضّل الصيغ المدمجة أصلاً
            f.get('vcodec', '').startswith('avc'),  # H.264 أوسع توافقاً مع تيليجرام
            f.get('tbr') or 0,
        )
        if cur is None or score > cur['_score']:
            best_by_h[slot] = {'fmt': f, '_score': score, 'slot': slot,
                               'video_only': video_only}

    options = []
    for slot in sorted(best_by_h):
        entry = best_by_h[slot]
        f = entry['fmt']
        options.append(QualityOption(
            key=f"h{slot}",
            height=slot,
            ext=f.get('ext') or 'mp4',
            filesize=_estimate_size(f, duration),
            fps=f.get('fps'),
            vcodec=f.get('vcodec'),
            acodec=f.get('acodec'),
            needs_merge=entry['video_only'],
        ))

    # ─ خيار الصوت ─
    if best_audio is not None and has_ffmpeg:
        abr = best_audio.get('abr') or 128
        est = _estimate_size(best_audio, duration)
        if not est and duration:
            est = int(192 * 1000 / 8 * duration)   # MP3 192k
        options.append(QualityOption(
            key='mp3', height=0, ext='mp3', filesize=est,
            is_audio=True, abr=min(abr, 320) if abr else 192))

    if not options:
        options.append(QualityOption('best', 0, 'mp4', 0))

    return options


# ── ذاكرة فحص قصيرة العمر ──
# فحص يوتيوب يكلّف ~14 ثانية معظمها انتظار شبكة. إعادة إرسال نفس الرابط
# (أو إرساله من عدة مستخدمين) لا يجب أن تدفع الثمن مرتين.
_probe_cache = {}
PROBE_CACHE_TTL = 600


def _cache_get(url):
    entry = _probe_cache.get(url)
    if not entry:
        return None
    if time.time() - entry[0] > PROBE_CACHE_TTL:
        _probe_cache.pop(url, None)
        return None
    return entry[1]


def _cache_put(url, info):
    # تنظيف كسول للمنتهي حتى لا تتضخم الذاكرة
    if len(_probe_cache) > 300:
        now = time.time()
        for k in [k for k, v in _probe_cache.items() if now - v[0] > PROBE_CACHE_TTL]:
            _probe_cache.pop(k, None)
    _probe_cache[url] = (time.time(), info)


def probe(url, timeout=None, use_cache=True):
    """يفحص الرابط ويعيد MediaInfo — يجرّب سلسلة العملاء حتى ينجح."""
    if use_cache:
        hit = _cache_get(url)
        if hit is not None:
            log.debug("فحص من الذاكرة: %s", url[:60])
            return hit

    plat = P.detect(url)
    has_ff = media_tools.has_ffmpeg()
    timeout = timeout or PROBE_TIMEOUT

    errors = []
    started = time.time()

    for i, variant in enumerate(plat.client_chain):
        if time.time() - started > timeout:
            break
        opts = _merge(base_opts(url, plat), variant)
        opts['skip_download'] = True
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                errors.append("لا توجد بيانات")
                continue

            # قائمة تشغيل / منشور متعدد
            is_playlist = info.get('_type') == 'playlist'
            entries = info.get('entries') or []
            if is_playlist:
                if not entries:
                    errors.append("قائمة فارغة")
                    continue
                first = entries[0] or {}
                opts_list = _collect_options(first, has_ff)
                result = MediaInfo(
                    url=url, platform=plat,
                    title=info.get('title') or first.get('title') or 'مجموعة',
                    duration=first.get('duration') or 0,
                    thumbnail=first.get('thumbnail') or info.get('thumbnail'),
                    uploader=info.get('uploader') or first.get('uploader') or '',
                    options=opts_list, is_playlist=True, entries=len(entries),
                    raw=info)
                _cache_put(url, result)
                return result

            result = MediaInfo(
                url=url, platform=plat,
                title=info.get('title') or info.get('description', '')[:60] or 'ملف',
                duration=info.get('duration') or 0,
                thumbnail=info.get('thumbnail'),
                uploader=info.get('uploader') or info.get('channel') or '',
                options=_collect_options(info, has_ff),
                live=bool(info.get('is_live')),
                raw=info)
            _cache_put(url, result)
            return result

        except Exception as e:
            errors.append(f"[{i}] {e}")
            log.debug("فشل الفحص (%s محاولة %s): %s", plat.key, i, e)
            continue

    raise ExtractError(plat, errors)


class ExtractError(Exception):
    def __init__(self, platform, errors):
        self.platform = platform
        self.errors = errors or []
        super().__init__(self.errors[-1] if self.errors else 'فشل الفحص')

    @property
    def last(self):
        return str(self.errors[-1]) if self.errors else ''

    def joined(self):
        return " | ".join(str(e) for e in self.errors)


def current_speed_bps():
    """السرعة المستخدمة في تقدير الأزمنة: مقاسة إن أمكن، وإلا الافتراضية."""
    try:
        from database import recent_speed_bps
        measured = recent_speed_bps()
    except Exception:
        measured = None
    if measured and measured > 100 * 1024:
        return measured
    return DEFAULT_SPEED_MBPS * 1000 * 1000 / 8.0
