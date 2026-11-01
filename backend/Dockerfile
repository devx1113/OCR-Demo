# 盤見積アシスタント API（FastAPI + Prisma Client Python）
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Asia/Tokyo \
    PANEL_PROJECTS_DIR=/data/projects

# 見積書の PDF プレビューに LibreOffice（Calc）と日本語フォントを使う。不要なら --build-arg WITH_LIBREOFFICE=false で小さくできる
ARG WITH_LIBREOFFICE=true
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates curl \
 && if [ "$WITH_LIBREOFFICE" = "true" ]; then apt-get install -y --no-install-recommends libreoffice-calc-nogui fonts-noto-cjk; fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Prisma のクライアント生成（Prisma CLI・エンジンはここでダウンロードしてイメージに含める）
COPY backend/prisma backend/prisma
RUN cd backend && prisma generate && prisma --version

COPY backend backend
COPY samples samples
COPY docker/backend-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /data/projects

WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
ENTRYPOINT ["entrypoint.sh"]
