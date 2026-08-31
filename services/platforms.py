# -*- coding: utf-8 -*-
"""سجل المنصات — كشف المنصة من الرابط + إعدادات yt-dlp الخاصة بكل منصة.

هنا يُحلّ سبب تعطّل يوتيوب وإنستغرام:
  • يوتيوب: يحتاج تدوير عملاء (player_client) لأن جوجل تحظر عميل الويب باستمرار.
  • إنستغرام: يحتاج كوكيز جلسة + ترويسات صحيحة، وإلا يرد بـ login required.
"""
import os
import re
from urllib.parse import urlparse

from config import COOKIES_DIR

UA_DESKTOP = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
UA_MOBILE = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 '
             '(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1')
UA_ANDROID = ('Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36')


class Platform:
    def __init__(self, key, name, emoji, patterns, cookie_file=None,
                 opts=None, client_chain=None, needs_cookies=False,
                 gallery_dl=False, notes=''):
        self.key = key
        self.name = name
        self.emoji = emoji
        self.patterns = [re.compile(p, re.I) for p in patterns]
        self.cookie_file = cookie_file
        self.opts = opts or {}
        # سلسلة محاولات: كل عنصر إعدادات إضافية تُجرَّب بالترتيب حتى ينجح واحد
        self.client_chain = client_chain or [{}]
        self.needs_cookies = needs_cookies
        self.gallery_dl = gallery_dl
        self.notes = notes

    def matches(self, url):
        return any(p.search(url) for p in self.patterns)

    def cookie_path(self):
        if not self.cookie_file:
            return None
        p = os.path.join(COOKIES_DIR, self.cookie_file)
        return p if os.path.exists(p) else None

    @property
    def label(self):
        return f"{self.emoji} {self.name}"


# ═══════════════════════════════════════════════════════════════
#  يوتيوب — أهم إصلاح
# ═══════════════════════════════════════════════════════════════
# جوجل تكسر عملاء yt-dlp بالتناوب، لذلك نجرّب عدة عملاء بالترتيب.
# web_safari/tv_simply يعطيان كامل الجودات (حتى 4K) بشرط توفّر محرك JS + PO Token.
# android_vr احتياطي أخير يعمل بلا أي متطلبات لكنه محدود بـ 360p.
# تم قياس هذه الترتيبات فعلياً على نفس الفيديو:
#   tv_simply + تخطي hls : 13.7 ثانية ← 2160p (الأسرع والأكمل معاً)
#   web_safari+tv_simply : 21.7 ثانية ← 2160p
#   web_safari وحده      : 16.7 ثانية ← 1080p فقط
# تخطّي hls يوفّر ~3 ثوانٍ لأن صيغ m3u8 لا نحتاجها (الجودات العالية في DASH).
YOUTUBE_CHAIN = [
    {'extractor_args': {'youtube': {'player_client': ['tv_simply'], 'skip': ['hls']}}},
    {'extractor_args': {'youtube': {'player_client': ['web_safari', 'tv']}}},
    {'extractor_args': {'youtube': {'player_client': ['mweb', 'ios']}},
     'http_headers': {'User-Agent': UA_MOBILE}},
    {'extractor_args': {'youtube': {'player_client': ['android_vr']}}},
    {'extractor_args': {'youtube': {'player_client': ['default']}}},
]

INSTAGRAM_CHAIN = [
    {},  # بالكوكيز إن وُجدت
    {'http_headers': {'User-Agent': UA_MOBILE,
                      'X-IG-App-ID': '936619743392459'}},
    {'http_headers': {'User-Agent': UA_ANDROID}},
]

PLATFORMS = [
    Platform(
        'youtube', 'يوتيوب', '▶️',
        [r'(?:^|\.)youtube\.com', r'(?:^|\.)youtu\.be', r'youtube-nocookie\.com',
         r'(?:^|\.)music\.youtube\.com'],
        cookie_file='youtube.txt',
        client_chain=YOUTUBE_CHAIN,
        opts={'extractor_retries': 3},
        notes='الشورتس والفيديو والبث المسجّل والموسيقى',
    ),
    Platform(
        'instagram', 'إنستغرام', '📸',
        [r'(?:^|\.)instagram\.com', r'(?:^|\.)instagr\.am', r'(?:^|\.)ddinstagram\.com'],
        cookie_file='instagram.txt',
        client_chain=INSTAGRAM_CHAIN,
        needs_cookies=True, gallery_dl=True,
        notes='ريلز Reels، منشورات، ستوري، IGTV، صور متعددة',
    ),
    Platform(
        'tiktok', 'تيك توك', '🎵',
        [r'(?:^|\.)tiktok\.com', r'(?:^|\.)vm\.tiktok\.com', r'(?:^|\.)vt\.tiktok\.com',
         r'(?:^|\.)douyin\.com'],
        cookie_file='tiktok.txt', gallery_dl=True,
        opts={'extractor_args': {'tiktok': {'api_hostname': ['api22-normal-c-useast2a.tiktokv.com']}}},
        notes='فيديو بدون علامة مائية غالباً',
    ),
    Platform(
        'snapchat', 'سناب شات', '👻',
        [r'(?:^|\.)snapchat\.com', r'(?:^|\.)snap\.com', r't\.snapchat\.com'],
        cookie_file='snapchat.txt', gallery_dl=True,
        opts={'http_headers': {'User-Agent': UA_MOBILE}},
        notes='Spotlight والقصص العامة والملفات العامة',
    ),
    Platform(
        'facebook', 'فيسبوك', '📘',
        [r'(?:^|\.)facebook\.com', r'(?:^|\.)fb\.watch', r'(?:^|\.)fb\.com',
         r'(?:^|\.)m\.facebook\.com'],
        cookie_file='facebook.txt', needs_cookies=True,
        notes='فيديو، ريلز، مشاهدات',
    ),
    Platform(
        'twitter', 'إكس / تويتر', '🐦',
        [r'(?:^|\.)twitter\.com', r'(?:^|\.)x\.com', r'(?:^|\.)t\.co',
         r'(?:^|\.)fxtwitter\.com', r'(?:^|\.)vxtwitter\.com'],
        cookie_file='twitter.txt', gallery_dl=True,
        notes='فيديو وصور وGIF',
    ),
    Platform(
        'threads', 'ثريدز', '🧵',
        [r'(?:^|\.)threads\.net', r'(?:^|\.)threads\.com'],
        cookie_file='instagram.txt', gallery_dl=True,
    ),
    Platform(
        'reddit', 'ريديت', '🤖',
        [r'(?:^|\.)reddit\.com', r'(?:^|\.)redd\.it', r'(?:^|\.)v\.redd\.it'],
        gallery_dl=True,
    ),
    Platform(
        'pinterest', 'بنترست', '📌',
        [r'(?:^|\.)pinterest\.', r'(?:^|\.)pin\.it'],
        gallery_dl=True,
    ),
    Platform('twitch', 'تويتش', '🟣',
             [r'(?:^|\.)twitch\.tv', r'(?:^|\.)clips\.twitch\.tv'],
             cookie_file='twitch.txt'),
    Platform('vimeo', 'فيميو', '🎬', [r'(?:^|\.)vimeo\.com']),
    Platform('dailymotion', 'ديلي موشن', '📺', [r'(?:^|\.)dailymotion\.com', r'(?:^|\.)dai\.ly']),
    Platform('soundcloud', 'ساوند كلاود', '🔊', [r'(?:^|\.)soundcloud\.com', r'(?:^|\.)snd\.sc']),
    Platform('spotify', 'سبوتيفاي', '🟢', [r'(?:^|\.)spotify\.com', r'(?:^|\.)spoti\.fi'],
             notes='الروابط العامة فقط (المعاينات)'),
    Platform('likee', 'لايكي', '💛', [r'(?:^|\.)likee\.video', r'(?:^|\.)like\.video', r'(?:^|\.)l\.likee\.video']),
    Platform('kwai', 'كواي', '⚡', [r'(?:^|\.)kwai\.com', r'(?:^|\.)kw\.ai', r'(?:^|\.)kwai-video\.com']),
    Platform('bilibili', 'بيليبيلي', '📼', [r'(?:^|\.)bilibili\.com', r'(?:^|\.)b23\.tv']),
    Platform('vk', 'VK', '🔵', [r'(?:^|\.)vk\.com', r'(?:^|\.)vkvideo\.ru'], cookie_file='vk.txt'),
    Platform('ok', 'أودنوكلاسنيكي', '🟠', [r'(?:^|\.)ok\.ru']),
    Platform('rumble', 'رامبل', '🟩', [r'(?:^|\.)rumble\.com']),
    Platform('odysee', 'أوديسي', '🌊', [r'(?:^|\.)odysee\.com', r'(?:^|\.)lbry\.tv']),
    Platform('bitchute', 'بيتشوت', '⬛', [r'(?:^|\.)bitchute\.com']),
    Platform('linkedin', 'لينكدإن', '💼', [r'(?:^|\.)linkedin\.com'], cookie_file='linkedin.txt'),
    Platform('tumblr', 'تمبلر', '🎨', [r'(?:^|\.)tumblr\.com'], gallery_dl=True),
    Platform('imgur', 'إيمجور', '🖼️', [r'(?:^|\.)imgur\.com'], gallery_dl=True),
    Platform('flickr', 'فليكر', '📷', [r'(?:^|\.)flickr\.com', r'(?:^|\.)flic\.kr'], gallery_dl=True),
    Platform('deviantart', 'ديفيان آرت', '🖌️', [r'(?:^|\.)deviantart\.com'], gallery_dl=True),
    Platform('telegram', 'تيليجرام', '✈️', [r'(?:^|\.)t\.me']),
    Platform('mixcloud', 'ميكس كلاود', '🎧', [r'(?:^|\.)mixcloud\.com']),
    Platform('bandcamp', 'باندكامب', '🎼', [r'(?:^|\.)bandcamp\.com']),
    Platform('archive', 'أرشيف الإنترنت', '📚', [r'(?:^|\.)archive\.org']),
    Platform('9gag', '9GAG', '😂', [r'(?:^|\.)9gag\.com']),
    Platform('espn', 'ESPN', '🏆', [r'(?:^|\.)espn\.com']),
    Platform('aljazeera', 'الجزيرة', '📰', [r'(?:^|\.)aljazeera\.']),
    Platform('shahid', 'شاهد', '🎥', [r'(?:^|\.)shahid\.mbc\.net'], cookie_file='shahid.txt'),
    Platform('mediafire', 'ميديا فاير', '📁', [r'(?:^|\.)mediafire\.com']),
    Platform('gdrive', 'جوجل درايف', '📂', [r'drive\.google\.com', r'docs\.google\.com']),
    Platform('dropbox', 'دروب بوكس', '📦', [r'(?:^|\.)dropbox\.com']),
    Platform('streamable', 'ستريمابل', '▶️', [r'(?:^|\.)streamable\.com']),
    Platform('vidmoly', 'مشغلات الفيديو', '🎞️',
             [r'(?:^|\.)vidmoly\.', r'(?:^|\.)dood\.', r'(?:^|\.)streamtape\.',
              r'(?:^|\.)mixdrop\.', r'(?:^|\.)filemoon\.', r'(?:^|\.)voe\.sx']),
]

GENERIC = Platform('generic', 'رابط عام', '🌐', [r'.*'],
                   notes='أي موقع آخر يدعمه yt-dlp (أكثر من 1800 موقع)')

# منصات مهمة تُعرض للمستخدم في رسالة المساعدة
FEATURED = ['youtube', 'instagram', 'tiktok', 'snapchat', 'facebook',
            'twitter', 'threads', 'reddit', 'pinterest', 'twitch',
            'vimeo', 'soundcloud', 'likee', 'kwai', 'dailymotion']


def detect(url):
    """يعيد كائن Platform المناسب للرابط."""
    if not url:
        return GENERIC
    try:
        host = (urlparse(url).hostname or '').lower()
    except Exception:
        host = ''
    probe = host or url
    for p in PLATFORMS:
        if p.matches(probe):
            return p
    # احتياط: بعض الروابط تحمل اسم المنصة في المسار (مثل روابط المشاركة)
    for p in PLATFORMS:
        if p.matches(url):
            return p
    return GENERIC


def get(key):
    for p in PLATFORMS:
        if p.key == key:
            return p
    return GENERIC


def featured_list():
    return [get(k) for k in FEATURED]


# ═══════════════════════════════════════════════════════════════
#  كشف نوع محتوى إنستغرام / سناب لاختيار المحرّك الصحيح
# ═══════════════════════════════════════════════════════════════
IG_STORY_RE = re.compile(r'/stories/', re.I)
IG_PHOTO_RE = re.compile(r'/(p|tv)/', re.I)
IG_REEL_RE = re.compile(r'/(reel|reels)/', re.I)


def content_hint(url):
    """تلميح عن نوع المحتوى: reel / story / photo / video"""
    if IG_REEL_RE.search(url):
        return 'reel'
    if IG_STORY_RE.search(url):
        return 'story'
    if IG_PHOTO_RE.search(url):
        return 'photo'
    return 'video'
