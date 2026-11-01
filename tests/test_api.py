"""API の全エンドポイント（取込・修正・承認・出力・マスタ・AI 連携の配線）を検証する。"""
import io
import shutil

import pytest
from conftest import REPLY, SAMPLES, upload
from openpyxl import load_workbook

from app import ai


def test_health_and_ai_status(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    h = client.get("/api/health").json()
    assert h["ok"] and h["ai"]["configured"] is False and h["ai"]["enabled"] is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert client.get("/api/health").json()["ai"]["enabled"] is True


def test_project_crud(client):
    assert client.post("/api/projects", json={"name": "  "}).status_code == 422
    p = client.post("/api/projects", json={"name": "案件A", "customer": "顧客"}).json()
    assert p["quote_no"].endswith("-0001") and p["status"] == "資料待ち"
    p2 = client.post("/api/projects", json={"name": "案件B"}).json()
    assert p2["quote_no"].endswith("-0002")
    assert client.patch(f"/api/projects/{p['id']}", json={"name": "案件A改"}).json()["name"] == "案件A改"
    assert [x["name"] for x in client.get("/api/projects").json()] == ["案件B", "案件A改"]
    assert client.delete(f"/api/projects/{p['id']}").json() == {"ok": True}
    assert client.get(f"/api/projects/{p['id']}").status_code == 404


def test_demo_without_analysis(client):
    p = client.post("/api/projects/demo?analyze=false").json()
    assert "analysis" not in p and len(p["documents"]) == 3 and p["status"] == "解析待ち"
    roles = {d["filename"]: d["role"] for d in p["documents"]}
    assert roles == {"送水ポンプ制御盤_製作仕様書.pdf": "main", "仕様補足・変更連絡書_No1.docx": "supplement",
                     "外形図_スキャン.pdf": "drawing"}


def test_upload_checks(client, tmp_path):
    p = client.post("/api/projects", json={"name": "取込"}).json()
    assert upload(client, p["id"], "送水ポンプ制御盤_製作仕様書.pdf").status_code == 200
    dup = upload(client, p["id"], "送水ポンプ制御盤_製作仕様書.pdf")
    assert dup.status_code == 409 and "既に登録" in dup.json()["detail"]
    r = client.post(f"/api/projects/{p['id']}/documents", files={"file": ("memo.txt", io.BytesIO(b"hello"))}).json()
    bad = [d for d in r["documents"] if d["filename"] == "memo.txt"][0]
    assert bad["status"] == "error" and "未対応" in bad["messages"][0]
    r = client.post(f"/api/projects/{p['id']}/samples/reply").json()
    assert any(d["filename"] == REPLY for d in r["documents"])
    assert client.post(f"/api/projects/{p['id']}/samples/unknown").status_code == 404
    did = r["documents"][0]["id"]
    assert client.get(f"/api/projects/{p['id']}/documents/{did}/file").status_code == 200
    assert client.get(f"/api/projects/{p['id']}/documents/{did}/parsed").json()["format"] == "pdf"
    r = client.patch(f"/api/projects/{p['id']}/documents/{did}", json={"role": "supplement", "include": False}).json()
    assert r["documents"][0]["role"] == "supplement" and r["documents"][0]["include"] is False
    r = client.delete(f"/api/projects/{p['id']}/documents/{did}").json()
    assert all(d["id"] != did for d in r["documents"])


def test_stale_flag_after_upload(client, demo):
    r = upload(client, demo["id"], REPLY).json()
    assert r["analysis_stale"] and r["status"] == "解析待ち"
    r = client.post(f"/api/projects/{demo['id']}/analyze").json()
    assert not r["analysis_stale"]


def test_field_actions_and_reset(client, demo):
    pid = demo["id"]
    assert client.post(f"/api/projects/{pid}/fields/protection", json={"action": "bogus"}).status_code == 422
    assert client.post(f"/api/projects/{pid}/fields/nope", json={"action": "confirm"}).status_code == 404
    r = client.post(f"/api/projects/{pid}/fields/location", json={"action": "confirm"}).json()
    assert {f["key"]: f for f in r["analysis"]["fields"]}["location"]["status"] == "confirmed"
    r = client.delete(f"/api/projects/{pid}/fields/location").json()
    assert {f["key"]: f for f in r["analysis"]["fields"]}["location"]["status"] == "inferred"
    assert r["history"][0]["action"] == "修正の取消" and r["history"][0]["user"] == "山田 太郎"


def test_estimate_line_edit_margin_and_reset(client, demo):
    pid = demo["id"]
    r = client.post(f"/api/projects/{pid}/estimate/lines/eq-no20", json={"unit_cost": 15000}).json()
    line = [l for l in r["analysis"]["estimate"]["lines"] if l["id"] == "eq-no20"][0]
    assert line["cost"] == 15000 and "edited" in line["flags"] and "rfq" not in line["flags"]
    before = r["analysis"]["estimate"]["sale_total"]
    r = client.patch(f"/api/projects/{pid}/settings", json={"margin": 0.3}).json()
    assert r["analysis"]["estimate"]["margin"] == 0.3 and r["analysis"]["estimate"]["sale_total"] > before
    assert client.patch(f"/api/projects/{pid}/settings", json={"margin": 5}).json()["analysis"]["estimate"]["margin"] == 0.6
    r = client.delete(f"/api/projects/{pid}/estimate/lines/eq-no20").json()
    assert "rfq" in [l for l in r["analysis"]["estimate"]["lines"] if l["id"] == "eq-no20"][0]["flags"]
    r = client.patch(f"/api/projects/{pid}/settings", json={"include_fan": False}).json()
    assert not any(c.get("recommended") for c in r["analysis"]["components"])


def test_custom_questions(client, demo):
    pid = demo["id"]
    assert client.post(f"/api/projects/{pid}/questions", json={"question": " "}).status_code == 422
    r = client.post(f"/api/projects/{pid}/questions", json={"question": "立会検査の人数をご教示ください"}).json()
    q = r["analysis"]["questions"][-1]
    assert q["custom_id"] and q["no"] == len(r["analysis"]["questions"])
    r = client.delete(f"/api/projects/{pid}/questions/{q['custom_id']}").json()
    assert all(not x.get("custom_id") for x in r["analysis"]["questions"])


def _resolve_all(client, pid):
    client.post(f"/api/projects/{pid}/fields/main_power", json={"action": "choose", "choice": 0})
    client.post(f"/api/projects/{pid}/fields/protection", json={"action": "edit", "value": "IP4X"})
    return client.patch(f"/api/projects/{pid}/settings", json={"enclosure_id": "ST-9007"}).json()


def test_approval_rules(client, manager, demo):
    pid = demo["id"]
    r = manager.post(f"/api/projects/{pid}/approve", json={})
    assert r.status_code == 409 and "3 件" in r.json()["detail"]
    _resolve_all(client, pid)
    assert client.post(f"/api/projects/{pid}/approve", json={}).status_code == 403      # 設計担当は承認できない
    r = manager.post(f"/api/projects/{pid}/approve", json={"comment": "OK"}).json()
    assert r["approval"]["status"] == "approved" and r["status"] == "承認済"
    r = client.post(f"/api/projects/{pid}/components/no11", json={"qty": 11}).json()
    assert r["approval"]["status"] == "revoked" and r["history"][0]["action"] == "承認取消"
    manager.post(f"/api/projects/{pid}/approve", json={})
    assert manager.post(f"/api/projects/{pid}/unapprove").json()["approval"]["status"] == "revoked"


def test_exports_blocked_then_forced(client, demo):
    pid = demo["id"]
    r = client.get(f"/api/projects/{pid}/export/estimate")
    assert r.status_code == 409 and len(r.json()["blocking"]) == 3
    r = client.get(f"/api/projects/{pid}/export/estimate?force=true")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert wb["御見積書"]["H1"].value == "【未承認ドラフト・要確認事項あり】"


def test_estimate_excel_content_after_approval(client, manager, demo):
    pid = demo["id"]
    _resolve_all(client, pid)
    p = manager.post(f"/api/projects/{pid}/approve", json={}).json()
    r = client.get(f"/api/projects/{pid}/export/estimate")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    cv = wb["御見積書"]
    assert cv["B4"].value == "湊川水道設備株式会社" and cv["H4"].value == p["quote_no"]
    assert cv["H1"].value in ("", None) and cv["H17"].value == "佐藤 花子"
    assert cv["C11"].value == "第二浄水場 送水ポンプ設備更新工事（送水ポンプ制御盤 CP-101）"
    assert cv["I20"].value == '=IF(F20="","",F20*H20)' and cv["C9"].value == "=I32"     # 雛形の数式を保持
    assert cv["I30"].value == "=SUM(I20:I29)"
    est = p["analysis"]["estimate"]
    rows = [(cv[f"C{r}"].value, cv[f"F{r}"].value, cv[f"H{r}"].value) for r in range(20, 30) if cv[f"C{r}"].value]
    assert len(rows) == len(est["customer_lines"])
    assert sum(q * u for _, q, u in rows) == est["sale_total"]                              # Excel の計算結果と一致
    assert cv["B35"].value.startswith("見積範囲") and any("W900" in (cv[f"B{r}"].value or "") for r in range(35, 45))
    eq = wb["主要機器構成"]
    assert eq["C7"].value == "INV-11K" and eq["G7"].value == "変更連絡により変更"
    assert client.get(f"/api/projects/{pid}").json()["status"] == "出力済"


def test_questions_and_basis_exports(client, demo):
    pid = demo["id"]
    wb = load_workbook(io.BytesIO(client.get(f"/api/projects/{pid}/export/questions").content))
    ws = wb["質疑書"]
    assert ws["A4"].value == "No" and ws["B5"].value == "資料間の相違" and "50Hz" in ws["D5"].value
    wb = load_workbook(io.BytesIO(client.get(f"/api/projects/{pid}/export/basis").content))
    assert wb.sheetnames == ["抽出項目", "構成機器", "収容判定", "原価内訳", "変更履歴"]
    assert wb["収容判定"]["A1"].value == "収容判定：不可"
    assert client.get(f"/api/projects/{pid}/export/unknown").status_code == 404


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice がない環境")
def test_estimate_pdf_preview(client, demo):
    r = client.get(f"/api/projects/{demo['id']}/export/estimate-pdf?force=true")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_master_roundtrip_affects_analysis(client, manager, demo):
    parts = client.get("/api/master/parts").json()
    for p in parts:
        if p["model"] == "SPD-3P":
            p["price"] = 24000
    assert client.put("/api/master/parts", json=parts).status_code == 403    # マスタ変更は権限者のみ
    assert manager.put("/api/master/parts", json=parts).json()["ok"]
    a = client.post(f"/api/projects/{demo['id']}/analyze").json()["analysis"]
    assert {l["id"]: l for l in a["estimate"]["lines"]}["eq-no20"]["cost"] == 24000
    rules = client.get("/api/master/rules").json()
    rules["layout"]["max_occupancy"] = 0.9
    manager.put("/api/master/rules", json=rules)
    assert client.get("/api/master/rules").json()["layout"]["max_occupancy"] == 0.9
    assert client.get("/api/master/cellmap").json()["lines"]["start_row"] == 20
    assert client.get("/api/master/nope").status_code == 404


# ---------- AI 連携の配線（偽 AI） ----------

def test_ai_endpoints_require_key(client, demo, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    did = demo["documents"][0]["id"]
    assert client.post(f"/api/projects/{demo['id']}/documents/{did}/ai").status_code == 503
    assert client.post(f"/api/projects/{demo['id']}/ai/ask", json={"question": "?"}).status_code == 503
    assert client.post("/api/ai/test").status_code == 503


def test_ai_settings_and_disable(client, manager, fake_ai):
    s = manager.put("/api/ai/settings", json={"model": "gpt-5.4", "enabled": False}).json()
    assert s["model"] == "gpt-5.4" and s["enabled"] is False and "gpt-5.5" in s["models"]
    assert client.post("/api/ai/test").status_code == 503
    manager.put("/api/ai/settings", json={"enabled": True})
    r = client.post("/api/ai/test").json()
    assert r["reply"] == "接続OK" and fake_ai.calls[-1]["model"] == "gpt-5.4"


def test_ai_document_read_endpoint(client, demo, fake_ai):
    scan = [d for d in demo["documents"] if d["filename"] == "外形図_スキャン.pdf"][0]
    r = client.post(f"/api/projects/{demo['id']}/documents/{scan['id']}/ai").json()      # 画像PDFは AI-OCR で読む
    assert r["kind"] == "ocr" and r["stats"]["dimensions"] == 3 and fake_ai.calls[-1]["images"] == 1
    main = demo["documents"][0]
    r = client.post(f"/api/projects/{demo['id']}/documents/{main['id']}/ai").json()
    assert r["cached"] is False and r["stats"]["fields"] == 0
    assert client.post(f"/api/projects/{demo['id']}/documents/{main['id']}/ai").json()["cached"] is True
    assert client.post(f"/api/projects/{demo['id']}/documents/{main['id']}/ai?force=true").json()["cached"] is False
    p = client.get(f"/api/projects/{demo['id']}").json()
    assert p["analysis_stale"] and p["history"][0]["action"] == "AI 読解"


def test_ai_errors_are_reported(client, demo, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")

    def boom(*a, **k):
        raise ai.AIError("OpenAI API の呼び出しに失敗しました：rate limit")
    monkeypatch.setattr(ai, "call_json", boom)
    r = client.post(f"/api/projects/{demo['id']}/ai/review")
    assert r.status_code == 502 and "rate limit" in r.json()["detail"]


def test_ai_chat_review_email(client, demo, fake_ai):
    pid = demo["id"]
    assert client.post(f"/api/projects/{pid}/ai/ask", json={"question": ""}).status_code == 422
    r = client.post(f"/api/projects/{pid}/ai/ask", json={"question": "納期は？"}).json()
    assert [m["role"] for m in r["chat"]] == ["user", "assistant"] and r["chat"][0]["user"] == "山田 太郎"
    client.post(f"/api/projects/{pid}/ai/ask", json={"question": "立会は？"})
    assert "納期は？" in fake_ai.calls[-1]["user"]                                     # 会話履歴を渡す
    assert client.delete(f"/api/projects/{pid}/ai/chat").json()["chat"] == []

    fake_ai.responses["review"] = {"summary": "主幹容量の確認が必要", "findings": [
        {"severity": "high", "category": "容量・保護協調", "title": "主幹MCCBの容量", "detail": "75ATでは不足の可能性", "target_key": "no1"}]}
    r = client.post(f"/api/projects/{pid}/ai/review").json()
    assert r["ai_review"]["findings"][0]["target_key"] == "no1" and r["ai_review"]["analyzed_at"] == r["analysis"]["analyzed_at"]
    assert fake_ai.calls[-1]["model"] == "gpt-5.5"

    fake_ai.responses["email"] = lambda user, schema: {"subject": "お見積書送付の件", "body": user}
    e = client.post(f"/api/projects/{pid}/ai/email", json={"kind": "quote"}).json()
    assert e["subject"] == "お見積書送付の件" and demo["quote_no"] in e["body"] and "2,270,000円" in e["body"]
    assert client.post(f"/api/projects/{pid}/ai/email", json={"kind": "x"}).status_code == 422


def test_spa_fallback(client):
    from app.config import FRONTEND_DIST
    if not (FRONTEND_DIST / "index.html").exists():
        pytest.skip("フロントエンド未ビルド")
    r = client.get("/projects/abc/review")
    assert r.status_code == 200 and "<div id=\"root\">" in r.text
    assert (SAMPLES / REPLY).exists()
