#!/bin/sh
# 起動のたびに未適用のマイグレーションを適用してから API を起動する。
# 引数を付けた場合（例：python -m app.import_json /import）は、マイグレーション後にそのコマンドを実行する
set -e
cd /app/backend
prisma migrate deploy
if [ "$#" -gt 0 ]; then
  exec "$@"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WORKERS:-1}" --proxy-headers
