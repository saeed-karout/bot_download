# -*- coding: utf-8 -*-
"""تثبيت كل ما يحتاجه البوت بأمر واحد:  python setup.py

يثبّت: مكتبات بايثون + ffmpeg + Deno + مزوّد PO Token
"""
import os
import sys
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, 'tools')
POT_DIR = os.path.join(TOOLS, 'bgutil-pot')
POT_VERSION = '1.3.2'


def line(t=''):
    print(t, flush=True)


def head(t):
    line()
    line("═" * 58)
    line(f"  {t}")
    line("═" * 58)


def run(cmd, **kw):
    return subprocess.run(cmd, **kw)


def step_python_deps():
    head("١/٤  مكتبات بايثون")
    req = os.path.join(HERE, 'requirements.txt')
    r = run([sys.executable, '-m', 'pip', 'install', '-r', req])
    line("✅ تم" if r.returncode == 0 else "❌ فشل — راجع الأخطاء أعلاه")
    return r.returncode == 0


def step_ffmpeg():
    head("٢/٤  ffmpeg  (دمج الصوت والفيديو + تحويل MP3)")
    from services import media_tools

    if media_tools.has_ffmpeg():
        line(f"✅ موجود مسبقاً: {media_tools.ffmpeg_version()}")
        return True

    if os.name == 'nt':
        ok, msg = media_tools.install_ffmpeg_windows(progress=line)
        line(msg)
        return ok

    line("⚠️ على لينكس ثبّته يدوياً:")
    line("   sudo apt update && sudo apt install -y ffmpeg")
    return False


def step_deno():
    head("٣/٤  Deno  (محرك JavaScript — إلزامي ليوتيوب)")
    from services import media_tools

    if media_tools.has_js_runtime():
        line("✅ موجود مسبقاً")
        return True

    ok, msg = media_tools.install_deno(progress=line)
    line(msg)
    if not ok:
        line("   بديل يدوي: curl -fsSL https://deno.land/install.sh | sh")
    return ok


def step_pot():
    head("٤/٤  مزوّد PO Token  (يفتح جودات يوتيوب العالية)")
    from services import media_tools

    if media_tools.has_pot():
        line("✅ موجود مسبقاً — جاري التهيئة...")
        return media_tools.warm_pot_cache()

    if not shutil.which('git'):
        line("❌ git غير مثبّت — تخطّي هذه الخطوة")
        line("   يوتيوب سيعمل لكن بجودات محدودة")
        return False
    if not shutil.which('npm'):
        line("❌ npm (Node.js) غير مثبّت — تخطّي هذه الخطوة")
        line("   ثبّت Node.js من https://nodejs.org ثم أعد التشغيل")
        return False

    os.makedirs(TOOLS, exist_ok=True)
    if os.path.exists(POT_DIR):
        shutil.rmtree(POT_DIR, ignore_errors=True)

    line("⬇️ جاري الاستنساخ...")
    r = run(['git', 'clone', '--depth', '1', '--branch', POT_VERSION,
             'https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git', POT_DIR])
    if r.returncode != 0:
        line("❌ فشل الاستنساخ")
        return False

    server = os.path.join(POT_DIR, 'server')
    line("📦 جاري تثبيت الاعتماديات (قد يستغرق دقيقة)...")
    npm = shutil.which('npm')
    r = run([npm, 'install', '--no-audit', '--no-fund'], cwd=server,
            shell=(os.name == 'nt'))
    if r.returncode != 0:
        line("❌ فشل npm install")
        return False

    line("🔨 جاري البناء...")
    npx = shutil.which('npx')
    run([npx, '--yes', 'tsc'], cwd=server, shell=(os.name == 'nt'))

    from services import media_tools as mt
    if mt.find_pot_home(refresh=True):
        line("✅ تم البناء — جاري التهيئة الأولى...")
        return mt.warm_pot_cache()

    line("❌ لم يكتمل البناء")
    return False


def main():
    line()
    line("🤖 تثبيت متطلبات بوت التنزيل")

    step_python_deps()

    # نستورد بعد تثبيت المكتبات
    sys.path.insert(0, HERE)

    results = {
        'ffmpeg': step_ffmpeg(),
        'deno': step_deno(),
        'pot': step_pot(),
    }

    head("النتيجة")
    from services import media_tools
    line(media_tools.status_text().replace('<b>', '').replace('</b>', '')
         .replace('<code>', '').replace('</code>', ''))

    line()
    if results['ffmpeg'] and results['deno']:
        line("🎉 جاهز! شغّل البوت الآن:")
        line("   python bot.py")
    else:
        line("⚠️ بعض الأدوات ناقصة — البوت سيعمل بقدرات محدودة.")
        line("   يمكنك أيضاً تشغيل /installtools داخل البوت.")
    line()


if __name__ == '__main__':
    main()
