# -*- coding: utf-8 -*-
"""محرك التنزيل — عدة مكتبات متعاقبة حتى ينجح واحد.

سلسلة المحاولات لكل رابط:
  1) yt-dlp مع سلسلة عملاء المنصة (يوتيوب: tv → android_vr → web → mweb)
  2) gallery-dl   — ممتاز لإنستغرام/سناب/بنترست/تويتر (صور ومنشورات متعددة)
  3) instaloader  — احتياطي خاص بإنستغرام
  4) تنزيل مباشر  — للروابط التي تشير إلى ملف فعلي
"""
import os
import re
import glob
import json
import time
import shutil
import logging
import tempfile
import subprocess

import requests
import yt_dlp

from config import (DOWNLOAD_DIR, ORPHAN_FILE_AGE, PROXY, TG_UPLOAD_LIMIT)
from services import platforms as P
from services import media_tools
from services.extractor import base_opts, _merge
from utils.helpers import safe_filename, is_safe_url

log = logging.getLogger(__name__)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

VIDEO_EXTS = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4v', '.flv', '.ts', '.3gp', '.mpg', '.mpeg', '.wmv'}
AUDIO_EXTS = {'.mp3', '.m4a', '.opus', '.ogg', '.wav', '.flac', '.aac', '.wma'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.bmp'}

DIRECT_EXTS = tuple(VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS |
                    {'.pdf', '.zip', '.rar', '.7z', '.apk', '.docx', '.xlsx',
                     '.pptx', '.txt', '.epub', '.torrent', '.exe', '.iso'})


class DownloadResult:
    def __init__(self, files, kind, title='', engine='', size=0, duration_ms=0,
                 height=0, width=0, media_duration=0, thumbnail=None):
        self.files = files if isinstance(files, list) else [files]
        self.kind = kind                  # video / audio / photo / document
        self.title = title
        self.engine = engine
        self.size = size
        self.duration_ms = duration_ms
        self.height = height
        self.width = width
        self.media_duration = media_duration
        self.thumbnail = thumbnail

    @property
    def path(self):
        return self.files[0] if self.files else None


class DownloadError(Exception):
    def __init__(self, message, attempts=None):
        super().__init__(message)
        self.attempts = attempts or []


# ═══════════════════════════ تنظيف ═══════════════════════════
def cleanup(path):
    if not path:
        return
    paths = path if isinstance(path, (list, tuple)) else [path]
    for p in paths:
        try:
            if p and os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def cleanup_orphans():
    """يحذف بقايا العمليات الفاشلة القديمة."""
    cutoff = time.time() - ORPHAN_FILE_AGE
    try:
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, '*')):
            try:
                if os.path.getmtime(f) < cutoff:
                    cleanup(f)
            except OSError:
                pass
    except Exception:
        pass


def _work_dir(user_id):
    d = os.path.join(DOWNLOAD_DIR, f"u{user_id}_{int(time.time() * 1000) % 10_000_000}")
    os.makedirs(d, exist_ok=True)
    return d


def _classify(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in AUDIO_EXTS:
        return 'audio'
    if ext in VIDEO_EXTS:
        return 'video'
    if ext in IMAGE_EXTS:
        return 'photo'
    return 'document'


def _collect_files(folder):
    out = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.endswith(('.part', '.ytdl', '.temp', '.tmp')):
                continue
            full = os.path.join(root, f)
            try:
                if os.path.getsize(full) > 0:
                    out.append(full)
            except OSError:
                pass
    out.sort()
    return out


# ═══════════════════════════ بناء محدد الصيغة ═══════════════════════════
def build_format(max_height, want_audio=False, needs_merge_ok=True):
    """محدد صيغة yt-dlp.

    الخطأ القديم كان استخدام `best[...]` وحده — وهو يقتصر على الصيغ المدمجة
    مسبقاً، ويوتيوب لا يقدّمها فوق 720p. الحل: bv*+ba مع تدرّج احتياطي.
    """
    if want_audio:
        return 'bestaudio/best'

    h = int(max_height or 0)
    if not needs_merge_ok:
        # بلا ffmpeg: الصيغ المدمجة فقط
        return f'best[height<={h}]/best' if h else 'best'

    if h:
        return (f'bv*[height<={h}]+ba/'
                f'b[height<={h}]/'
                f'bv*[height<={h}]/'
                f'b')
    return 'bv*+ba/b'


# ═══════════════════════════ 1) yt-dlp ═══════════════════════════
def _ytdlp_download(url, out_dir, max_height=0, want_audio=False,
                    progress_cb=None, playlist=False):
    plat = P.detect(url)
    has_ff = media_tools.has_ffmpeg()

    if want_audio and not has_ff:
        raise DownloadError("تحويل MP3 يحتاج ffmpeg — أبلغ الأدمن")

    attempts = []
    started = time.time()

    for i, variant in enumerate(plat.client_chain):
        opts = _merge(base_opts(url, plat), variant)
        opts.update({
            'outtmpl': os.path.join(out_dir, '%(title).80s [%(id)s].%(ext)s'),
            'format': build_format(max_height, want_audio, has_ff),
            'noplaylist': not playlist,
            'restrictfilenames': False,
            'windowsfilenames': True,
            'trim_file_name': 100,
            'overwrites': True,
            'noprogress': True,
        })

        if want_audio:
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }, {
                'key': 'FFmpegMetadata',
            }]
        elif has_ff:
            opts['merge_output_format'] = 'mp4'
            # نضمن توافق الحاوية مع مشغّل تيليجرام
            opts['postprocessors'] = [{
                'key': 'FFmpegVideoRemuxer',
                'preferedformat': 'mp4',
            }]

        if progress_cb:
            opts['progress_hooks'] = [progress_cb]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

            files = _collect_files(out_dir)
            if not files:
                raise DownloadError("لم يُنتج أي ملف")

            if info and info.get('_type') == 'playlist':
                entry = (info.get('entries') or [{}])[0] or {}
            else:
                entry = info or {}

            main = files[0]
            if len(files) > 1:
                # نختار الأكبر كملف رئيسي (الفيديو وليس الصورة المصغّرة)
                main = max(files, key=lambda f: os.path.getsize(f))

            kind = 'audio' if want_audio else _classify(main)
            return DownloadResult(
                files=[main] if not playlist else files,
                kind=kind,
                title=entry.get('title') or os.path.basename(main),
                engine=f"yt-dlp/{plat.key}#{i}",
                size=os.path.getsize(main),
                duration_ms=int((time.time() - started) * 1000),
                height=entry.get('height') or 0,
                width=entry.get('width') or 0,
                media_duration=entry.get('duration') or 0,
                thumbnail=entry.get('thumbnail'),
            )

        except Exception as e:
            attempts.append(f"yt-dlp#{i}: {e}")
            log.debug("yt-dlp محاولة %s فشلت (%s): %s", i, plat.key, e)
            # ننظّف الملفات الجزئية قبل المحاولة التالية
            for f in glob.glob(os.path.join(out_dir, '*')):
                cleanup(f)
            continue

    raise DownloadError("فشلت كل محاولات yt-dlp", attempts)


# ═══════════════════════════ 2) gallery-dl ═══════════════════════════
def _gallery_dl_available():
    return shutil.which('gallery-dl') is not None or _module_exists('gallery_dl')


def _module_exists(name):
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _gallery_dl_download(url, out_dir, progress_cb=None):
    """ممتاز للمنشورات المتعددة والصور والستوري."""
    if not _gallery_dl_available():
        raise DownloadError("gallery-dl غير مثبّت")

    plat = P.detect(url)
    started = time.time()

    exe = shutil.which('gallery-dl')
    if exe:
        cmd = [exe]
    else:
        import sys
        cmd = [sys.executable, '-m', 'gallery_dl']

    cmd += ['--dest', out_dir, '--no-part', '--quiet']

    cookie = plat.cookie_path()
    if cookie:
        cmd += ['--cookies', cookie]
    if PROXY:
        cmd += ['--proxy', PROXY]

    cmd += ['--', url]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=900,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
    except subprocess.TimeoutExpired:
        raise DownloadError("gallery-dl: انتهت المهلة")

    files = _collect_files(out_dir)
    if not files:
        err = (proc.stderr or proc.stdout or 'لا ملفات').strip()[:300]
        raise DownloadError(f"gallery-dl: {err}")

    main = max(files, key=lambda f: os.path.getsize(f))
    return DownloadResult(
        files=files, kind=_classify(main),
        title=os.path.splitext(os.path.basename(main))[0],
        engine='gallery-dl', size=os.path.getsize(main),
        duration_ms=int((time.time() - started) * 1000))


# ═══════════════════════════ 3) instaloader ═══════════════════════════
IG_SHORTCODE_RE = re.compile(r'/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)')


def _instaloader_download(url, out_dir):
    if not _module_exists('instaloader'):
        raise DownloadError("instaloader غير مثبّت")

    import instaloader

    m = IG_SHORTCODE_RE.search(url)
    if not m:
        raise DownloadError("instaloader: لا يدعم هذا النوع من روابط إنستغرام")

    started = time.time()
    L = instaloader.Instaloader(
        dirname_pattern=out_dir, save_metadata=False, download_comments=False,
        download_geotags=False, post_metadata_txt_pattern='', quiet=True)

    session = os.path.join(os.path.dirname(out_dir), '..', 'cookies', 'instaloader.session')
    try:
        user = os.getenv('IG_USERNAME')
        if user and os.path.exists(session):
            L.load_session_from_file(user, session)
    except Exception:
        pass

    try:
        post = instaloader.Post.from_shortcode(L.context, m.group(1))
        L.download_post(post, target='')
    except Exception as e:
        raise DownloadError(f"instaloader: {e}")

    files = [f for f in _collect_files(out_dir)
             if os.path.splitext(f)[1].lower() in (VIDEO_EXTS | IMAGE_EXTS)]
    if not files:
        raise DownloadError("instaloader: لا ملفات")

    main = max(files, key=lambda f: os.path.getsize(f))
    return DownloadResult(files=files, kind=_classify(main),
                          title=os.path.basename(main), engine='instaloader',
                          size=os.path.getsize(main),
                          duration_ms=int((time.time() - started) * 1000))


# ═══════════════════════════ 4) تنزيل مباشر ═══════════════════════════
def download_direct(url, out_dir, max_bytes=None, progress_cb=None):
    """ينزّل ملفاً مباشراً بأمان — بلا اختراق مسار وبسقف حجم."""
    if not is_safe_url(url):
        raise DownloadError("رابط غير آمن أو داخلي — مرفوض")

    max_bytes = max_bytes or TG_UPLOAD_LIMIT
    started = time.time()

    headers = {'User-Agent': P.UA_DESKTOP}
    proxies = {'http': PROXY, 'https': PROXY} if PROXY else None

    with requests.get(url, stream=True, timeout=(30, 180), headers=headers,
                      proxies=proxies, allow_redirects=True) as r:
        r.raise_for_status()

        declared = int(r.headers.get('Content-Length') or 0)
        if declared and declared > max_bytes:
            raise DownloadError(
                f"حجم الملف {declared / 1048576:.0f}MB يتجاوز الحد المسموح "
                f"{max_bytes / 1048576:.0f}MB")

        # الاسم: من ترويسة الخادم إن وُجدت، وإلا من الرابط — منظّف دائماً
        name = ''
        cd = r.headers.get('Content-Disposition') or ''
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.I)
        if m:
            name = m.group(1)
        if not name:
            name = url.split('/')[-1].split('?')[0]
        name = safe_filename(name, fallback='download')

        if '.' not in name:
            ctype = (r.headers.get('Content-Type') or '').split(';')[0].strip()
            ext = {'video/mp4': '.mp4', 'audio/mpeg': '.mp3', 'image/jpeg': '.jpg',
                   'image/png': '.png', 'application/pdf': '.pdf',
                   'application/zip': '.zip'}.get(ctype, '.bin')
            name += ext

        path = os.path.join(out_dir, name)
        got = 0
        with open(path, 'wb') as f:
            for chunk in r.iter_content(1024 * 512):
                if not chunk:
                    continue
                got += len(chunk)
                if got > max_bytes:
                    f.close()
                    cleanup(path)
                    raise DownloadError(
                        f"الملف تجاوز الحد المسموح ({max_bytes / 1048576:.0f}MB) أثناء التنزيل")
                f.write(chunk)
                if progress_cb:
                    progress_cb({'status': 'downloading', 'downloaded_bytes': got,
                                 'total_bytes': declared or 0})

    return DownloadResult(files=[path], kind=_classify(path),
                          title=os.path.basename(path), engine='direct',
                          size=os.path.getsize(path),
                          duration_ms=int((time.time() - started) * 1000))


def looks_direct(url):
    clean = url.lower().split('?')[0].split('#')[0]
    return clean.endswith(DIRECT_EXTS)


# ═══════════════════════════ المنسّق ═══════════════════════════
def download(url, user_id, max_height=0, want_audio=False,
             progress_cb=None, playlist=False, max_bytes=None):
    """ينزّل الرابط مجرّباً كل المحركات المتاحة بالترتيب."""
    out_dir = _work_dir(user_id)
    plat = P.detect(url)
    attempts = []

    engines = []
    if looks_direct(url):
        engines.append(('direct', lambda: download_direct(url, out_dir, max_bytes, progress_cb)))

    engines.append(('yt-dlp', lambda: _ytdlp_download(
        url, out_dir, max_height, want_audio, progress_cb, playlist)))

    if plat.gallery_dl and not want_audio:
        engines.append(('gallery-dl', lambda: _gallery_dl_download(url, out_dir, progress_cb)))

    if plat.key == 'instagram' and not want_audio:
        engines.append(('instaloader', lambda: _instaloader_download(url, out_dir)))

    if not looks_direct(url):
        engines.append(('direct', lambda: download_direct(url, out_dir, max_bytes, progress_cb)))

    for name, fn in engines:
        try:
            result = fn()
            if result and result.files:
                return result, out_dir
        except Exception as e:
            attempts.append(f"{name}: {str(e)[:200]}")
            log.info("محرك %s فشل على %s: %s", name, plat.key, str(e)[:200])
            for f in glob.glob(os.path.join(out_dir, '*')):
                cleanup(f)

    cleanup(out_dir)
    raise DownloadError(" || ".join(attempts) or "فشل كل المحركات", attempts)


# ═══════════════════════════ ما بعد المعالجة ═══════════════════════════
def make_thumbnail(video_path, out_dir):
    """يستخرج صورة مصغّرة — تيليجرام يعرض الفيديو أجمل معها."""
    if not media_tools.has_ffmpeg():
        return None
    ff = os.path.join(media_tools.ffmpeg_location(), 'ffmpeg' + ('.exe' if os.name == 'nt' else ''))
    thumb = os.path.join(out_dir, 'thumb.jpg')
    try:
        subprocess.run(
            [ff, '-y', '-ss', '1', '-i', video_path, '-vframes', '1',
             '-vf', 'scale=320:-2', '-q:v', '4', thumb],
            capture_output=True, timeout=60,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        if os.path.exists(thumb) and os.path.getsize(thumb) < 200 * 1024:
            return thumb
    except Exception:
        pass
    return None


def probe_dimensions(path):
    """أبعاد ومدة الفيديو عبر ffprobe — تجعل تيليجرام يعرضه كفيديو لا كملف."""
    if not media_tools.has_ffmpeg():
        return 0, 0, 0
    ffprobe = os.path.join(media_tools.ffmpeg_location(),
                           'ffprobe' + ('.exe' if os.name == 'nt' else ''))
    if not os.path.exists(ffprobe):
        return 0, 0, 0
    try:
        out = subprocess.run(
            [ffprobe, '-v', 'quiet', '-print_format', 'json', '-show_streams',
             '-show_format', path],
            capture_output=True, text=True, timeout=60,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        data = json.loads(out.stdout or '{}')
        dur = int(float(data.get('format', {}).get('duration') or 0))
        for s in data.get('streams', []):
            if s.get('codec_type') == 'video':
                return int(s.get('width') or 0), int(s.get('height') or 0), dur
        return 0, 0, dur
    except Exception:
        return 0, 0, 0
