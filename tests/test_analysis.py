"""デモシナリオの業務ロジック（抽出・照合・収容判定・温度・見積・質疑）をルール抽出のみで検証する。"""
import pytest
from conftest import upload


def F(a):
    return {f["key"]: f for f in a["fields"]}


def C(a):
    return {c["key"]: c for c in a["components"]}


def test_fields_extraction_and_cross_document_checks(demo):
    a = demo["analysis"]
    f = F(a)
    assert f["customer"]["value"] == "湊川水道設備株式会社" and f["customer"]["status"] == "ok"
    assert f["outer_dims"]["parsed"] == {"w": 800, "h": 2000, "d": 700}              # 変更連絡（60cm→70cm）を mm で反映
    assert f["outer_dims"]["status"] == "changed" and f["outer_dims"]["change"]["before_matches"]
    assert f["main_power"]["status"] == "conflict"
    assert {g["value"] for g in f["main_power"]["candidates"]} == {"AC200V 3φ3W 60Hz", "AC200V 3φ3W 50Hz"}
    assert f["main_power"]["value"] == "AC200V 3φ3W 50Hz"                            # 受領日が新しい資料を仮採用
    assert f["protection"]["status"] == "missing"
    assert f["location"]["status"] == "inferred" and f["location"]["value"] == "屋内"
    assert f["reserve_space"]["parsed"] == {"pct": 15.0}
    assert f["exclusions"]["parsed"] == ["現地据付工事", "外部配線工事", "試運転調整"]
    for x in a["fields"]:                                                            # 値のある項目はすべて出典付き
        if x["value"] and x["status"] != "inferred":
            assert x["sources"] and x["sources"][0]["doc_name"]
    pdf_src = f["paint"]["sources"][0]
    assert pdf_src["page"] == 2 and len(pdf_src["bbox"]) == 4


def test_components_normalization_changes_and_additions(demo):
    c = C(demo["analysis"])
    assert c["no1"]["name"] == "配線用遮断器" and c["no1"]["aliased"]
    assert c["no2"]["model"] == "ELB-3P50"
    assert c["no7"]["model"] == "PLC-DI16" and any("表記揺れ" in n for n in c["no7"]["notes"])
    assert c["no3"]["model"] == "INV-11K" and c["no3"]["status"] == "changed" and c["no3"]["w"] == 220
    assert c["no11"]["qty"] == 10
    assert c["no18"]["origin"] == "added" and c["no18"]["name"] == "盤内照明"
    assert c["no20"]["price"] is None and c["no20"]["status"] == "added"
    assert c["no12"]["layout_mount"] == "terminal" and c["no17"]["layout_mount"] == "door"
    assert c["rec-fan"]["model"] == "FAN-250" and c["rec-fan"]["recommended"]


def test_fit_thermal_and_alternatives(demo):
    fit = demo["analysis"]["fit"]
    assert fit["verdict"] == "ng"
    checks = {x["id"]: x for x in fit["checks"]}
    assert checks["plate"]["status"] == "ng" and checks["plate"]["value"] == 1885
    assert checks["reserve"]["limit"] == 0.85 and "仕様書" in checks["reserve"]["rule"]
    assert checks["width_limit"]["status"] == "ok"
    assert fit["alternatives"][0]["id"] == "ST-9007" and fit["alternatives"][0]["w"] <= 900
    th = fit["thermal"]
    assert th["need_fan"] and th["heat_w"] == 965.0 and th["fan"]["model"] == "FAN-250"
    assert th["required_airflow"] <= th["fan"]["airflow"]
    plate = fit["plate"]
    inv = [i for i in plate["items"] if i["model"] == "INV-11K"]
    assert len(inv) == 2 and inv[0]["fw"] == 320 and inv[0]["fh"] == 550             # クリアランス込みの外形


def test_main_spec_only_fits(client):
    p = client.post("/api/projects", json={"name": "主仕様書のみ"}).json()
    upload(client, p["id"], "送水ポンプ制御盤_製作仕様書.pdf")
    a = client.post(f"/api/projects/{p['id']}/analyze").json()["analysis"]
    assert a["fit"]["verdict"] == "ok" and a["fit"]["plate"]["occupancy"] < 0.85
    assert F(a)["main_power"]["status"] == "ok"


def test_estimate_is_internally_consistent(demo):
    e = demo["analysis"]["estimate"]
    assert sum(l["cost"] for l in e["lines"]) == e["cost_total"]
    assert sum(c["amount"] for c in e["customer_lines"]) == e["sale_total"]
    assert e["sale_total"] % 10000 == 0 and e["tax"] == e["sale_total"] // 10
    assert e["grand_total"] == e["sale_total"] + e["tax"]
    assert {l["name"] for l in e["rfq"]} == {"サージ防護デバイス", "予備品 ヒューズ"}
    assert [l["name"] for l in e["expired"]] == ["制御用変圧器"]
    labor = {l["id"]: l for l in e["lines"] if l["group"] == "labor"}
    assert labor["test"]["qty"] == 16                                                # 立会検査の加算
    assert labor["docs"]["qty"] == 8                                                 # 図書2種 × 4h


def test_issues_questions_and_conditions(demo):
    a = demo["analysis"]
    blocking = {i["title"] for i in a["issues"] if i["blocking"]}
    assert blocking == {"主回路電源：資料間で値が異なります", "保護等級：記載が見つかりません", "収容判定：不可"}
    qs = a["questions"]
    assert [q["category"] for q in qs] == ["資料間の相違", "記載なし"]
    assert "60Hz" in qs[0]["question"] and "50Hz" in qs[0]["question"]
    assert any(c.startswith("※主回路電源は「AC200V 3φ3W 50Hz」") and "質疑No.1" in c for c in a["conditions"])
    assert any(r["label"] == "立会検査あり" for r in a["risks"])
    assert any(i["type"] == "document" for i in a["issues"])                          # スキャン図面は抽出対象外


def test_resolution_workflow_reaches_zero_blocking(client, demo):
    pid = demo["id"]
    r = client.post(f"/api/projects/{pid}/fields/main_power", json={"action": "choose", "choice": 0}).json()
    assert F(r["analysis"])["main_power"]["status"] == "resolved"
    assert F(r["analysis"])["main_power"]["value"] == "AC200V 3φ3W 60Hz"
    r = client.post(f"/api/projects/{pid}/fields/protection", json={"action": "ask"}).json()
    assert F(r["analysis"])["protection"]["status"] == "asked"
    assert any("保護等級" in q["question"] for q in r["analysis"]["questions"])
    r = client.patch(f"/api/projects/{pid}/settings", json={"enclosure_id": "ST-9007"}).json()
    a = r["analysis"]
    assert a["fit"]["verdict"] == "ok" and a["fit"]["spec_result"]["verdict"] == "ng"
    assert any(q["category"] == "仕様変更のご提案" and "W900" in q["question"] for q in a["questions"])
    assert any("W900×H2000×D700 に変更" in c for c in a["conditions"])
    assert a["stats"]["blocking"] == 0 and r["status"] == "確認完了"


def test_overrides_survive_reanalysis(client, demo):
    pid = demo["id"]
    client.post(f"/api/projects/{pid}/fields/protection", json={"action": "edit", "value": "IP4X", "reason": "電話確認"})
    client.post(f"/api/projects/{pid}/components/no11", json={"qty": 12})
    client.post(f"/api/projects/{pid}/components/no20", json={"deleted": True})
    a = client.post(f"/api/projects/{pid}/analyze").json()["analysis"]
    assert F(a)["protection"]["value"] == "IP4X" and F(a)["protection"]["status"] == "edited"
    assert C(a)["no11"]["qty"] == 12 and any("数量を修正" in n for n in C(a)["no11"]["notes"])
    assert C(a)["no20"]["status"] == "deleted"
    assert not any(l["name"] == "サージ防護デバイス" for l in a["estimate"]["lines"])


@pytest.mark.parametrize("model,expect", [("RY-4C", "照合"), ("ZZ-999", "マスタ未登録")])
def test_manual_component_with_and_without_master(client, demo, model, expect):
    r = client.post(f"/api/projects/{demo['id']}/components", json={"name": "追加機器", "model": model, "qty": 2, "mount": "plate"})
    a = r.json()["analysis"]
    comp = [c for c in a["components"] if c["origin"] == "manual"][0]
    if expect == "照合":
        assert comp["in_master"] and comp["w"] == 30
    else:
        assert comp["status"] == "no_master" and a["fit"]["verdict"] == "insufficient"   # 寸法不明 → 情報不足（落ちない）
