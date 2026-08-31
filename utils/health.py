# -*- coding: utf-8 -*-
"""خادم فحص صحة صغير.

بوت تيليجرام بالاستطلاع (polling) لا يفتح أي منفذ، لكن كثيراً من منصات
الاستضافة (غيمة، Heroku، Render...) تعتبر الخدمة ميتة إن لم تستمع لمنفذ،
فتوقفها. هذا الخادم يردّ على /health و / ليبقى النشر حياً — ويعطيك
لوحة حالة سريعة من المتصفح.
"""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger(__name__)

_state = {'ready': False, 'bot': None}


def set_ready(username=None):
    _state['ready'] = True
    _state['bot'] = username


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload, ctype='application/json'):
        body = (json.dumps(payload, ensure_ascii=False)
                if ctype == 'application/json' else payload).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', f'{ctype}; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def do_GET(self):
        path = self.path.split('?')[0].rstrip('/') or '/'

        # الحياة (liveness): 200 دائماً ما دامت العملية تستجيب.
        # نتعمّد عدم إرجاع 503 أثناء الإقلاع لأن منصات الاستضافة تقتل
        # الحاوية عندئذ — والبوت يحتاج وقتاً لتهيئة أدواته.
        if path in ('/health', '/healthz', '/ping'):
            self._send(200, {'status': 'ok' if _state['ready'] else 'starting',
                             'alive': True})
            return

        # الجاهزية (readiness): 503 حتى يتصل البوت بتيليجرام فعلاً
        if path in ('/ready', '/readyz'):
            ok = _state['ready']
            self._send(200 if ok else 503,
                       {'status': 'ready' if ok else 'starting'})
            return

        if path == '/status':
            try:
                from services import media_tools
                from database import get_stats
                s = get_stats()
                self._send(200, {
                    'status': 'ok' if _state['ready'] else 'starting',
                    'bot': _state['bot'],
                    'tools': {
                        'ffmpeg': media_tools.has_ffmpeg(),
                        'deno': media_tools.has_js_runtime(),
                        'pot': media_tools.has_pot(),
                    },
                    'users': s['total_users'],
                    'downloads': s['dl_total'],
                    'downloads_today': s['dl_today'],
                })
            except Exception as e:
                self._send(500, {'status': 'error', 'detail': str(e)[:200]})
            return

        if path == '/':
            name = _state['bot'] or 'Telegram Downloader Bot'
            self._send(200,
                       f"<!doctype html><meta charset='utf-8'>"
                       f"<title>{name}</title>"
                       f"<body style='font-family:system-ui;text-align:center;padding:3rem'>"
                       f"<h1>🤖 {name}</h1>"
                       f"<p>{'يعمل ✅' if _state['ready'] else 'قيد الإقلاع…'}</p>"
                       f"<p><a href='/status'>/status</a></p></body>",
                       ctype='text/html')
            return

        self._send(404, {'status': 'not found'})

    # نكتم سجلّ كل طلب — فاحص الصحة يطرق كل بضع ثوانٍ
    def log_message(self, fmt, *args):
        pass


def start(port):
    """يشغّل الخادم في خيط خلفي. يعيد True إن نجح."""
    if not port:
        return False
    try:
        server = ThreadingHTTPServer(('0.0.0.0', int(port)), _Handler)
    except OSError as e:
        log.warning("تعذّر فتح منفذ فحص الصحة %s: %s", port, e)
        return False

    t = threading.Thread(target=server.serve_forever, daemon=True,
                         name='health')
    t.start()
    log.info("خادم فحص الصحة يستمع على المنفذ %s", port)
    return True
