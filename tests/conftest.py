import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import ai, storage  # noqa: E402,F401
from app.config import MASTER, SAMPLES  # noqa: E402

DEMO = ("送水ポンプ制御盤_製作仕様書.pdf", "仕様補足・変更連絡書_No1.docx", "外形図_スキャン.pdf")
REPLY = "顧客回答メール_仕様確認.pdf"


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """案件・マスタ・AI 設定をテスト用の一時ディレクトリに切り替える（本物のデータを汚さない）。
    DATABASE_URL を指定して実行した場合は、テストごとにデータベースを空にする（テスト専用の DB を使うこと）。"""
    projects = tmp_path / "projects"
    projects.mkdir()
    master = tmp_path / "master"
    shutil.copytree(MASTER, master)
    monkeypatch.setattr(storage, "PROJECTS", projects)
    monkeypatch.setattr(storage, "MASTER", master)
    if storage.BACKEND == "db":
        from app import storage_db
        storage_db.truncate_all()
    return tmp_path


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, headers={"X-User": "%E5%B1%B1%E7%94%B0%20%E5%A4%AA%E9%83%8E"})  # 山田 太郎


SATO = "%E4%BD%90%E8%97%A4%20%E8%8A%B1%E5%AD%90"      # 佐藤 花子（設計課長：承認・マスタ変更の権限あり）
SUZUKI = "%E9%88%B4%E6%9C%A8%20%E4%B8%80%E9%83%8E"    # 鈴木 一郎（営業担当：閲覧・承認済み見積の出力のみ）


@pytest.fixture
def manager():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, headers={"X-User": SATO})


@pytest.fixture
def sales():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, headers={"X-User": SUZUKI})


@pytest.fixture
def demo(client):
    """ルール抽出のみで解析したデモ案件。"""
    r = client.post("/api/projects/demo")
    assert r.status_code == 200
    return r.json()


def upload(client, pid, name):
    with open(SAMPLES / name, "rb") as f:
        return client.post(f"/api/projects/{pid}/documents", files={"file": (name, f)})


class FakeAI:
    """OpenAI を呼ばずに、構造化出力の応答を返す偽物。呼び出し内容を記録する。"""

    def __init__(self):
        self.calls = []
        self.responses = {}

    def __call__(self, model, system, user, schema, name, effort="low", images=None):
        self.calls.append({"model": model, "name": name, "user": user, "schema": schema, "images": len(images or [])})
        resp = self.responses.get(name)
        if callable(resp):
            resp = resp(user, schema)
        if resp is None:
            resp = {"extraction": {"fields": [], "components": [], "corrections": []},
                    "recheck": {"fields": [], "components": [], "corrections": []},
                    "answer": {"answer": "資料には記載がありません。", "citations": []},
                    "review": {"summary": "大きな問題はありません。", "findings": []},
                    "email": {"subject": "件名", "body": "本文"},
                    "ocr": {"doc_kind": "外形図", "title": "OUTLINE DRAWING", "drawing_no": "CP-101", "scale": "1:20",
                            "lines": [{"text": "H2000", "page": 1}, {"text": "W800", "page": 1}, {"text": "D600", "page": 1},
                                      {"text": "OUTLINE DRAWING CP-101 SCALE 1:20", "page": 1}],
                            "dimensions": [{"axis": "W", "value_mm": 800, "text": "W800", "page": 1, "bbox": [0.38, 0.87, 0.48, 0.91]},
                                           {"axis": "H", "value_mm": 2000, "text": "H2000", "page": 1, "bbox": [0.27, 0.48, 0.33, 0.52]},
                                           {"axis": "D", "value_mm": 600, "text": "D600", "page": 1, "bbox": [0.69, 0.85, 0.74, 0.89]}]},
                    "ping": {"reply": "接続OK"}}[name]
        return json.loads(json.dumps(resp)), {"model": model, "seconds": 0.01, "input_tokens": 10, "output_tokens": 5}


@pytest.fixture
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    monkeypatch.setattr(ai, "call_json", fake)
    return fake
