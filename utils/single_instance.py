# -*- coding: utf-8 -*-
"""قفل النسخة الواحدة.

تيليجرام يسمح باتصال getUpdates واحد فقط لكل توكن. إن عملت نسختان
تتنازعان إلى الأبد بخطأ Conflict ولا تعمل أي منهما. هذا القفل يمنع ذلك
بوضوح عند الإقلاع بدل ترك المشكلة تظهر كسيل أخطاء غامض.
"""
import os
import sys
import atexit
import logging

log = logging.getLogger(__name__)

_lock_handle = None
_lock_path = None


def _pid_alive(pid):
    """هل العملية ما زالت حية؟"""
    if pid <= 0:
        return False
    if os.name == 'nt':
        import subprocess
        try:
            out = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}', '/NH'],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW)
            return str(pid) in (out.stdout or '')
        except Exception:
            return True   # عند الشك نفترض أنها حية
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire(lock_file, kill_stale=False):
    """يحجز القفل. يعيد (نجح، رسالة)."""
    global _lock_handle, _lock_path

    lock_file = os.path.abspath(lock_file)

    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r', encoding='utf-8') as f:
                old_pid = int((f.read().strip() or '0'))
        except (ValueError, OSError):
            old_pid = 0

        if old_pid and old_pid != os.getpid() and _pid_alive(old_pid):
            if not kill_stale:
                return False, (
                    f"نسخة أخرى من البوت تعمل بالفعل (PID {old_pid}).\n\n"
                    f"تيليجرام يسمح بنسخة واحدة فقط لكل توكن.\n\n"
                    f"الحلول:\n"
                    f"  • أوقف تلك النسخة أولاً، أو\n"
                    f"  • شغّل:  python bot.py --force   (يوقف القديمة تلقائياً)")

            log.warning("إيقاف النسخة القديمة PID %s", old_pid)
            try:
                if os.name == 'nt':
                    import subprocess
                    subprocess.run(['taskkill', '/F', '/PID', str(old_pid)],
                                   capture_output=True, timeout=20,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    import signal
                    import time
                    os.kill(old_pid, signal.SIGTERM)
                    time.sleep(3)
            except Exception as e:
                return False, f"تعذّر إيقاف النسخة القديمة (PID {old_pid}): {e}"

    try:
        os.makedirs(os.path.dirname(lock_file), exist_ok=True)
        with open(lock_file, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))
    except OSError as e:
        return False, f"تعذّرت كتابة ملف القفل: {e}"

    _lock_path = lock_file
    atexit.register(release)
    return True, f"القفل محجوز (PID {os.getpid()})"


def release():
    """يحرّر القفل — فقط إن كان يخصّ هذه العملية."""
    global _lock_path
    if not _lock_path:
        return
    try:
        with open(_lock_path, 'r', encoding='utf-8') as f:
            if int(f.read().strip() or '0') == os.getpid():
                os.remove(_lock_path)
    except (OSError, ValueError):
        pass
    _lock_path = None
