"""類似案件検索（C12）・マスタ変更の影響確認と版（C13）・回帰チェック（G3）・市況係数（D8）・
修正履歴からの改善候補（F7）・判定一致率（G4）・効果測定（F8）・他システム連携 CSV（F9）。"""
import csv
import io

from app import learning, report


def _resolve_all(client, pid):
    client.post(f"/api/projects/{pid}/fields/main_power", json={"action": "choose", "choice": 0})
    client.post(f"/api/projects/{pid}/fields/protection", json={"action": "edit", "value": "IP4X"})
    return client.patch(f"/api/projects/{pid}/settings", json={"enclosure_id": "ST-9007"}).json()


def _rules(client):
    return client.get("/api/master/rules").json()


# ---------- 類似過去案件（C12） ----------

def test_similar_cases_rank_like_for_like_first(client, demo):
    r = client.get(f"/api/projects/{demo['id']}/similar").json()
    top = r["items"][0]
    assert top["quote_no"] == "Q2025-0188" and top["score"] >= 90          # 同じ顧客・用途・インバータ 2台の送水ポンプ盤
    assert any("用途" in m for m in top["match"]) and any("インバータ 22kW" in m for m in top["match"])
    assert any("W900" in d for d in top["diff"])                            # 過去案件は W900 に変更して受注
    assert [x["score"] for x in r["items"]] == sorted((x["score"] for x in r["items"]), reverse=True)
    assert {b["key"] for b in top["breakdown"]} >= {"purpose", "components", "drive", "size"}
    p = r["price"]
    assert p["n"] == 3 and p["min"] <= p["avg"] <= p["max"] and p["current"] == demo["analysis"]["estimate"]["sale_total"]
    assert r["searched"] == 12 and r["sizes"]


def test_unrelated_panel_scores_low(client, demo):
    items = {x["quote_no"]: x for x in client.get(f"/api/projects/{demo['id']}/similar?limit=12").json()["items"]}
    assert len(items) == 12
    low = items["Q2024-0315"]                                              # 壁掛形の薬注盤（PLC・インバータなし）
    assert low["score"] < 50 and any("盤形式：壁掛形" in d for d in low["diff"])


def test_approved_quotes_become_past_cases(client, manager, demo):
    _resolve_all(client, demo["id"])
    manager.post(f"/api/projects/{demo['id']}/approve", json={})
    other = client.post("/api/projects/demo").json()
    r = client.get(f"/api/projects/{other['id']}/similar").json()
    mine = next(x for x in r["items"] if x["source"] == "system")
    assert mine["project_id"] == demo["id"] and mine["result"] == "承認 第1版" and mine["score"] >= 90
    assert "W900" in mine["enclosure"]


def test_similar_requires_analysis(client):
    pid = client.post("/api/projects", json={"name": "空の案件"}).json()["id"]
    assert client.get(f"/api/projects/{pid}/similar").status_code == 409


# ---------- 市況係数（D8） ----------

def test_market_factors_apply_to_enclosure_and_imported_parts(client, manager, demo):
    base = demo["analysis"]["estimate"]
    assert base["market"]["delta"] == 0 and not any("market" in l["flags"] for l in base["lines"])
    rules = _rules(manager)
    rules["market"].update(steel_index=110, usd_jpy=165)
    assert manager.put("/api/master/rules?recompute=true", json=rules).status_code == 200
    e = client.get(f"/api/projects/{demo['id']}").json()["analysis"]["estimate"]
    lines = {l["id"]: l for l in e["lines"]}
    enc = lines["enc"]
    assert "market" in enc["flags"] and enc["unit_cost"] == round(enc["base_unit_cost"] * (1 + 0.10 * 0.45))
    inv = lines["eq-no3"]                                                  # インバータは輸入品（為替 150→165・連動 60%）
    assert inv["unit_cost"] == round(inv["base_unit_cost"] * 1.06) and "為替" in inv["note"]
    assert "market" not in lines["eq-no1"]["flags"]                        # 国内品は変えない
    assert e["market"]["steel"] == 1.045 and e["market"]["fx"] == 1.06 and e["market"]["lines"] == 3
    assert e["market"]["delta"] > 0 and e["sale_total"] > base["sale_total"]
    # 担当者が単価を直した行は市況係数をかけない
    r = client.post(f"/api/projects/{demo['id']}/estimate/lines/enc", json={"unit_cost": 200000}).json()
    enc = next(l for l in r["analysis"]["estimate"]["lines"] if l["id"] == "enc")
    assert enc["unit_cost"] == 200000 and "market" not in enc["flags"]


def test_market_rules_are_validated(manager):
    rules = _rules(manager)
    rules["market"]["steel_share"] = 1.5
    assert manager.put("/api/master/rules", json=rules).status_code == 422
    rules["market"]["steel_share"] = 0.4
    rules["market"]["usd_jpy_base"] = 0
    assert manager.put("/api/master/rules", json=rules).status_code == 422


# ---------- 影響確認・版・回帰チェック（C13・G3） ----------

def test_impact_preview_does_not_save(client, manager, demo):
    pid = demo["id"]
    rev = client.get(f"/api/projects/{pid}/rev").json()["rev"]
    rules = _rules(manager)
    rules["market"]["steel_index"] = 120
    r = manager.post("/api/master/rules/impact", json=rules).json()
    assert r["total"] == 1 and r["changed"] == 1 and r["sale_delta"] > 0 and "鋼材指数 100→120" in r["summary"]
    row = r["rows"][0]
    assert row["id"] == pid and row["changes"][0]["kind"] == "sale_total" and not row["locked"]
    assert client.get(f"/api/projects/{pid}/rev").json()["rev"] == rev   # 案件は保存しない
    assert _rules(manager)["market"]["steel_index"] == 100              # マスタも保存しない
    assert client.post("/api/master/rules/impact", json=rules).status_code == 403   # 設計担当はマスタ権限なし


def test_impact_detects_verdict_change_and_protects_approved(client, manager, demo):
    _resolve_all(client, demo["id"])
    manager.post(f"/api/projects/{demo['id']}/approve", json={})
    open_p = client.post("/api/projects/demo").json()
    _resolve_all(client, open_p["id"])
    rules = _rules(manager)
    rules["layout"]["row_duct_h"] = 200                                  # 段間ダクトを太くすると W900 でも収まらない
    r = manager.post("/api/master/rules/impact", json=rules).json()
    assert r["changed"] == 2 and r["verdict_changed"] == 2 and r["locked_changed"] == 1
    approved = next(x for x in r["rows"] if x["id"] == demo["id"])
    assert approved["locked"] and approved["approval"] == "approved"
    assert any(c["kind"] == "verdict" and c["a"] == "可" for c in approved["changes"])

    res = manager.put("/api/master/rules?recompute=true", json=rules).json()
    assert [x["id"] for x in res["recomputed"]] == [open_p["id"]]       # 承認済みの見積は再計算しない
    p = client.get(f"/api/projects/{open_p['id']}").json()
    assert p["history"][0]["action"] == "マスタ変更による再計算" and "収容判定 可→不可" in p["history"][0]["detail"]
    done = client.get(f"/api/projects/{demo['id']}").json()
    assert done["approval"]["status"] == "approved" and done["analysis"]["fit"]["verdict"] == "ok"

    # 回帰チェック：承認済み案件は保存済みの結果と現在のルールでの結果が異なる
    g = client.get("/api/report/regression").json()
    assert g["changed"] == 1 and g["rows"][0]["id"] == demo["id"] and g["rows"][0]["locked"]


def test_master_versions_and_restore(client, manager, demo):
    rules = _rules(manager)
    rules["cost"]["transport"] = 99000
    assert manager.put("/api/master/rules", json=rules).json()["version"] == 2
    rules["cost"]["transport"] = 120000
    assert manager.put("/api/master/rules", json=rules).json()["version"] == 3
    vs = client.get("/api/master/rules/versions").json()
    assert [v["version"] for v in vs] == [3, 2, 1] and vs[0]["by"] == "佐藤 花子"
    assert "運搬費 99,000→120,000" in vs[0]["summary"] and vs[2]["summary"] == "初期データ"
    # 回帰チェック：保存しただけ（再計算なし）なので、保存済みの解析とは金額が違う
    g = client.get("/api/report/regression").json()
    assert g["changed"] == 1 and g["rows"][0]["changes"][0]["kind"] == "sale_total"
    assert client.post("/api/master/rules/versions/1/restore").status_code == 403
    r = manager.post("/api/master/rules/versions/1/restore?recompute=true").json()
    assert r["version"] == 4 and _rules(manager)["cost"]["transport"] == 85000
    assert client.get("/api/master/rules/versions").json()[0]["summary"] == "第1版に戻す"
    assert client.get("/api/report/regression").json()["changed"] == 0
    assert manager.post("/api/master/rules/versions/99/restore").status_code == 404


def test_parts_version_summary(manager):
    parts = manager.get("/api/master/parts").json()
    parts[0]["price"] = 19000
    parts.append({**parts[1], "model": "ELB-3P75"})
    manager.put("/api/master/parts", json=parts)
    s = manager.get("/api/master/parts/versions").json()[0]["summary"]
    assert "単価変更 1件（MCB-3P100）" in s and "追加 1件（ELB-3P75）" in s


def test_past_projects_master_is_read_only(client, manager):
    assert len(client.get("/api/master/past_projects").json()) == 12
    assert manager.put("/api/master/past_projects", json=[]).status_code == 404


# ---------- 修正履歴からの改善候補（F7） ----------

def test_model_correction_becomes_alias_candidate(client, manager, demo):
    pid = demo["id"]
    p = client.post(f"/api/projects/{pid}/components", json={"name": "インバータ", "model": "INV11KW", "qty": 1}).json()
    key = next(c["key"] for c in p["analysis"]["components"] if c["origin"] == "manual")
    client.post(f"/api/projects/{pid}/components/{key}", json={"model": "INV-11K"})
    items = client.get("/api/learning").json()["items"]
    c = next(x for x in items if x["kind"] == "part_alias")
    assert c["target"] == "INV-11K" and c["value"] == "INV11KW" and c["applicable"]
    assert c["projects"][0]["id"] == pid and "INV11KW → INV-11K" in c["examples"][0]
    assert client.post(f"/api/learning/{c['id']}/apply").status_code == 403          # 反映はマスタ権限者だけ
    r = manager.post(f"/api/learning/{c['id']}/apply").json()
    assert r["master"] == "parts" and r["version"] == 2
    inv = next(x for x in manager.get("/api/master/parts").json() if x["model"] == "INV-11K")
    assert "INV11KW" in inv["aliases"]
    assert "改善候補を反映" in client.get("/api/master/parts/versions").json()[0]["summary"]
    r = client.get("/api/learning").json()
    assert c["id"] not in {x["id"] for x in r["items"]} and r["applied"] == 1
    assert r["decisions"][0] == {**r["decisions"][0], "id": c["id"], "action": "applied", "by": "佐藤 花子"}
    assert manager.post(f"/api/learning/{c['id']}/apply").status_code == 404           # 判断済み
    # 反映後は、別の案件で同じ表記を入力してもマスタと照合できる
    other = client.post("/api/projects/demo").json()
    p = client.post(f"/api/projects/{other['id']}/components", json={"name": "インバータ", "model": "INV11KW", "qty": 1}).json()
    added = next(c for c in p["analysis"]["components"] if c["origin"] == "manual")
    assert added["in_master"] and added["model"] == "INV-11K"


def test_unregistered_part_candidate_can_only_be_dismissed(client, manager, demo):
    client.post(f"/api/projects/{demo['id']}/components", json={"name": "ノイズフィルタ", "model": "NF-3P20", "qty": 1})
    c = next(x for x in client.get("/api/learning").json()["items"] if x["kind"] == "unregistered")
    assert c["target"] == "NF-3P20" and not c["applicable"]
    assert manager.post(f"/api/learning/{c['id']}/apply").status_code == 409
    assert manager.post(f"/api/learning/{c['id']}/dismiss").status_code == 200
    r = client.get("/api/learning").json()
    assert r["open"] == 0 and r["decisions"][0]["action"] == "dismissed" and r["decisions"][0]["id"] == c["id"]
    assert manager.post("/api/learning/000000000000/apply").status_code == 404


def test_ai_only_value_confirmed_by_human_suggests_field_alias():
    dic = {"fields": [{"key": "protection", "label": "保護等級", "aliases": ["保護等級", "保護構造"]}], "component_names": {}}
    f = {"key": "protection", "label": "保護等級", "status": "confirmed", "methods": ["ai"], "value": "IP4X",
         "sources": [{"doc_name": "回答.pdf", "text": "盤の防塵防水性能：IP4X 相当とします"}]}
    p = {"id": "a" * 12, "quote_no": "Q1", "name": "x", "analysis": {"fields": [f], "components": []}}
    r = learning.candidates([p], dic, [], {})
    c = r["items"][0]
    assert c["kind"] == "field_alias" and c["value"] == "盤の防塵防水性能" and c["target"] == "protection"
    learning.apply(c, dic, [])
    assert "盤の防塵防水性能" in dic["fields"][0]["aliases"]
    assert learning.candidates([p], dic, [], {})["items"] == []          # 反映後は候補に出ない
    f["sources"][0]["text"] = "保護構造：IP4X"                              # 既に辞書にある項目名は候補にしない
    assert learning.candidates([p], dic, [], {})["items"] == []


def test_label_from_source():
    assert learning._label_from_source("保護構造 | IP4X") == "保護構造"
    assert learning._label_from_source("・周囲温度：0〜40℃") == "周囲温度"
    assert learning._label_from_source("IP4X 相当とします") is None
    assert learning._label_from_source("2026年10月31日：回答") is None


def test_repeated_edits_are_reported_for_rule_review(client):
    for _ in range(2):
        pid = client.post("/api/projects/demo").json()["id"]
        client.post(f"/api/projects/{pid}/fields/delivery", json={"action": "edit", "value": "受注後6ヶ月"})
    c = next(x for x in client.get("/api/learning").json()["items"] if x["kind"] == "frequent_edit")
    assert c["target"] == "delivery" and c["count"] == 2 and not c["applicable"] and len(c["examples"]) == 2


# ---------- 判定一致率（G4） ----------

def test_fit_review_and_agreement_rate(client, sales, demo):
    pid = demo["id"]
    assert client.post(f"/api/projects/{pid}/fit/review", json={"decision": "disagree", "final_verdict": "ok"}).status_code == 422  # 理由が必要
    assert client.post(f"/api/projects/{pid}/fit/review", json={"decision": "maybe"}).status_code == 422
    assert sales.post(f"/api/projects/{pid}/fit/review", json={"decision": "agree"}).status_code == 403
    r = client.post(f"/api/projects/{pid}/fit/review", json={
        "decision": "disagree", "final_verdict": "ok", "final_enclosure": "自立形 W800×H2000×D700", "reason": "ダクト幅を詰めれば収まる"}).json()
    fr = r["fit_review"]
    assert fr["system"]["verdict"] == "ng" and fr["final_verdict"] == "ok" and fr["by"] == "山田 太郎"
    assert r["history"][0]["action"] == "収容判定の最終判断" and "システム「不可」→ 設計者「可」" in r["history"][0]["detail"]
    assert r["analysis"]["estimate"]["sale_total"] == demo["analysis"]["estimate"]["sale_total"]   # 見積は変えない

    other = client.post("/api/projects/demo").json()
    _resolve_all(client, other["id"])
    client.post(f"/api/projects/{other['id']}/fit/review", json={"decision": "agree"})
    g = client.get("/api/report/fit").json()
    assert g["recorded"] == 2 and g["agree"] == 1 and g["rate"] == 0.5 and g["verdict_diff"] == 1
    agreed = next(x for x in g["rows"] if x["decision"] == "agree")
    assert agreed["final_verdict"] == agreed["system_verdict"] == "ok"
    assert client.delete(f"/api/projects/{pid}/fit/review").json().get("fit_review") is None
    assert client.get("/api/report/fit").json()["recorded"] == 1


# ---------- 効果測定（F8） ----------

def test_active_minutes_skip_idle_gaps():
    ev = ["2026-10-01T09:00:00", "2026-10-01T09:10:00", "2026-10-01T09:15:00", "2026-10-01T13:00:00", "2026-10-01T13:05:00"]
    assert report._active_minutes(ev, 20) == 22.0          # 10 + 5 + 5 分 + 最初の 2 分（4 時間の空きは数えない）
    assert report._active_minutes([], 20) == 0


def test_effect_report_counts_completed_quotes(client, manager, demo):
    _resolve_all(client, demo["id"])
    client.post(f"/api/projects/{demo['id']}/approval/request", json={})
    manager.post(f"/api/projects/{demo['id']}/approve", json={})
    client.post("/api/projects/demo")
    e = client.get("/api/report/effect").json()
    assert e["projects"] == 2 and e["completed"] == 1 and e["baseline_hours"] == 6.0
    row = next(r for r in e["rows"] if r["id"] == demo["id"])
    assert row["completed"] and row["events"] >= 4 and row["active_min"] >= 2 and row["saved_hours"] > 5
    assert row["corrected"] == 0 and row["fields"] > 20  # 記載なしの補完・矛盾の解決は「修正」に数えない
    assert 0 < e["reduction_rate"] <= 1 and e["avg_analysis_sec"] >= 0
    rules = _rules(manager)
    rules["effect"]["baseline_hours"] = 3
    manager.put("/api/master/rules", json=rules)
    assert client.get("/api/report/effect").json()["baseline_hours"] == 3


# ---------- 他システム連携 CSV（F9） ----------

def _csv(resp):
    assert resp.status_code == 200 and resp.content.startswith(b"\xef\xbb\xbf")   # Excel で開ける BOM 付き UTF-8
    return list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))


def test_sales_and_purchase_csv(client, manager, sales, demo):
    pid = demo["id"]
    assert client.get(f"/api/projects/{pid}/export/sales-csv").status_code == 409     # 未解決の要確認あり
    p = _resolve_all(client, pid)
    est = p["analysis"]["estimate"]
    assert sales.get(f"/api/projects/{pid}/export/sales-csv").status_code == 403      # 営業は承認前の出力不可
    rows = _csv(client.get(f"/api/projects/{pid}/export/sales-csv"))
    assert rows[0][:5] == ["見積番号", "件名", "顧客", "承認状態", "行番号"] and rows[1][3] == "未承認"
    assert int(rows[-1][9]) == est["grand_total"] and rows[-1][5] == "合計（税込）"
    assert sum(int(r[9]) for r in rows[1:] if r[10] == "明細") == est["sale_total"]

    manager.post(f"/api/projects/{pid}/approve", json={})
    assert _csv(sales.get(f"/api/projects/{pid}/export/sales-csv"))[1][3] == "承認済"
    rows = _csv(sales.get(f"/api/projects/{pid}/export/purchase-csv"))
    assert rows[0][:5] == ["見積番号", "区分", "メーカー", "型式", "品名"]
    inv = next(r for r in rows if r[3] == "INV-11K")
    assert inv[1] == "機器" and inv[2] == "B製作所" and inv[5] == "2"
    assert rows[1][1] == "筐体" and {r[1] for r in rows[1:]} <= {"筐体", "機器", "予備品"}
    h = client.get(f"/api/projects/{pid}").json()["history"]
    assert h[0]["action"] == "連携CSV出力" and "手配リスト" in h[0]["detail"]


def test_csv_cells_are_not_formulas(client, manager, demo):
    pid = demo["id"]
    _resolve_all(client, pid)
    client.post(f"/api/projects/{pid}/fields/subject", json={"action": "edit", "value": "=HYPERLINK(\"http://x\")"})
    rows = _csv(client.get(f"/api/projects/{pid}/export/sales-csv"))
    assert rows[1][1] == "'=HYPERLINK(\"http://x\")"
