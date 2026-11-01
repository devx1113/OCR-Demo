"""OpenAI API を実際に呼び出して、デモシナリオで期待する結果が得られるかを確認する（課金あり）。

    pytest -m live
"""
import os

import pytest
from conftest import REPLY, upload

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY が未設定")]


@pytest.fixture(autouse=True)
def isolated_data():
    """conftest の同名フィクスチャを無効化（このモジュールは live フィクスチャで一時ディレクトリを共有する）。"""


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """3資料（主仕様書・変更連絡書・回答メール）を AI 読解して解析した案件。モジュール内で共有して課金を抑える。"""
    import shutil
    import sys
    from pathlib import Path

    from fastapi.testclient import TestClient

    from app import ai, storage
    from app.config import MASTER
    from app.main import app

    root = tmp_path_factory.mktemp("live")
    (root / "projects").mkdir()
    shutil.copytree(MASTER, root / "master")
    mp = pytest.MonkeyPatch()
    mp.setattr(storage, "PROJECTS", root / "projects")
    mp.setattr(storage, "MASTER", root / "master")
    if storage.BACKEND == "db":
        from app import storage_db
        storage_db.truncate_all()
    client = TestClient(app, headers={"X-User": "%E5%B1%B1%E7%94%B0%20%E5%A4%AA%E9%83%8E"})
    p = client.post("/api/projects", json={"name": "live"}).json()
    for n in ("送水ポンプ制御盤_製作仕様書.pdf", "仕様補足・変更連絡書_No1.docx", REPLY):
        p = upload(client, p["id"], n).json()
    reads = {d["filename"]: client.post(f"/api/projects/{p['id']}/documents/{d['id']}/ai").json() for d in p["documents"]}
    p = client.post(f"/api/projects/{p['id']}/analyze").json()
    yield client, p, reads
    mp.undo()
    del sys, Path


def test_ai_reads_documents_with_verified_evidence(live):
    _, p, reads = live
    for name, r in reads.items():
        assert r["usage"]["seconds"] < 90, name
    assert reads["送水ポンプ制御盤_製作仕様書.pdf"]["stats"]["fields"] >= 20
    assert reads["送水ポンプ制御盤_製作仕様書.pdf"]["stats"]["components"] >= 15
    assert reads[REPLY]["stats"]["corrections"] >= 1
    assert p["analysis"]["ai"]["agreed"] >= 18                       # ルール抽出と AI が独立に同じ値を読んだ項目


def test_ai_fills_value_only_written_in_prose(live):
    _, p, _ = live
    f = {x["key"]: x for x in p["analysis"]["fields"]}
    assert "IP4X" in f["protection"]["value"] and f["protection"]["methods"] == ["ai"]
    assert f["protection"]["sources"][0]["doc_name"] == REPLY and f["protection"]["sources"][0]["page"] == 1
    assert f["main_power"]["status"] == "conflict" and "60Hz" in f["main_power"]["value"]
    for key in ("subject", "customer", "witness", "panel_name"):          # AI の誤読で余計な矛盾を作らない
        assert f[key]["status"] != "conflict", key
    assert not any(i["type"] == "ai_component" for i in p["analysis"]["issues"])
    assert any("50Hz" in n["summary"] for n in p["analysis"]["ai_notes"])


def test_ai_chat_answers_with_citations(live):
    client, p, _ = live
    r = client.post(f"/api/projects/{p['id']}/ai/ask", json={"question": "主回路電源の周波数は結局どちらが正しいですか？"}).json()
    msg = r["chat"][-1]
    assert "60" in msg["content"] and "[D" not in msg["content"]
    assert any(c["doc_name"] == REPLY for c in msg["citations"])
    r = client.post(f"/api/projects/{p['id']}/ai/ask", json={"question": "盤の重量は何kgと書かれていますか？"}).json()
    assert "記載" in r["chat"][-1]["content"]                          # 資料にないことは推測しない


def test_ai_design_review(live):
    client, p, _ = live
    r = client.post(f"/api/projects/{p['id']}/ai/review").json()["ai_review"]
    assert r["summary"] and 1 <= len(r["findings"]) <= 6
    assert {f["severity"] for f in r["findings"]} <= {"high", "medium", "low"}
    keys = {c["key"] for c in p["analysis"]["components"]} | {f["key"] for f in p["analysis"]["fields"]} | {""}
    assert sum(f["target_key"] in keys for f in r["findings"]) >= len(r["findings"]) - 1


@pytest.mark.parametrize("kind", ["quote", "questions"])
def test_ai_email_draft(live, kind):
    client, p, _ = live
    r = client.post(f"/api/projects/{p['id']}/ai/email", json={"kind": kind}).json()
    assert r["subject"] and "湊川水道設備" in r["body"] and "山田" in r["body"]
    if kind == "quote":
        assert p["quote_no"] in r["body"] and f"{p['analysis']['estimate']['sale_total']:,}" in r["body"]


def test_ai_ocr_reads_scanned_drawing_and_flags_old_depth(live):
    """スキャン図面（画像PDF）を AI-OCR で読み、寸法注記を取り出して仕様（変更後 D700）との相違を検出する。"""
    client, p, _ = live
    p = upload(client, p["id"], "外形図_スキャン.pdf").json()
    scan = next(d for d in p["documents"] if d["filename"] == "外形図_スキャン.pdf")
    r = client.post(f"/api/projects/{p['id']}/documents/{scan['id']}/ai").json()
    assert r["kind"] == "ocr" and r["stats"]["dimensions"] >= 3 and r["usage"]["seconds"] < 60
    a = client.post(f"/api/projects/{p['id']}/analyze").json()["analysis"]
    g = a["drawings"][0]
    assert {(i["axis"], i["drawing"]) for i in g["items"]} >= {("w", 800), ("h", 2000), ("d", 600)}
    assert [m["axis"] for m in g["mismatch"]] == ["d"] and g["mismatch"][0]["matches_before"]
    assert all(i["source"]["bbox"] for i in g["items"])               # 図面上の位置（ハイライト用）
