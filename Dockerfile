# ═══════════════════════════════════════════════════════════════
#  بوت تنزيل الفيديو — صورة جاهزة للنشر
#
#  تُبنى بثلاث أدوات إلزامية:
#    • ffmpeg  — دمج الفيديو مع الصوت وتحويل MP3
#    • Deno    — محرك JavaScript يحل تحديات يوتيوب (بدونه يوتيوب لا يعمل)
#    • bgutil  — مزوّد PO Token الذي يطلبه يوتيوب
# ═══════════════════════════════════════════════════════════════

# ── مرحلة البناء: نجهّز مزوّد PO Token ونتخلص من أدوات البناء لاحقاً ──
FROM node:20-bookworm-slim AS potbuilder

ARG POT_VERSION=1.3.2
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 --branch ${POT_VERSION} \
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git . \
    && cd server \
    && npm install --no-audit --no-fund --loglevel=error \
    && npx --yes tsc \
    && npm prune --omit=dev


# ── الصورة النهائية ──
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    DENO_DIR=/app/tools/.deno_cache

# ffmpeg للمعالجة، والباقي أدوات نظام صغيرة
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        curl \
        unzip \
        tini \
    && rm -rf /var/lib/apt/lists/*

# ── Deno: محرك JavaScript، إلزامي ليوتيوب ──
ARG DENO_VERSION=v2.9.6
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) target="x86_64-unknown-linux-gnu" ;; \
      arm64) target="aarch64-unknown-linux-gnu" ;; \
      *) echo "معمارية غير مدعومة: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/deno.zip \
      "https://github.com/denoland/deno/releases/download/${DENO_VERSION}/deno-${target}.zip"; \
    unzip -q /tmp/deno.zip -d /usr/local/bin; \
    chmod +x /usr/local/bin/deno; \
    rm /tmp/deno.zip; \
    deno -V

WORKDIR /app

# ── مزوّد PO Token من مرحلة البناء ──
COPY --from=potbuilder /build/server /app/tools/bgutil-pot/server

# ── مكتبات بايثون (طبقة منفصلة لتستفيد من الكاش) ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── كود البوت ──
COPY . .

# مجلد البيانات الدائم: قاعدة البيانات والكوكيز
ENV DATA_DIR=/data \
    DOWNLOAD_DIR=/tmp/downloads \
    LOG_PATH=/tmp/bot.log \
    TOOLS_DIR=/app/tools \
    PORT=8080

RUN mkdir -p /data/cookies /tmp/downloads /app/tools/.deno_cache \
    && chmod -R 777 /app/tools/.deno_cache

# نُحمّل اعتماديات Deno وقت البناء.
# بدون هذا يستغرق أول توليد توكن أكثر من دقيقة فيتجاوز مهلة yt-dlp (15 ثانية)
# ويفشل يوتيوب صامتاً. نفس الأمر الذي يستدعيه المزوّد وقت التشغيل.
RUN cd /app/tools/bgutil-pot/server \
    && deno run --allow-env --allow-net --allow-ffi --allow-write --allow-read \
         src/generate_once.ts --version \
    && chmod -R 777 /app/tools/.deno_cache

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT}/health || exit 1

# tini يضمن إنهاءً نظيفاً للعمليات الفرعية (ffmpeg و deno)
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "bot.py"]
