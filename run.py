"""盤見積アシスタント（デモ版）の起動スクリプト。

    python run.py            → http://127.0.0.1:8000 を開く
    python run.py --port 8080 --no-browser
"""
import argparse
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))


def main():
    ap = argparse.ArgumentParser(description="盤見積アシスタント デモ版")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("※ frontend/dist がありません。先に `cd frontend && npm install && npm run build` を実行してください。")

    import uvicorn

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"盤見積アシスタント デモ版を起動します → {url}  （終了: Ctrl+C）")
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
