import os
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

# テスト時などに案件データ・マスタの保存先を切り替えられるようにする
PROJECTS = Path(os.environ.get("PANEL_PROJECTS_DIR") or PROJECTS)
MASTER = Path(os.environ.get("PANEL_MASTER_DIR") or MASTER)
PROJECTS.mkdir(parents=True, exist_ok=True)
