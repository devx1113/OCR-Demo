"""AI 連携のうち、ネットワークを使わずに検証できる部分（根拠検証・キャッシュ・ルール抽出との突き合わせ）。"""
import pytest
from conftest import REPLY, upload

from app import ai, storage
from app.analysis import analyze

INDEX = {
    "p1l5": {"text": "まず盤の保護構造についてですが、本盤は屋内の電気室に設置いたしますので、保護等級はIP4X相当で問題ございません。",
             "page": 1, "bbox": [0, 0, 1, 1], "ids": ["p1l5"]},
    "p2t0r8": {"text": "主回路電源 | AC200V 3φ3W 60Hz", "page": 2, "bbox": [0, 0, 1, 1], "ids": ["c1", "c2"]},
}


@pytest.mark.parametrize("value,eid,quote,expected", [
    ("IP4X相当", "p1l5", "保護等級はIP4X相当で問題ございません。", ("p1l5", True)),
    ("IP4X相当", "p1l5", "「保護等級はIP4X相当で問題ございません」", ("p1l5", True)),      # 括弧付きの引用
    ("IP4X相当", "[p1l5]", "[p1l5] 保護等級はIP4X相当", ("p1l5", True)),                 # ID 付きの引用
    ("AC200V 3φ3W 60Hz", "p1l5", "AC200V 3φ3W 60Hz", ("p2t0r8", True)),                  # ID の取り違えを補正
    ("AC200V 3φ3W 50Hz", "p2t0r8", "AC200V 3φ3W 50Hz", ("p2t0r8", False)),               # 数値が原文と違う
    ("IP54", "p1l5", "保護等級はIP54とする", ("p1l5", False)),                            # 原文にない引用（作り話）
    ("IP4X相当", "zzz", "存在しない文", (None, False)),
])
def test_verify(value, eid, quote, expected):
    assert ai.verify(value, eid, quote, INDEX) == expected


def test_doc_index_rows():
    parsed = {"blocks": [
        {"id": "p1l0", "type": "para", "page": 1, "bbox": [1, 2, 3, 4], "text": "タイトル"},
        {"id": "p1t0", "type": "table", "page": 1, "bbox": None, "rows": [
            [{"id": "a", "text": "数量", "bbox": [0, 0, 10, 10]}, {"id": "b", "text": "1面", "bbox": [10, 0, 20, 12]}]]},
    ]}
    text, index = ai.doc_index(parsed, prefix="D1:")
    assert "[D1:p1l0] タイトル" in text and "[D1:p1t0r0] 数量 | 1面" in text
    assert index["D1:p1t0r0"]["bbox"] == [0, 0, 20, 12] and index["D1:p1t0r0"]["ids"] == ["a", "b"]


def _reply_project(client):
    p = client.post("/api/projects", json={"name": "AI"}).json()
    for name in ("送水ポンプ制御盤_製作仕様書.pdf", "仕様補足・変更連絡書_No1.docx", REPLY):
        p = upload(client, p["id"], name).json()
    return p


def _extraction_for(user, schema):
    """資料ごとにそれらしい AI 応答を返す（作り話・取り違えも混ぜる）。"""
    if "顧客回答メール" in user:
        return {"fields": [
            {"key": "protection", "value": "IP4X相当", "evidence_id": "p1l5", "evidence_quote": "保護等級はIP4X相当で問題ございません"},
            {"key": "main_power", "value": "AC200V 3φ3W 60Hz", "evidence_id": "p1l7", "evidence_quote": "AC200V 3φ3W 60Hzが正となります"},
            {"key": "customer", "value": "株式会社サンプル制御システム", "evidence_id": "p1t0r1", "evidence_quote": "株式会社サンプル制御システム 営業部 山田様"},
            {"key": "witness", "value": "1回", "evidence_id": "p1l9", "evidence_quote": "立会検査は1回の予定"},
            {"key": "location", "value": "屋内の電気室", "evidence_id": "p1l5", "evidence_quote": "屋内の電気室に設置いたします"},
            {"key": "paint", "value": "マンセル N7", "evidence_id": "p1l5", "evidence_quote": "塗装色はマンセルN7とする"},  # 作り話
        ], "components": [], "corrections": [
            {"summary": "変更連絡書の50Hzは誤記", "evidence_id": "p1l7", "evidence_quote": "記載の50Hzは弊社の誤記でございました"}]}
    if "製作仕様書" in user:
        return {"fields": [
            {"key": "outer_dims", "value": "W800 × H2000 × D600 mm", "evidence_id": "p2t0r5", "evidence_quote": "W800 × H2000 × D600 mm"},
            {"key": "location", "value": "第二浄水場", "evidence_id": "p3l6", "evidence_quote": "第二浄水場 車上渡し"},   # 型に合わない
        ], "components": [
            {"name": "インバータ", "model": "INV-7R5", "spec": "7.5kW", "qty": 2, "mount": "取付板", "evidence_id": "p2t1r3", "evidence_quote": "INV-7R5"},
            {"name": "表示灯", "model": "PL-22", "spec": "", "qty": 6, "mount": "扉面", "evidence_id": "p2t1r13", "evidence_quote": "PL-22"},
        ], "corrections": []}
    return {"fields": [], "components": [], "corrections": []}


def test_extract_document_verifies_and_caches(client, fake_ai):
    p = _reply_project(client)
    fake_ai.responses["extraction"] = _extraction_for
    project = storage.load_project(p["id"])
    reply = next(d for d in project["documents"] if d["filename"] == REPLY)
    dic = storage.load_master("dictionary")
    r = ai.extract_document(project, reply, storage.load_parsed(p["id"], reply["id"]), dic)
    assert r["cached"] is False
    assert {f["key"] for f in r["fields"]} == {"protection", "main_power", "customer", "witness", "location"}
    assert r["stats"]["rejected"] == 1 and r["rejected"][0]["key"] == "paint"   # 作り話は除外
    assert r["corrections"][0]["source"]["page"] == 1
    n = len(fake_ai.calls)
    again = ai.extract_document(project, reply, storage.load_parsed(p["id"], reply["id"]), dic)
    assert again["cached"] is True and len(fake_ai.calls) == n                 # 2回目は API を呼ばない


def test_recheck_pass_only_for_missing_named_fields(client, fake_ai):
    p = _reply_project(client)
    fake_ai.responses["extraction"] = {"fields": [], "components": [], "corrections": []}
    fake_ai.responses["recheck"] = lambda user, schema: {"fields": [
        {"key": "protection", "value": "IP4X相当", "evidence_id": "p1l5", "evidence_quote": "保護等級はIP4X相当"}],
        "components": [], "corrections": []}
    project = storage.load_project(p["id"])
    reply = next(d for d in project["documents"] if d["filename"] == REPLY)
    r = ai.extract_document(project, reply, storage.load_parsed(p["id"], reply["id"]), storage.load_master("dictionary"))
    recheck = [c for c in fake_ai.calls if c["name"] == "recheck"][0]
    assert "protection" in recheck["schema"]["properties"]["fields"]["items"]["properties"]["key"]["enum"]
    assert "protection" in r["usage"]["recheck"]
    assert [f["key"] for f in r["fields"]] == ["protection"]


def test_analysis_combines_rules_and_ai(client, fake_ai):
    p = _reply_project(client)
    fake_ai.responses["extraction"] = _extraction_for
    for d in p["documents"]:
        assert client.post(f"/api/projects/{p['id']}/documents/{d['id']}/ai").status_code == 200
    a = client.post(f"/api/projects/{p['id']}/analyze").json()["analysis"]
    f = {x["key"]: x for x in a["fields"]}

    assert f["protection"]["status"] == "review" and f["protection"]["methods"] == ["ai"]     # 文章からだけ読めた値
    assert f["protection"]["value"] == "IP4X相当" and "AI" in f["protection"]["note"]
    assert "rule+ai" in f["outer_dims"]["methods"]                                           # ルールと AI が一致
    assert f["customer"]["status"] == "ok" and f["customer"]["value"] == "湊川水道設備株式会社"  # 宛先の誤読は採用しない
    assert f["witness"]["status"] == "ok"                                                    # 「1回」は言い換えとして裏付け扱い
    assert f["location"]["value"] == "屋内" and f["location"]["methods"] == ["ai"]            # 地名は捨て、屋内を採用
    mp = f["main_power"]
    assert mp["status"] == "conflict" and mp["value"] == "AC200V 3φ3W 60Hz"                   # 最新資料（回答メール）を仮採用
    assert len(mp["candidates"]) == 2
    assert a["ai_notes"][0]["summary"].startswith("変更連絡書の50Hz")
    comps = {c["key"]: c for c in a["components"]}
    assert comps["no3"]["model"] == "INV-11K" and comps["no3"].get("ai_verified")            # 変更前の型式でも突き合わせる
    assert not [c for c in a["components"] if c["origin"] == "ai"]
    assert a["ai"]["used"] and a["ai"]["ai_only"] >= 2


def test_ai_corrections_on_change_rows_are_not_duplicated(client, fake_ai):
    p = _reply_project(client)

    def resp(user, schema):
        if "仕様補足" in user:   # 変更一覧の行を「訂正」として返してきた場合
            return {"fields": [], "components": [], "corrections": [
                {"summary": "インバータを11kWに変更", "evidence_id": "?", "evidence_quote": "INV-11K（11kW）"}]}
        return _extraction_for(user, schema)
    fake_ai.responses["extraction"] = resp
    for d in p["documents"]:
        client.post(f"/api/projects/{p['id']}/documents/{d['id']}/ai")
    a = client.post(f"/api/projects/{p['id']}/analyze").json()["analysis"]
    assert [n["summary"] for n in a["ai_notes"]] == ["変更連絡書の50Hzは誤記"]


def test_ai_component_only_found_by_ai_is_added_for_review(client, fake_ai):
    p = _reply_project(client)

    def resp(user, schema):
        if "顧客回答メール" in user:
            return {"fields": [], "corrections": [], "components": [
                {"name": "サービスコンセント", "model": "OUT-2P", "spec": "", "qty": 1, "mount": "取付板",
                 "evidence_id": "p1l5", "evidence_quote": "屋内の電気室に設置"},
                {"name": "警報ブザー", "model": "BZ-24", "spec": "DC24V", "qty": 1, "mount": "扉面",
                 "evidence_id": "p1l9", "evidence_quote": "立会検査は1回の予定"},
                {"name": "ドアスイッチ", "model": "", "spec": "", "qty": 1, "mount": "扉面",
                 "evidence_id": "p1l5", "evidence_quote": "屋内の電気室に設置いたします"}]}
        return {"fields": [], "components": [], "corrections": []}
    fake_ai.responses["extraction"] = resp
    for d in p["documents"]:
        client.post(f"/api/projects/{p['id']}/documents/{d['id']}/ai")
    a = client.post(f"/api/projects/{p['id']}/analyze").json()["analysis"]
    added = [c for c in a["components"] if c["origin"] == "ai"]
    # BZ-24・OUT-2P は根拠の行に型式の数値がないため不採用（既存機器の裏付けにも使わない）。ドアスイッチだけが追加候補
    assert [c["name"] for c in added] == ["ドアスイッチ"]
    assert added[0]["status"] == "ai" and added[0]["sources"][0]["ids"] == ["p1l5"]
    assert not {c["key"]: c for c in a["components"]}["no19"].get("ai_verified")
    assert any(i["type"] == "ai_component" and not i["blocking"] for i in a["issues"])
    # 未確定の候補は収容判定・見積に含めない（寸法不明でも「情報不足」にしない）
    assert a["fit"]["verdict"] == "ng" and not any(l["name"] == "ドアスイッチ" for l in a["estimate"]["lines"])
    key = added[0]["key"]
    a = client.post(f"/api/projects/{p['id']}/components/{key}", json={"confirmed": True}).json()["analysis"]
    comp = {c["key"]: c for c in a["components"]}[key]
    assert comp["status"] == "confirmed" and not comp.get("candidate")
    assert a["fit"]["verdict"] == "insufficient"                                   # 確定後は寸法不明として判定に反映
    assert any(l["name"] == "ドアスイッチ" and "rfq" in l["flags"] for l in a["estimate"]["lines"])


def test_ai_fan_mention_merges_into_thermal_recommendation(client, fake_ai):
    p = _reply_project(client)

    def resp(user, schema):
        if "製作仕様書" in user:
            return {"fields": [], "corrections": [], "components": [
                {"name": "換気ファン", "model": "", "spec": "", "qty": None, "mount": "不明",
                 "evidence_id": "?", "evidence_quote": "必要に応じて換気ファンを設けること"}]}
        return {"fields": [], "components": [], "corrections": []}
    fake_ai.responses["extraction"] = resp
    for d in p["documents"]:
        client.post(f"/api/projects/{p['id']}/documents/{d['id']}/ai")
    a = client.post(f"/api/projects/{p['id']}/analyze").json()["analysis"]
    assert not [c for c in a["components"] if c["origin"] == "ai"]
    fan = {c["key"]: c for c in a["components"]}["rec-fan"]
    assert fan["ai_verified"] and any("AI も仕様書の記載から" in n for n in fan["notes"])


def test_ai_toggle_per_project(client, fake_ai):
    p = _reply_project(client)
    fake_ai.responses["extraction"] = _extraction_for
    for d in p["documents"]:
        client.post(f"/api/projects/{p['id']}/documents/{d['id']}/ai")
    client.post(f"/api/projects/{p['id']}/analyze")
    off = client.patch(f"/api/projects/{p['id']}/settings", json={"ai": False}).json()["analysis"]
    assert {x["key"]: x for x in off["fields"]}["protection"]["status"] == "missing"
    assert off["ai"]["used"] is False


def test_ask_strips_ids_and_verifies_citations(client, fake_ai):
    p = _reply_project(client)
    client.post(f"/api/projects/{p['id']}/analyze")
    fake_ai.responses["answer"] = {"answer": "60Hzが正です。[D3:p1l7] 主仕様書にも記載があります［D1:p2t0r8］。", "citations": [
        {"evidence_id": "D3:p1l7", "quote": "AC200V 3φ3W 60Hzが正となります"},
        {"evidence_id": "D1:p2t0r8", "quote": "AC200V 3φ3W 60Hz"},
        {"evidence_id": "D1:p2t0r8", "quote": "でっち上げの引用"}]}
    r = client.post(f"/api/projects/{p['id']}/ai/ask", json={"question": "周波数は？"})
    assert r.status_code == 200
    msg = r.json()["chat"][-1]
    assert msg["content"] == "60Hzが正です。 主仕様書にも記載があります。"
    assert [c["doc_name"] for c in msg["citations"]] == [REPLY, "送水ポンプ制御盤_製作仕様書.pdf"]
    assert msg["unverified"] == 1
    assert "[D1:p2t0r8] 主回路電源 | AC200V 3φ3W 60Hz" in fake_ai.calls[-1]["user"]
