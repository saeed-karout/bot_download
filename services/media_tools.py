# -*- coding: utf-8 -*-
"""اكتشاف ffmpeg وتنزيله تلقائياً.

بدون ffmpeg لا يستطيع yt-dlp دمج الفيديو مع الصوت، فتنحصر الجودة في 720p
على يوتيوب ويفشل تحويل MP3 تماماً. هذا كان أحد أسباب تعطّل يوتيوب.
"""
import os
import io
import shutil
import zipfile
import logging
import platform
import subprocess

from config import TOOLS_DIR

log = logging.getLogger(__name__)

_FFMPEG_CACHE = {'checked': False, 'path': None, 'version': None}

WINDOWS_BUILD_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip",
]


def _exe(name):
    return name + '.exe' if os.name == 'nt' else name


def _candidates():
    """أماكن محتملة لـ ffmpeg بترتيب الأولوية."""
    yield shutil.which('ffmpeg')
    yield os.path.join(TOOLS_DIR, _exe('ffmpeg'))
    yield os.path.join(TOOLS_DIR, 'bin', _exe('ffmpeg'))
    for root, dirs, files in os.walk(TOOLS_DIR):
        if _exe('ffmpeg') in files:
            yield os.path.join(root, _exe('ffmpeg'))
        # لا نغوص أعمق من طبقتين لتجنّب البطء
        if root.count(os.sep) - TOOLS_DIR.count(os.sep) > 2:
            dirs[:] = []
    if os.name != 'nt':
        yield '/usr/bin/ffmpeg'
        yield '/usr/local/bin/ffmpeg'
        yield '/snap/bin/ffmpeg'


def _probe(path):
    if not path or not os.path.exists(path):
        return None
    try:
        out = subprocess.run([path, '-version'], capture_output=True, text=True,
                             timeout=15,
                             creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        if out.returncode == 0:
            first = (out.stdout or '').splitlines()[0] if out.stdout else 'ffmpeg'
            return first.strip()[:80]
    except Exception:
        pass
    return None


def find_ffmpeg(refresh=False):
    """يعيد مسار مجلد ffmpeg الصالح أو None."""
    if _FFMPEG_CACHE['checked'] and not refresh:
        return _FFMPEG_CACHE['path']

    _FFMPEG_CACHE['checked'] = True
    _FFMPEG_CACHE['path'] = None
    _FFMPEG_CACHE['version'] = None

    for cand in _candidates():
        if not cand:
            continue
        ver = _probe(cand)
        if ver:
            _FFMPEG_CACHE['path'] = os.path.dirname(os.path.abspath(cand))
            _FFMPEG_CACHE['version'] = ver
            log.info("ffmpeg: %s (%s)", cand, ver)
            return _FFMPEG_CACHE['path']

    log.warning("ffmpeg غير موجود — الجودات العالية ودمج الصوت وتحويل MP3 معطّلة")
    return None


def has_ffmpeg():
    return find_ffmpeg() is not None


def ffmpeg_version():
    find_ffmpeg()
    return _FFMPEG_CACHE['version']


def ffmpeg_location():
    return find_ffmpeg()


def install_ffmpeg_windows(progress=None):
    """ينزّل ffmpeg تلقائياً على ويندوز ويضعه في tools/ ."""
    import requests

    if platform.system() != 'Windows':
        return False, "التنزيل التلقائي مدعوم على ويندوز فقط. على لينكس: sudo apt install ffmpeg"

    last_err = None
    for url in WINDOWS_BUILD_URLS:
        try:
            if progress:
                progress(f"⬇️ جاري تنزيل ffmpeg من {url.split('/')[2]} ...")
            r = requests.get(url, stream=True, timeout=(30, 300))
            r.raise_for_status()

            buf = io.BytesIO()
            total = int(r.headers.get('Content-Length') or 0)
            got = 0
            step = 0
            for chunk in r.iter_content(1024 * 256):
                buf.write(chunk)
                got += len(chunk)
                step += 1
                if progress and total and step % 40 == 0:
                    progress(f"⬇️ ffmpeg: {got * 100 // total}%")

            if progress:
                progress("📦 جاري فك الضغط ...")

            buf.seek(0)
            with zipfile.ZipFile(buf) as z:
                for member in z.namelist():
                    base = os.path.basename(member)
                    if base.lower() in ('ffmpeg.exe', 'ffprobe.exe', 'ffplay.exe'):
                        target = os.path.join(TOOLS_DIR, base)
                        with z.open(member) as src, open(target, 'wb') as dst:
                            shutil.copyfileobj(src, dst)

            path = find_ffmpeg(refresh=True)
            if path:
                return True, f"✅ تم تثبيت ffmpeg في: {path}"
            last_err = "فُكّ الضغط لكن لم يُعثر على ffmpeg.exe"
        except Exception as e:
            last_err = str(e)
            log.warning("فشل تنزيل ffmpeg من %s: %s", url, e)

    return False, f"❌ فشل التثبيت التلقائي: {last_err}"


# ═══════════════════════════════════════════════════════════════
#  محرك JavaScript (Deno) + مزوّد PO Token
# ═══════════════════════════════════════════════════════════════
# يوتيوب صار يتطلّب حلّ تحديات JS (signature / n-challenge) وتوكن PO.
# بدون محرك JS يعيد يوتيوب صفر صيغ قابلة للتنزيل — وهذا كان سبب تعطّله.
_JS_CACHE = {'checked': False, 'path': None}
_POT_CACHE = {'checked': False, 'home': None}

DENO_URLS = {
    ('Windows', 'AMD64'): "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip",
    ('Linux', 'x86_64'): "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip",
    ('Linux', 'aarch64'): "https://github.com/denoland/deno/releases/latest/download/deno-aarch64-unknown-linux-gnu.zip",
    ('Darwin', 'arm64'): "https://github.com/denoland/deno/releases/latest/download/deno-aarch64-apple-darwin.zip",
    ('Darwin', 'x86_64'): "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-apple-darwin.zip",
}


def find_deno(refresh=False):
    if _JS_CACHE['checked'] and not refresh:
        return _JS_CACHE['path']
    _JS_CACHE['checked'] = True
    _JS_CACHE['path'] = None

    for cand in (os.path.join(TOOLS_DIR, _exe('deno')), shutil.which('deno')):
        if cand and os.path.exists(cand):
            try:
                out = subprocess.run([cand, '-V'], capture_output=True, text=True, timeout=20,
                                     creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
                if out.returncode == 0:
                    _JS_CACHE['path'] = os.path.abspath(cand)
                    log.info("محرك JS: %s (%s)", cand, (out.stdout or '').strip())
                    return _JS_CACHE['path']
            except Exception:
                pass

    log.warning("Deno غير موجود — يوتيوب سيعمل بجودة محدودة جداً")
    return None


def has_js_runtime():
    return find_deno() is not None


def find_pot_home(refresh=False):
    """مجلد server الخاص بمزوّد PO Token."""
    if _POT_CACHE['checked'] and not refresh:
        return _POT_CACHE['home']
    _POT_CACHE['checked'] = True
    _POT_CACHE['home'] = None

    for cand in (
        os.path.join(TOOLS_DIR, 'bgutil-pot', 'server'),
        os.path.expanduser('~/bgutil-ytdlp-pot-provider/server'),
    ):
        if os.path.isfile(os.path.join(cand, 'src', 'generate_once.ts')) or \
           os.path.isfile(os.path.join(cand, 'build', 'generate_once.js')):
            _POT_CACHE['home'] = os.path.abspath(cand)
            return _POT_CACHE['home']
    return None


def has_pot():
    return find_pot_home() is not None


def ytdlp_runtime_opts():
    """إعدادات yt-dlp اللازمة لتشغيل يوتيوب بكامل الجودات."""
    opts = {}
    deno = find_deno()
    if deno:
        opts['js_runtimes'] = {'deno': {'path': deno}}

    pot = find_pot_home()
    if pot:
        opts['extractor_args'] = {'youtubepot-bgutilscript': {'server_home': [pot]}}

    ff = ffmpeg_location()
    if ff:
        opts['ffmpeg_location'] = ff
    return opts


def install_deno(progress=None):
    """ينزّل Deno تلقائياً (ملف تنفيذي واحد محمول)."""
    import requests

    key = (platform.system(), platform.machine())
    url = DENO_URLS.get(key)
    if not url:
        # تطبيع أسماء المعمارية
        machine = platform.machine().lower()
        if machine in ('amd64', 'x86_64'):
            url = DENO_URLS.get((platform.system(), 'x86_64')) or DENO_URLS.get((platform.system(), 'AMD64'))
        elif machine in ('arm64', 'aarch64'):
            url = DENO_URLS.get((platform.system(), 'aarch64')) or DENO_URLS.get((platform.system(), 'arm64'))
    if not url:
        return False, f"لا توجد نسخة Deno جاهزة لـ {platform.system()}/{platform.machine()}"

    try:
        if progress:
            progress("⬇️ جاري تنزيل محرك Deno ...")
        r = requests.get(url, stream=True, timeout=(30, 600))
        r.raise_for_status()

        buf = io.BytesIO()
        total = int(r.headers.get('Content-Length') or 0)
        got = step = 0
        for chunk in r.iter_content(1024 * 256):
            buf.write(chunk)
            got += len(chunk)
            step += 1
            if progress and total and step % 60 == 0:
                progress(f"⬇️ Deno: {got * 100 // total}%")

        buf.seek(0)
        with zipfile.ZipFile(buf) as z:
            for member in z.namelist():
                if os.path.basename(member).lower() in ('deno', 'deno.exe'):
                    target = os.path.join(TOOLS_DIR, os.path.basename(member))
                    with z.open(member) as src, open(target, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    if os.name != 'nt':
                        os.chmod(target, 0o755)

        path = find_deno(refresh=True)
        return (True, f"✅ تم تثبيت Deno: {path}") if path else (False, "لم يُعثر على الملف بعد الفك")
    except Exception as e:
        return False, f"❌ فشل تثبيت Deno: {e}"


def warm_pot_cache():
    """تشغيل أولي لمزوّد التوكن ليحمّل اعتمادياته (وإلا انتهت مهلته أول مرة)."""
    deno, home = find_deno(), find_pot_home()
    if not (deno and home):
        return False
    script = os.path.join(home, 'src', 'generate_once.ts')
    if not os.path.exists(script):
        script = os.path.join(home, 'build', 'generate_once.js')
    if not os.path.exists(script):
        return False
    try:
        out = subprocess.run(
            [deno, 'run', '--allow-env', '--allow-net', '--allow-ffi',
             '--allow-write', '--allow-read', script, '--version'],
            capture_output=True, text=True, timeout=300, cwd=home,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        ok = out.returncode == 0
        log.info("تهيئة مزوّد PO Token: %s", (out.stdout or out.stderr or '').strip()[:80])
        return ok
    except Exception as e:
        log.warning("فشل تهيئة مزوّد PO Token: %s", e)
        return False


def status_text():
    """نص جاهز لعرضه للأدمن."""
    lines = []

    if has_ffmpeg():
        lines.append(f"✅ <b>ffmpeg</b> — يعمل\n   <code>{ffmpeg_version()}</code>")
    else:
        lines.append("❌ <b>ffmpeg</b> — غير مثبّت\n"
                     "   ⚠️ الجودات العالية ودمج الصوت وتحويل MP3 معطّلة\n"
                     "   🔧 /installtools")

    if has_js_runtime():
        lines.append("✅ <b>Deno</b> (محرك JS) — يعمل\n"
                     "   يوتيوب يعمل بكامل الجودات")
    else:
        lines.append("❌ <b>Deno</b> — غير مثبّت\n"
                     "   ⚠️ يوتيوب سيعيد 360p فقط أو يفشل تماماً\n"
                     "   🔧 /installtools")

    if has_pot():
        lines.append("✅ <b>PO Token Provider</b> — يعمل")
    else:
        lines.append("⚠️ <b>PO Token Provider</b> — غير مثبّت\n"
                     "   قد يفشل يوتيوب أحياناً")

    return "\n\n".join(lines)
