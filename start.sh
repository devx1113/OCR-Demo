#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "[1/3] Python 仮想環境を作成しています..."
  python3 -m venv .venv
fi
echo "[2/3] 依存パッケージを確認しています..."
.venv/bin/python -m pip install -q -r requirements.txt
if [ ! -f frontend/dist/index.html ]; then
  echo "[3/3] 画面をビルドしています（初回のみ・Node.js が必要）..."
  (cd frontend && npm install && npm run build)
fi
exec .venv/bin/python run.py "$@"
