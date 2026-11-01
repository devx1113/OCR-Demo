"""PostgreSQL（Prisma Client Python）による永続化。storage.py と同じ関数を提供し、案件は従来と同じ dict の形で受け渡す。

- 案件の保存は更新番号（rev）による楽観的排他制御。読み込んだ後に他の担当者が保存していれば Conflict を送出する
  （複数のサーバープロセス・コンテナで動かしても、後からの保存で他人の更新を上書きしない）
- 履歴と見積の版は追記のみ。資料は案件の保存時に一覧と同期する
- マスタ・担当者は初回アクセス時に backend/data/master の JSON から投入する
"""
import json
import threading
from datetime import datetime

from prisma import Json, Prisma

from . import storage

_client: Prisma | None = None
_client_lock = threading.Lock()


def db() -> Prisma:
    global _client
    with _client_lock:
        if _client is None:
            _client = Prisma()
        if not _client.is_connected():
            _client.connect()
        return _client


def disconnect():
    global _client
    with _client_lock:
        if _client is not None and _client.is_connected():
            _client.disconnect()


# ---------- 日時（画面・履歴は「2026-10-31T10:21:00」形式のローカル時刻で扱う） ----------

def _to_dt(s: str | None) -> datetime:
    return (datetime.fromisoformat(s) if s else datetime.now()).astimezone()


def _from_dt(d: datetime | None) -> str | None:
    return d.astimezone().replace(tzinfo=None).isoformat(timespec="seconds") if d else None


# ---------- 列の対応（案件 dict のキー ↔ テーブルの列） ----------

PROJECT_SCALAR = {"quote_no": "quoteNo", "name": "name", "customer": "customer", "owner": "owner", "due_date": "dueDate",
                  "analysis_stale": "analysisStale", "exported_at": "exportedAt", "modified_by": "modifiedBy"}
PROJECT_JSON = {"settings": ("settings", {}), "field_overrides": ("fieldOverrides", {}), "component_overrides": ("componentOverrides", {}),
                "extra_components": ("extraComponents", []), "custom_questions": ("customQuestions", []), "chat": ("chat", []),
                "approval": ("approval", None), "ai_review": ("aiReview", None), "analysis": ("analysis", None)}
# 保存しないキー（別テーブル・保存時に決まる値・表示用に計算する値）
PROJECT_SKIP = {"id", "documents", "history", "revisions", "rev", "created_at", "updated_at", "status"}

DOC_COLS = {"filename": "filename", "ext": "ext", "size": "size", "sha256": "sha256", "kind": "kind", "pages": "pages",
            "text_layer": "textLayer", "status": "status", "role": "role", "received_date": "receivedDate", "version": "version",
            "title": "title", "doc_no": "docNo", "include": "include", "uploaded_at": "uploadedAt", "uploaded_by": "uploadedBy",
            "blocks": "blocks", "tables": "tables"}


def _j(v):
    return Json(v)


def _project_data(p: dict) -> dict:
    data = {col: p.get(k) for k, col in PROJECT_SCALAR.items() if k in p}
    data.setdefault("customer", "")
    data.setdefault("owner", "")
    data["analysisStale"] = bool(p.get("analysis_stale"))
    data["modifiedBy"] = p.get("modified_by") or ""
    for k, (col, default) in PROJECT_JSON.items():
        v = p.get(k, default)
        if v is not None:
            data[col] = _j(v)
    extra = {k: v for k, v in p.items() if k not in PROJECT_SKIP and k not in PROJECT_SCALAR and k not in PROJECT_JSON}
    data["extra"] = _j(extra)
    return data


def _doc_data(d: dict, pos: int) -> dict:
    data = {col: d.get(k) for k, col in DOC_COLS.items()}
    data["textLayer"] = bool(d.get("text_layer", True))
    data["include"] = bool(d.get("include", True))
    data["messages"] = _j(d.get("messages") or [])
    data["extra"] = _j({k: v for k, v in d.items() if k not in DOC_COLS and k not in ("id", "messages")})
    data["position"] = pos
    return data


def _doc_dict(r) -> dict:
    d = {"id": r.id, **{k: getattr(r, col) for k, col in DOC_COLS.items()}, "messages": r.messages or []}
    d.update(r.extra or {})
    for k in ("blocks", "tables"):  # 未解析の資料には付けない（従来の dict と同じ形にする）
        if d[k] is None:
            d.pop(k)
    return d


def _project_dict(r, *, history=True) -> dict:
    p = {"id": r.id, "rev": r.rev, "created_at": _from_dt(r.createdAt), "updated_at": _from_dt(r.updatedAt)}
    for k, col in PROJECT_SCALAR.items():
        p[k] = getattr(r, col)
    for k, (col, _default) in PROJECT_JSON.items():
        v = getattr(r, col)
        if v is not None:
            p[k] = v
    p.update(r.extra or {})
    p["documents"] = [_doc_dict(d) for d in sorted(r.documents or [], key=lambda x: x.position)]
    p["history"] = ([{"at": h.at, "user": h.user, "action": h.action, "detail": h.detail, "_hid": h.id}
                     for h in sorted(r.history or [], key=lambda x: -x.id)] if history else [])
    p["revisions"] = [{**rv.data, "_rid": rv.id} for rv in sorted(r.revisions or [], key=lambda x: x.rev)]
    if not p["revisions"]:
        p.pop("revisions")
    return p


def strip_internal(p: dict) -> dict:
    """API の応答には DB 内部の番号（履歴・版の行 ID）を出さない。"""
    for h in p.get("history", []):
        h.pop("_hid", None)
    for rv in p.get("revisions", []) or []:
        rv.pop("_rid", None)
    return p


# ---------- マスタ・担当者 ----------

def _seed_master(name: str):
    f = storage.MASTER / f"{name}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def load_master(name: str):
    c = db()
    if name == "users":
        rows = c.user.find_many(order={"sort": "asc"})
        if not rows:
            seed = _seed_master("users") or {"users": []}
            for i, u in enumerate(seed["users"]):
                c.user.upsert(where={"name": u["name"]},
                              data={"create": {"name": u["name"], "role": u["role"], "perms": u["perms"], "sort": i},
                                    "update": {}})
            rows = c.user.find_many(order={"sort": "asc"})
        return {"users": [{"name": u.name, "role": u.role, "perms": list(u.perms)} for u in rows]}
    row = c.masterdata.find_unique(where={"name": name})
    if row is None:
        seed = _seed_master(name)
        if seed is None:
            raise FileNotFoundError(name)
        c.masterdata.upsert(where={"name": name}, data={"create": {"name": name, "data": _j(seed), "updatedBy": "初期データ"}, "update": {}})
        return seed
    data = row.data
    if isinstance(data, dict):  # 後の版で追加した設定グループ（例：rules.market）は初期データの値で補う
        seed = _seed_master(name)
        if isinstance(seed, dict):
            data = {**{k: v for k, v in seed.items() if k not in data}, **data}
    return data


def save_master(name: str, data):
    c = db()
    if name == "users":
        with c.tx() as tx:
            tx.user.delete_many()
            for i, u in enumerate(data["users"]):
                tx.user.create(data={"name": u["name"], "role": u["role"], "perms": u["perms"], "sort": i})
        return
    user = storage.current_user.get() or ""
    c.masterdata.upsert(where={"name": name}, data={
        "create": {"name": name, "data": _j(data), "updatedBy": user},
        "update": {"data": _j(data), "updatedBy": user, "updatedAt": datetime.now().astimezone()}})


def add_master_version(name: str, data, by: str, summary: str) -> int:
    c = db()
    last = c.masterversion.find_first(where={"name": name}, order={"version": "desc"})
    n = (last.version if last else 0) + 1
    c.masterversion.create(data={"name": name, "version": n, "data": _j(data), "createdBy": by, "summary": summary})
    return n


def list_master_versions(name: str) -> list[dict]:
    rows = db().masterversion.find_many(where={"name": name}, order={"version": "desc"}, take=storage.MASTER_VERSIONS_KEEP)
    return [{"version": r.version, "at": _from_dt(r.createdAt), "by": r.createdBy, "summary": r.summary} for r in rows]


def load_master_version(name: str, version: int):
    r = db().masterversion.find_unique(where={"name_version": {"name": name, "version": version}})
    return r.data if r else None


# ---------- 案件 ----------

_INCLUDE_FULL = {"documents": True, "history": True, "revisions": True}


def list_projects(history: bool = False) -> list[dict]:
    """案件の一覧。履歴は件数が多いため、必要な場合（効果測定）だけ読み込む。"""
    include = {"documents": True, "revisions": True, "history": history}
    rows = db().project.find_many(include=include, order={"createdAt": "desc"})
    out = [strip_internal(_project_dict(r, history=history)) for r in rows]
    return sorted(out, key=lambda p: (p["created_at"], p.get("quote_no", "")), reverse=True)


def load_project(pid: str) -> dict | None:
    storage.project_dir(pid)  # ID の形式チェック
    r = db().project.find_unique(where={"id": pid}, include=_INCLUDE_FULL)
    return _project_dict(r) if r else None


def project_rev(pid: str) -> dict | None:
    """更新番号と最終更新者だけを読む（同時編集の検知用。解析結果などの大きな列は読まない）。"""
    storage.project_dir(pid)
    rows = db().query_raw('SELECT rev, modified_by, updated_at FROM projects WHERE id = $1', pid)
    if not rows:
        return None
    r = rows[0]
    at = r["updated_at"]
    at = _from_dt(datetime.fromisoformat(at) if isinstance(at, str) else at)
    return {"rev": r["rev"], "modified_by": r["modified_by"], "updated_at": at}


def save_project(project: dict):
    """案件を保存する。読み込み時の rev から変わっていれば（他の担当者が先に保存していれば）Conflict。"""
    c = db()
    expected = int(project.get("rev") or 0)
    now = storage.now_iso()
    project["updated_at"] = now
    project["modified_by"] = storage.current_user.get() or project.get("modified_by") or ""
    data = _project_data(project)
    data["updatedAt"] = _to_dt(now)
    pid = project["id"]
    d = storage.project_dir(pid)
    (d / "files").mkdir(parents=True, exist_ok=True)

    with c.tx() as tx:
        if expected == 0 and tx.project.find_unique(where={"id": pid}) is None:
            tx.project.create(data={"id": pid, "rev": 1, "createdAt": _to_dt(project.get("created_at")), **data})
        else:
            n = tx.project.update_many(where={"id": pid, "rev": expected}, data={**data, "rev": expected + 1})
            if n == 0:
                cur = tx.project.find_unique(where={"id": pid})
                if cur is None:
                    raise storage.InvalidId(pid)
                raise storage.Conflict(cur.modifiedBy, _from_dt(cur.updatedAt))

        # 資料：一覧と同期（削除された資料は、構造化結果・AI 結果も消す）
        keep = [x["id"] for x in project.get("documents", [])]
        gone = [r.id for r in tx.document.find_many(where={"projectId": pid}) if r.id not in keep]
        if gone:
            tx.document.delete_many(where={"id": {"in": gone}})
            tx.parseddocument.delete_many(where={"documentId": {"in": gone}})
            tx.airesult.delete_many(where={"documentId": {"in": gone}})
        for i, doc in enumerate(project.get("documents", [])):
            dd = _doc_data(doc, i)
            tx.document.upsert(where={"id": doc["id"]}, data={"create": {"id": doc["id"], "projectId": pid, **dd}, "update": dd})

        # 履歴：まだ保存していない項目（_hid なし）を古い順に追記
        for h in reversed([h for h in project.get("history", []) if "_hid" not in h]):
            row = tx.historyentry.create(data={"projectId": pid, "at": h["at"], "user": h["user"], "action": h["action"],
                                               "detail": h.get("detail") or ""})
            h["_hid"] = row.id
        # 見積の版：追記のみ
        for rv in project.get("revisions", []) or []:
            if "_rid" in rv:
                continue
            body = {k: v for k, v in rv.items() if k != "_rid"}
            row = tx.revision.create(data={"projectId": pid, "rev": rv["rev"], "at": rv["at"], "approvedBy": rv.get("approved_by") or "",
                                           "saleTotal": int(rv.get("sale_total") or 0), "data": _j(body)})
            rv["_rid"] = row.id
    project["rev"] = expected + 1


def delete_project(pid: str):
    storage.project_dir(pid)
    c = db()
    with c.tx() as tx:
        tx.parseddocument.delete_many(where={"projectId": pid})
        tx.airesult.delete_many(where={"projectId": pid})
        tx.project.delete_many(where={"id": pid})


def next_quote_no() -> str:
    year = datetime.now().year
    rows = db().project.find_many(where={"quoteNo": {"startswith": f"Q{year}-"}})
    nums = []
    for r in rows:
        try:
            nums.append(int(r.quoteNo.split("-")[1]))
        except (IndexError, ValueError):
            pass
    return f"Q{year}-{(max(nums) + 1) if nums else 1:04d}"


# ---------- 資料の構造化結果・AI 結果 ----------

def save_parsed(pid: str, doc_id: str, parsed: dict):
    storage._doc_id(doc_id)
    db().parseddocument.upsert(where={"documentId": doc_id}, data={
        "create": {"documentId": doc_id, "projectId": pid, "data": _j(parsed)}, "update": {"data": _j(parsed)}})


def load_parsed(pid: str, doc_id: str) -> dict | None:
    storage._doc_id(doc_id)
    r = db().parseddocument.find_first(where={"documentId": doc_id, "projectId": pid})
    return r.data if r else None


def save_ai(pid: str, doc_id: str, data: dict):
    storage._doc_id(doc_id)
    row = {"projectId": pid, "kind": data.get("kind") or "extract", "cacheKey": data.get("cache_key") or "",
           "model": data.get("model") or "", "data": _j(data)}
    db().airesult.upsert(where={"documentId": doc_id}, data={"create": {"documentId": doc_id, **row}, "update": row})


def load_ai(pid: str, doc_id: str) -> dict | None:
    storage._doc_id(doc_id)
    r = db().airesult.find_first(where={"documentId": doc_id, "projectId": pid})
    return r.data if r else None


def truncate_all():
    """テスト用：全テーブルを空にする。"""
    db().execute_raw('TRUNCATE projects, documents, parsed_documents, ai_results, history, revisions, users, master_data, master_versions RESTART IDENTITY CASCADE')
