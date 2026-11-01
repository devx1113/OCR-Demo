"""探索テストで見つかった不具合の再発防止（セキュリティ・不正入力・同時操作・AI 障害時の扱い）。"""
import io
import threading
import time

import pytest
from openpyxl import load_workbook

from app import ai, main, storage
from app.config import FRONTEND_DIST

from conftest import upload


# ---------- 配信・ID ----------

@pytest.mark.skipif(not (FRONTEND_DIST / "index.html").exists(), reason="フロントエンド未ビルド")
@pytest.mark.parametrize("path", ["/..%2F..%2F.env", "/%2e%2e/%2e%2e/.env", "/" + "..%2F" * 12 + "etc%2Fpasswd"])
def test_spa_route_does_not_serve_files_outside_dist(client, path):
    r = client.get(path)
    assert "OPENAI_API_KEY" not in r.text and "root:" not in r.text
    assert "<!doctype html>" in r.text.lower()


def test_unknown_api_path_is_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["detail"]


@pytest.mark.parametrize("pid", ["xyz", "..", "000000000000x"])
def test_invalid_project_id_is_404(client, pid):
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_invalid_document_id_is_404(client, demo):
    assert client.get(f"/api/projects/{demo['id']}/documents/..x/parsed").status_code == 404


# ---------- 不正な入力は 500 ではなく 422 / 409 ----------

@pytest.mark.parametrize("method,path,body", [
    ("POST", "/api/projects", {"name": 123}),
    ("PATCH", "/api/projects/{pid}", {"name": ""}),
    ("PATCH", "/api/projects/{pid}", {"due_date": "not-a-date"}),
    ("POST", "/api/projects/{pid}/fields/main_power", {"action": "choose", "choice": 99}),
    ("POST", "/api/projects/{pid}/fields/main_power", {"action": "choose", "choice": "abc"}),
    ("POST", "/api/projects/{pid}/components/no1", {"qty": "abc"}),
    ("POST", "/api/projects/{pid}/components/no1", {"qty": 1e9}),          # 以前は配置計算でメモリを使い切った
    ("POST", "/api/projects/{pid}/components/no1", {"qty": -3}),
    ("POST", "/api/projects/{pid}/components/no1", {"model": 123}),
    ("POST", "/api/projects/{pid}/components", {"name": "x", "qty": "abc"}),
    ("PATCH", "/api/projects/{pid}/settings", {"margin": "abc"}),
    ("PATCH", "/api/projects/{pid}/settings", {"enclosure_id": "NOPE"}),
    ("PATCH", "/api/projects/{pid}/settings", {"include_fan": "no"}),
    ("POST", "/api/projects/{pid}/estimate/lines/enc", {"unit_cost": "abc"}),
    ("POST", "/api/projects/{pid}/estimate/lines/enc", {"qty": -1}),
    ("POST", "/api/projects/{pid}/questions", {"question": 5}),
    ("PATCH", "/api/projects/{pid}/documents/{did}", {"role": "bogus"}),
    ("PATCH", "/api/projects/{pid}/documents/{did}", {"include": "yes"}),
    ("PUT", "/api/ai/settings", {"model": "bogus-model"}),
    ("PUT", "/api/ai/settings", {"enabled": "yes"}),
])
def test_bad_input_is_rejected_cleanly(client, manager, demo, method, path, body):
    url = path.format(pid=demo["id"], did=demo["documents"][0]["id"])
    r = (manager if path.startswith("/api/ai/settings") else client).request(method, url, json=body)
    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], (str, list))


def test_choose_on_field_without_candidates_is_409(client, demo):
    r = client.post(f"/api/projects/{demo['id']}/fields/subject", json={"action": "choose", "choice": 0})
    assert r.status_code == 409


def test_failed_validation_does_not_persist_override(client, demo):
    pid = demo["id"]
    client.post(f"/api/projects/{pid}/components/no1", json={"qty": "abc"})
    p = client.get(f"/api/projects/{pid}").json()
    assert "qty" not in p.get("component_overrides", {}).get("no1", {})
    assert client.post(f"/api/projects/{pid}/analyze").status_code == 200


@pytest.mark.parametrize("name,body", [
    ("parts", {}),
    ("parts", [{"model": "X"}]),
    ("parts", [{"model": "A", "name": "a", "price": "高い"}]),
    ("enclosures", []),
    ("rules", {}),
    ("dictionary", {}),
])
def test_broken_master_is_rejected(manager, name, body):
    assert manager.put(f"/api/master/{name}", json=body).status_code == 422


def test_rule_round_unit_zero_is_rejected_and_estimate_survives(client, manager, demo):
    rules = client.get("/api/master/rules").json()
    rules["cost"]["round_unit"] = 0
    assert manager.put("/api/master/rules", json=rules).status_code == 422
    assert client.post(f"/api/projects/{demo['id']}/analyze").status_code == 200


# ---------- 取込 ----------

def test_extension_mismatch_is_reported(client, demo):
    from docx import Document
    b = io.BytesIO()
    Document().save(b)
    p = client.post(f"/api/projects/{demo['id']}/documents", files={"file": ("偽装.pdf", b.getvalue())}).json()
    d = p["documents"][-1]
    assert d["status"] == "error" and "中身は Word" in d["messages"][0]


def test_empty_docx_is_warning_not_main_spec(client):
    from docx import Document
    pid = client.post("/api/projects", json={"name": "空資料"}).json()["id"]
    b = io.BytesIO()
    Document().save(b)
    d = client.post(f"/api/projects/{pid}/documents", files={"file": ("空.docx", b.getvalue())}).json()["documents"][-1]
    assert d["status"] == "warning" and d["role"] == "other"


# ---------- Excel 出力 ----------

def test_excel_export_never_writes_document_text_as_formula(client, demo):
    pid = demo["id"]
    client.post(f"/api/projects/{pid}/fields/customer", json={"action": "edit", "value": '=HYPERLINK("http://example.invalid","x")'})
    client.post(f"/api/projects/{pid}/questions", json={"question": "=2*3"})
    client.post(f"/api/projects/{pid}/components", json={"name": "=evil()", "model": "=X()", "qty": 1})
    for kind in ("estimate", "questions", "basis"):
        wb = load_workbook(io.BytesIO(client.get(f"/api/projects/{pid}/export/{kind}?force=true").content))
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and any(k in c.value for k in ("HYPERLINK", "2*3", "evil", "X()")):
                        assert c.data_type == "s", f"{kind} {ws.title}!{c.coordinate} が数式になっています"
    # 雛形側の数式（合計など）は残っている
    wb = load_workbook(io.BytesIO(client.get(f"/api/projects/{pid}/export/estimate?force=true").content))
    assert any(c.data_type == "f" for ws in wb.worksheets for row in ws.iter_rows() for c in row)


# ---------- AI の待ち時間中の操作を上書きしない ----------

@pytest.mark.parametrize("label,call", [
    ("review", lambda c, pid: c.post(f"/api/projects/{pid}/ai/review")),
    ("ask", lambda c, pid: c.post(f"/api/projects/{pid}/ai/ask", json={"question": "電源は？"})),
    ("email", lambda c, pid: c.post(f"/api/projects/{pid}/ai/email", json={"kind": "quote"})),
])
def test_ai_call_does_not_overwrite_concurrent_edits(client, demo, fake_ai, monkeypatch, label, call):
    pid = demo["id"]

    def slow(*a, **k):
        time.sleep(0.8)
        return fake_ai(*a, **k)
    monkeypatch.setattr(ai, "call_json", slow)
    t = threading.Thread(target=lambda: call(client, pid))
    t.start()
    time.sleep(0.3)
    client.post(f"/api/projects/{pid}/questions", json={"question": f"{label} の待ち時間中に追加"})
    t.join()
    p = client.get(f"/api/projects/{pid}").json()
    assert any(label in q["question"] for q in p["custom_questions"])
    if label == "review":
        assert p.get("ai_review")
    if label == "ask":
        assert p["chat"][-1]["role"] == "assistant"


def test_ask_without_usable_documents_is_409(client, fake_ai):
    pid = client.post("/api/projects", json={"name": "空"}).json()["id"]
    assert client.post(f"/api/projects/{pid}/ai/ask", json={"question": "電源は？"}).status_code == 409


# ---------- AI 障害時の文言 ----------

def _openai_error(kind):
    import httpx
    import openai
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp = lambda code: httpx.Response(code, request=req)  # noqa: E731
    return {
        "timeout": openai.APITimeoutError(request=req),
        "conn": openai.APIConnectionError(request=req),
        "auth": openai.AuthenticationError("bad key", response=resp(401), body=None),
        "rate": openai.RateLimitError("slow down", response=resp(429), body=None),
        "model": openai.NotFoundError("no model", response=resp(404), body=None),
        "server": openai.InternalServerError("boom", response=resp(500), body=None),
    }[kind]


@pytest.mark.parametrize("kind,expect", [
    ("timeout", "ネットワーク"), ("conn", "ネットワーク"), ("auth", "キーが無効"),
    ("rate", "利用上限"), ("model", "モデル"), ("server", "HTTP 500"),
])
def test_openai_errors_are_explained_in_japanese(kind, expect):
    assert expect in ai._explain(_openai_error(kind))


def test_ai_read_failure_is_502_and_analysis_still_works(client, demo, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def boom(*a, **k):
        raise ai.AIError(ai._explain(_openai_error("conn")))
    monkeypatch.setattr(ai, "call_json", boom)
    pid = demo["id"]
    did = demo["documents"][0]["id"]
    r = client.post(f"/api/projects/{pid}/documents/{did}/ai", params={"force": True})
    assert r.status_code == 502 and "ネットワーク" in r.json()["detail"]
    assert client.post(f"/api/projects/{pid}/analyze").status_code == 200


@pytest.mark.skipif(storage.BACKEND == "db", reason="JSON ファイル保存のときだけの検査")
def test_list_projects_skips_corrupted_project_file(client, demo):
    bad = storage.PROJECTS / "0123456789ab"
    bad.mkdir()
    (bad / "project.json").write_text("{broken", encoding="utf-8")
    r = client.get("/api/projects")
    assert r.status_code == 200 and [p["id"] for p in r.json()] == [demo["id"]]


def test_main_module_exposes_validation_limits():
    assert main.MAX_QTY == 999
