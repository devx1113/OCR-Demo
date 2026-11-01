"""追加機能：画像PDFの AI-OCR と図面照合、権限と承認フロー、見積の版と比較、同時編集の保護、精度レポート。"""


def _scan(p):
    return next(d for d in p["documents"] if d["filename"] == "外形図_スキャン.pdf")


def _resolve_all(client, pid):
    client.post(f"/api/projects/{pid}/fields/main_power", json={"action": "choose", "choice": 0})
    client.post(f"/api/projects/{pid}/fields/protection", json={"action": "edit", "value": "IP4X"})
    return client.patch(f"/api/projects/{pid}/settings", json={"enclosure_id": "ST-9007"}).json()


# ---------- 画像PDF・スキャン図面の AI-OCR ----------

def test_ocr_reads_drawing_and_flags_outdated_depth(client, demo, fake_ai):
    pid = demo["id"]
    r = client.post(f"/api/projects/{pid}/documents/{_scan(demo)['id']}/ai").json()
    assert r["kind"] == "ocr" and r["stats"] == {**r["stats"], "lines": 4, "dimensions": 3, "rejected": 0}
    a = client.post(f"/api/projects/{pid}/analyze").json()["analysis"]
    g = a["drawings"][0]
    assert g["drawing_no"] == "CP-101" and [(i["axis"], i["drawing"], i["spec"], i["match"]) for i in g["items"]] == [
        ("w", 800, 800, True), ("h", 2000, 2000, True), ("d", 600, 700, False)]
    assert g["mismatch"][0]["matches_before"]                         # 変更連絡の「変更前 60cm」と一致 → 旧版の図面
    bbox = g["items"][0]["source"]["bbox"]
    assert bbox and 300 < bbox[0] < 340 and 500 < bbox[1] < 520       # 比率 → PDF 座標（842×595pt）に換算
    issue = next(i for i in a["issues"] if i["type"] == "drawing")
    assert not issue["blocking"] and "旧版の図面" in issue["detail"] and issue["target"]["key"] == "outer_dims"
    assert not any(i["type"] == "document" for i in a["issues"])     # 読み取れたので「抽出対象外」は出さない
    q = next(q for q in a["questions"] if q["category"] == "図面と仕様の相違")
    assert "最新の図面" in q["question"] and "図番 CP-101" in q["question"]
    assert any("外形寸法は仕様書・変更連絡の値" in c for c in a["conditions"])


def test_ocr_rejects_dimension_not_in_transcription(client, demo, fake_ai):
    fake_ai.responses["ocr"] = {
        "doc_kind": "外形図", "title": "", "drawing_no": "", "scale": "", "lines": [{"text": "W800", "page": 1}],
        "dimensions": [{"axis": "W", "value_mm": 800, "text": "W800", "page": 1, "bbox": [0.1, 0.1, 0.2, 0.2]},
                       {"axis": "D", "value_mm": 650, "text": "D650", "page": 1, "bbox": [0.1, 0.1, 0.2, 0.2]},   # 書き起こしにない
                       {"axis": "H", "value_mm": 1900, "text": "W800", "page": 1, "bbox": [2, 0, 1, 1]}]}          # 数値が注記と不一致
    r = client.post(f"/api/projects/{demo['id']}/documents/{_scan(demo)['id']}/ai").json()
    assert r["stats"]["dimensions"] == 1 and r["stats"]["rejected"] == 2
    a = client.post(f"/api/projects/{demo['id']}/analyze").json()["analysis"]
    assert a["drawings"][0]["mismatch"] == [] and not any(i["type"] == "drawing" for i in a["issues"])


def test_ocr_is_cached_and_used_as_qa_evidence(client, demo, fake_ai):
    pid, did = demo["id"], _scan(demo)["id"]
    client.post(f"/api/projects/{pid}/documents/{did}/ai")
    assert client.post(f"/api/projects/{pid}/documents/{did}/ai").json()["cached"] is True
    fake_ai.responses["answer"] = lambda user, schema: {
        "answer": "外形図では奥行 600mm です。", "citations": [{"evidence_id": next(
            ln.split("]")[0][1:] for ln in user.splitlines() if ln.startswith("[") and ":ocr" in ln and "D600" in ln), "quote": "D600"}]}
    p = client.post(f"/api/projects/{pid}/ai/ask", json={"question": "図面の奥行は？"}).json()
    assert "外形図_スキャン.pdf" in fake_ai.calls[-1]["user"] and "AI-OCR" in fake_ai.calls[-1]["user"]
    cite = p["chat"][-1]["citations"][0]
    assert cite["doc_id"] == did and cite["text"] == "D600"


def test_ocr_ignored_when_ai_disabled_for_project(client, demo, fake_ai):
    pid = demo["id"]
    client.post(f"/api/projects/{pid}/documents/{_scan(demo)['id']}/ai")
    client.patch(f"/api/projects/{pid}/settings", json={"ai": False})
    a = client.post(f"/api/projects/{pid}/analyze").json()["analysis"]
    assert a["drawings"] == [] and any(i["type"] == "document" for i in a["issues"])


# ---------- 権限と承認フロー ----------

def test_sales_is_read_only_but_can_export_approved_quote(client, manager, sales, demo):
    pid = demo["id"]
    r = sales.post(f"/api/projects/{pid}/fields/customer", json={"action": "edit", "value": "X"})
    assert r.status_code == 403 and "営業担当" in r.json()["detail"]
    assert sales.post("/api/projects", json={"name": "x"}).status_code == 403
    assert sales.get(f"/api/projects/{pid}/export/estimate?force=true").status_code == 403    # 承認前のドラフトは不可
    assert sales.get(f"/api/projects/{pid}/export/questions").status_code == 200
    _resolve_all(client, pid)
    manager.post(f"/api/projects/{pid}/approve", json={})
    assert sales.get(f"/api/projects/{pid}/export/estimate").status_code == 200
    assert {u["role"] for u in client.get("/api/users").json()} == {"設計担当", "設計課長", "営業担当"}


def test_request_return_and_approve_flow(client, manager, demo):
    pid = demo["id"]
    assert client.post(f"/api/projects/{pid}/approval/request", json={}).status_code == 409      # 要確認が残っている
    _resolve_all(client, pid)
    p = client.post(f"/api/projects/{pid}/approval/request", json={"comment": "ご確認ください"}).json()
    assert p["status"] == "承認待ち" and p["approval"]["by"] == "山田 太郎"
    summary = next(x for x in client.get("/api/projects").json() if x["id"] == pid)
    assert summary["approval"]["status"] == "requested"
    assert client.post(f"/api/projects/{pid}/approval/return", json={"comment": "x"}).status_code == 403
    assert manager.post(f"/api/projects/{pid}/approval/return", json={}).status_code == 422     # 理由は必須
    p = manager.post(f"/api/projects/{pid}/approval/return", json={"comment": "利益率を見直してください"}).json()
    assert p["status"] == "差戻し" and p["history"][0]["action"] == "差戻し"
    client.patch(f"/api/projects/{pid}/settings", json={"margin": 0.3})
    client.post(f"/api/projects/{pid}/approval/request", json={})
    p = manager.post(f"/api/projects/{pid}/approve", json={"comment": "OK"}).json()
    assert p["approval"]["requested_by"] == "山田 太郎" and p["approval"]["rev"] == 1
    assert p["revisions"][0]["approved_by"] == "佐藤 花子" and p["revisions"][0]["margin"] == 0.3


def test_edit_after_request_withdraws_it(client, demo):
    pid = demo["id"]
    _resolve_all(client, pid)
    client.post(f"/api/projects/{pid}/approval/request", json={})
    p = client.post(f"/api/projects/{pid}/components/no17", json={"qty": 2}).json()
    assert p["approval"]["status"] == "withdrawn" and p["status"] == "確認完了"
    assert p["history"][0]["action"] == "承認依頼の取下げ"


# ---------- 見積の版と比較 ----------

def test_revisions_and_compare(client, manager, demo):
    pid = demo["id"]
    _resolve_all(client, pid)
    manager.post(f"/api/projects/{pid}/approve", json={})
    client.post(f"/api/projects/{pid}/components/no17", json={"qty": 2})
    client.patch(f"/api/projects/{pid}/settings", json={"margin": 0.3})
    p = manager.post(f"/api/projects/{pid}/approve", json={}).json()
    assert [r["rev"] for r in p["revisions"]] == [1, 2] and p["approval"]["rev"] == 2
    d = client.get(f"/api/projects/{pid}/revisions/compare", params={"a": 1, "b": 2}).json()
    assert d["totals"]["sale_total"]["delta"] == p["revisions"][1]["sale_total"] - p["revisions"][0]["sale_total"]
    assert d["totals"]["margin"]["b"] == 0.3 and d["changes"] > 0
    assert any(c["kind"] == "changed" and c["b"]["qty"] == 2 for c in d["components"])
    same = client.get(f"/api/projects/{pid}/revisions/compare", params={"a": 2, "b": "current"}).json()
    assert same["changes"] == 0 and same["totals"]["sale_total"]["delta"] == 0
    assert client.get(f"/api/projects/{pid}/revisions/compare", params={"a": 9}).status_code == 404


# ---------- 同時編集の保護 ----------

def test_stale_edit_by_other_user_is_rejected(client, manager, demo):
    pid = demo["id"]
    rev = client.get(f"/api/projects/{pid}/rev").json()["rev"]
    client.post(f"/api/projects/{pid}/questions", json={"question": "山田の質疑"})
    after = client.get(f"/api/projects/{pid}/rev").json()
    assert after["rev"] == rev + 1 and after["modified_by"] == "山田 太郎"
    # 同じ担当者が古い画面のまま操作しても、自分の更新なので止めない
    assert client.post(f"/api/projects/{pid}/questions", json={"question": "続けて"}, headers={"X-Project-Rev": str(rev)}).status_code == 200
    # 佐藤さんの画面は山田さんの更新前（rev）のまま → 最新を読み込むよう 409
    r = manager.post(f"/api/projects/{pid}/questions", json={"question": "古い画面から"}, headers={"X-Project-Rev": str(rev)})
    assert r.status_code == 409 and r.json()["code"] == "stale" and "山田 太郎 さん" in r.json()["detail"]
    latest = client.get(f"/api/projects/{pid}/rev").json()["rev"]
    assert manager.post(f"/api/projects/{pid}/questions", json={"question": "最新から"}, headers={"X-Project-Rev": str(latest)}).status_code == 200
    assert client.get(f"/api/projects/{pid}/rev").json()["modified_by"] == "佐藤 花子"


def test_concurrent_edits_are_not_lost(client, demo):
    import threading
    pid = demo["id"]
    errors = []

    def add(i):
        r = client.post(f"/api/projects/{pid}/questions", json={"question": f"同時 {i}"})
        if r.status_code != 200:
            errors.append(r.status_code)
    ts = [threading.Thread(target=add, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    qs = client.get(f"/api/projects/{pid}").json()["custom_questions"]
    assert not errors and sorted(q["question"] for q in qs) == sorted(f"同時 {i}" for i in range(8))


# ---------- 精度レポート ----------

def test_accuracy_report_counts_human_corrections(client, demo):
    pid = demo["id"]
    base = client.get("/api/report/accuracy").json()
    assert base["projects"] == 1 and base["fields"]["corrected"] == 0 and base["fields"]["rate"] == 1.0
    client.post(f"/api/projects/{pid}/fields/customer", json={"action": "edit", "value": "湊川水道設備（株）"})
    client.post(f"/api/projects/{pid}/fields/subject", json={"action": "confirm"})
    client.post(f"/api/projects/{pid}/components/no11", json={"qty": 12})
    r = client.get("/api/report/accuracy").json()
    f = r["fields"]
    assert f["corrected"] == 1 and f["confirmed"] == 1 and 0 < f["rate"] < 1
    row = next(x for x in r["by_field"] if x["key"] == "customer")
    assert row["corrected"] == 1 and row["rate"] == 0
    assert r["by_field"][0]["key"] == "customer"                        # 修正が多い項目が先頭
    assert r["components"]["corrected"] == 1 and r["detect"]["conflicts"] >= 1 and r["detect"]["changes"] >= 1
    assert r["rows"][0]["corrected"] == 1 and {m["method"] for m in r["by_method"]} == {"both", "rule", "ai"}

