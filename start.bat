@echo off
chcp 65001 > nul
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo [1/3] Python 仮想環境を作成しています...
  py -3 -m venv .venv || python -m venv .venv
)
echo [2/3] 依存パッケージを確認しています...
.venv\Scripts\python -m pip install -q -r requirements.txt
if not exist frontend\dist\index.html (
  echo [3/3] 画面をビルドしています（初回のみ・Node.js が必要）...
  pushd frontend
  call npm install
  call npm run build
  popd
)
.venv\Scripts\python run.py %*
pause
