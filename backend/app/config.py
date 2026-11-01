import os
import shutil
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
DATA = BACKEND / "data"
MASTER = DATA / "master"
PROJECTS = DATA / "projects"
TEMPLATES = DATA / "templates"
SAMPLES = ROOT / "samples"
FRONTEND_DIST = ROOT / "frontend" / "dist"

ESTIMATE_TEMPLATE = TEMPLATES / "estimate_template.xlsx"
CELLMAP = TEMPLATES / "cellmap.json"

ALLOWED_EXT = {".pdf", ".docx", ".xlsx"}
AI_SETTINGS = MASTER / "ai.json"
MAX_UPLOAD_MB = 50



def _load_env():
    """プロジェクト直下の .env を読み込む（API キーをソースコードに書かないため）。既存の環境変数を優先する。"""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

# Vercel などのサーバーレス環境：書き込めるのは /tmp だけで、内容はインスタンスの入れ替えで消える。
# 案件は /tmp に置き、マスタは同梱の初期データを /tmp に写して使う（公開デモ用。データは保持されない）
SERVERLESS = bool(os.environ.get("VERCEL")) or not os.access(DATA, os.W_OK)
if SERVERLESS:
    TMP = Path("/tmp/panel")
    PROJECTS = TMP / "projects"
    if not os.environ.get("PANEL_MASTER_DIR") and not (TMP / "master").exists():
        (TMP / "master").mkdir(parents=True)
        for f in MASTER.glob("*.json"):  # 中身だけ写す（同梱ファイルの読み取り専用の属性は引き継がない）
            shutil.copyfile(f, TMP / "master" / f.name)
    MASTER = TMP / "master"
    MAX_UPLOAD_MB = 4  # Vercel の要求本文の上限 4.5MB（マルチパートの分を差し引く）

# テスト時などに案件データ・マスタの保存先を切り替えられるようにする
PROJECTS = Path(os.environ.get("PANEL_PROJECTS_DIR") or PROJECTS)
MASTER = Path(os.environ.get("PANEL_MASTER_DIR") or MASTER)
PROJECTS.mkdir(parents=True, exist_ok=True)
