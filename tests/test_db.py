"""PostgreSQL（Prisma）保存時の検査。DATABASE_URL を指定して実行したときだけ動く。

    DATABASE_URL=postgresql://panel:panel@127.0.0.1:5434/panel_test pytest tests/test_db.py
"""
import pytest

from app import storage

pytestmark = pytest.mark.skipif(storage.BACKEND != "db", reason="DATABASE_URL 未指定（JSON ファイル保存で実行中）")


def test_optimistic_lock_rejects_save_from_stale_copy(client, demo):
    pid = demo["id"]
    a = storage.load_project(pid)
    b = storage.load_project(pid)
    storage.current_user.set("佐藤 花子")
    a["name"] = "先に保存"
    storage.save_project(a)
    b["name"] = "古い内容から保存"
    with pytest.raises(storage.Conflict) as e:
        storage.save_project(b)
    assert e.value.modified_by == "佐藤 花子"
    assert storage.load_project(pid)["name"] == "先に保存"


def test_history_and_revisions_are_appended_once(client, manager, demo):
    pid = demo["id"]
    n = len(storage.load_project(pid)["history"])
    client.post(f"/api/projects/{pid}/questions", json={"question": "一つ目"})
    client.post(f"/api/projects/{pid}/questions", json={"question": "二つ目"})
    h = client.get(f"/api/projects/{pid}").json()["history"]
    assert len(h) == n + 2 and "二つ目" in h[0]["detail"]
    assert all("_hid" not in x for x in h)                                    # 内部の行 ID は応答に出さない
    client.post(f"/api/projects/{pid}/fields/main_power", json={"action": "choose", "choice": 0})
    client.post(f"/api/projects/{pid}/fields/protection", json={"action": "edit", "value": "IP4X"})
    client.patch(f"/api/projects/{pid}/settings", json={"enclosure_id": "ST-9007"})
    manager.post(f"/api/projects/{pid}/approve", json={})
    manager.post(f"/api/projects/{pid}/unapprove")
    p = manager.post(f"/api/projects/{pid}/approve", json={}).json()
    assert [r["rev"] for r in p["revisions"]] == [1, 2] and all("_rid" not in r for r in p["revisions"])
    from app import storage_db
    c = storage_db.db()
    assert c.revision.count(where={"projectId": pid}) == 2
    assert c.historyentry.count(where={"projectId": pid}) == len(p["history"])


def test_deleting_document_and_project_cleans_rows(client, demo, fake_ai):
    from app import storage_db
    c = storage_db.db()
    pid = demo["id"]
    did = demo["documents"][0]["id"]
    client.post(f"/api/projects/{pid}/documents/{did}/ai")
    assert c.airesult.count(where={"documentId": did}) == 1 and c.parseddocument.count(where={"documentId": did}) == 1
    client.delete(f"/api/projects/{pid}/documents/{did}")
    assert c.document.count(where={"id": did}) == 0
    assert c.airesult.count(where={"documentId": did}) == 0 and c.parseddocument.count(where={"documentId": did}) == 0
    client.delete(f"/api/projects/{pid}")
    assert c.project.count() == 0 and c.parseddocument.count() == 0 and c.historyentry.count() == 0


def test_masters_and_users_seeded_from_json(client, manager):
    from app import storage_db
    c = storage_db.db()
    assert [u["role"] for u in client.get("/api/users").json()] == ["設計担当", "設計課長", "営業担当"]
    parts = client.get("/api/master/parts").json()
    parts[0]["price"] = 12345
    assert manager.put("/api/master/parts", json=parts).json()["ok"]
    row = c.masterdata.find_unique(where={"name": "parts"})
    assert row.data[0]["price"] == 12345 and row.updatedBy == "佐藤 花子"
    assert client.get("/api/health").json()["storage"] == "db"


def test_rev_endpoint_reads_lightweight_row(client, demo):
    r = client.get(f"/api/projects/{demo['id']}/rev").json()
    assert r["rev"] >= 1 and r["modified_by"] == "山田 太郎" and len(r["updated_at"]) == 19


def test_import_json_projects_without_touching_source(tmp_path, client, fake_ai):
    """JSON 保存の案件フォルダから取り込める（元ファイルは変更しない・二度目はスキップ）。"""
    import hashlib
    import json
    import shutil
    from app import import_json, storage_db
    p = client.post("/api/projects/demo").json()
    pid = p["id"]
    client.post(f"/api/projects/{pid}/documents/{p['documents'][0]['id']}/ai")
    src = tmp_path / "old"
    d = src / pid
    (d / "parsed").mkdir(parents=True)
    (d / "ai").mkdir()
    (d / "files").mkdir()
    full = client.get(f"/api/projects/{pid}").json()
    full.pop("rev"), full.pop("status")
    (d / "project.json").write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
    for doc in full["documents"]:
        if (x := storage.load_parsed(pid, doc["id"])) is not None:
            (d / "parsed" / f"{doc['id']}.json").write_text(json.dumps(x, ensure_ascii=False), encoding="utf-8")
        if (x := storage.load_ai(pid, doc["id"])) is not None:
            (d / "ai" / f"{doc['id']}.json").write_text(json.dumps(x, ensure_ascii=False), encoding="utf-8")
        f = storage.project_dir(pid) / "files" / f"{doc['id']}{doc['ext']}"
        (d / "files" / f.name).write_bytes(f.read_bytes())
    before = hashlib.sha256((d / "project.json").read_bytes()).hexdigest()
    storage_db.truncate_all()
    shutil.rmtree(storage.project_dir(pid))

    done, skipped = import_json.import_dir(src)
    assert len(done) == 1 and not skipped
    q = client.get(f"/api/projects/{pid}").json()
    assert q["quote_no"] == full["quote_no"] and len(q["documents"]) == 3 and len(q["history"]) == len(full["history"])
    assert q["updated_at"] == full["updated_at"]
    assert client.get(f"/api/projects/{pid}/documents/{full['documents'][0]['id']}/file").status_code == 200
    assert client.post(f"/api/projects/{pid}/analyze").json()["analysis"]["ai"]["used"]       # AI 結果も引き継がれる
    assert hashlib.sha256((d / "project.json").read_bytes()).hexdigest() == before          # 元ファイルは変更しない
    assert import_json.import_dir(src) == ([], [f"{full['quote_no']} {full['name']}（登録済み）"])


def test_master_versions_table_and_new_rule_groups(manager):
    from app import storage_db
    old = storage.load_master("rules")
    for k in ("market", "effect"):                     # 以前の版で保存された（新しい設定グループがない）ルール
        old.pop(k)
    storage_db.db().masterdata.update(where={"name": "rules"}, data={"data": storage_db._j(old)})
    rules = manager.get("/api/master/rules").json()
    assert rules["market"]["steel_index"] == 100 and rules["effect"]["baseline_hours"] == 6.0   # 初期データの値で補う
    rules["market"]["steel_index"] = 105
    assert manager.put("/api/master/rules", json=rules).json()["version"] == 2
    rows = storage_db.db().masterversion.find_many(where={"name": "rules"}, order={"version": "asc"})
    assert [r.version for r in rows] == [1, 2] and rows[1].createdBy == "佐藤 花子" and rows[1].data["market"]["steel_index"] == 105
    assert storage.load_master_version("rules", 1)["market"]["steel_index"] == 100
