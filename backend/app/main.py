"""盤見積アシスタント（デモ版）API。"""
import json
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Body, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai, exports, impact, learning, parsing, report, revisions, similar, storage
from .analysis import analyze
from .config import ALLOWED_EXT, CELLMAP, FRONTEND_DIST, MAX_UPLOAD_MB, SAMPLES

@asynccontextmanager
async def _lifespan(_app):
    yield
    if storage.BACKEND == "db":  # 終了時にデータベース接続を閉じる
        from . import storage_db
        storage_db.disconnect()


app = FastAPI(title="盤見積アシスタント API", version="1.1.0", lifespan=_lifespan)


@app.exception_handler(storage.InvalidId)
def _invalid_id(_req, _exc):
    return JSONResponse(status_code=404, content={"detail": "案件または資料が見つかりません"})


@app.exception_handler(storage.Conflict)
def _conflict(_req, exc: storage.Conflict):
    """保存の直前に他の担当者が同じ案件を保存していた（データベースの更新番号で検知）。"""
    at = (exc.updated_at or "")[11:16]
    return JSONResponse(status_code=409, content={
        "code": "stale", "modified_by": exc.modified_by,
        "detail": f"{exc.modified_by or '他の担当者'} さんが {at} にこの案件を更新しました。最新の内容を読み込みましたので、もう一度操作してください。"})




_PROJECT_PATH = re.compile(r"^/api/projects/([0-9a-f]{12})(/.*)?$")
_project_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@app.middleware("http")
async def _concurrency(request, call_next):
    """複数の担当者が同じ案件を操作する場合の保護。
    - 画面が古い（他の担当者が更新した後の）状態のまま操作した場合は 409 で知らせ、最新の内容を読み込ませる
    - 同じ案件への更新は 1 件ずつ処理し、読み込み〜保存の間に他の更新が割り込んで内容が失われないようにする
      （AI 呼び出しは数十秒かかるため対象外。AI の結果は保存直前に最新の案件を読み直して追記する）"""
    user = unquote(request.headers.get("x-user") or "") or "担当者"
    storage.current_user.set(user)
    m = _PROJECT_PATH.match(request.url.path)
    if not m or request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    pid, rest = m.group(1), m.group(2) or ""
    seen = request.headers.get("x-project-rev") or ""
    if seen.isdigit():
        cur = await run_in_threadpool(storage.project_rev, pid)
        if cur and int(seen) < int(cur.get("rev") or 0) and cur.get("modified_by") and cur["modified_by"] != user:
            at = (cur.get("updated_at") or "")[11:16]
            return JSONResponse(status_code=409, content={
                "code": "stale", "rev": cur.get("rev"), "modified_by": cur["modified_by"],
                "detail": f"{cur['modified_by']} さんが {at} にこの案件を更新しました。最新の内容を読み込みましたので、もう一度操作してください。"})
    if rest == "/ai" or rest.startswith("/ai/") or rest.endswith("/ai"):
        return await call_next(request)
    with _locks_guard:
        lock = _project_locks.setdefault(pid, threading.Lock())
    await run_in_threadpool(lock.acquire)  # 待つ間もイベントループを止めない
    try:
        return await call_next(request)
    finally:
        lock.release()


ROLE_JA = {"main": "主仕様書", "supplement": "補足資料", "drawing": "図面", "other": "その他"}
MASTER_NAMES = {"parts", "enclosures", "rules", "dictionary"}
MASTER_JA = {"parts": "部品マスタ", "enclosures": "筐体マスタ", "rules": "判定・算定ルール", "dictionary": "変換辞書"}
MASTER_READONLY = {"past_projects"}  # 過去案件データ（デモ版は閲覧のみ。本番は既存の受注実績から移行）
DOC_STATUS_JA = {"ok": "正常", "warning": "警告", "error": "エラー"}


def _user(x_user: str | None) -> str:
    return unquote(x_user) if x_user else "担当者"


PERM_JA = {"edit": "資料・抽出値・見積の編集", "request": "承認依頼", "approve": "承認・差戻し", "export": "見積書の出力",
           "draft": "承認前の見積書（ドラフト）の出力", "master": "マスタ・設定の変更"}


def _users() -> list[dict]:
    try:
        return storage.load_master("users")["users"]
    except (OSError, ValueError, KeyError):
        return []


def _can(user: str, perm: str) -> bool:
    acc = next((u for u in _users() if u["name"] == user), None)
    return acc is None or perm in acc["perms"]  # 登録外（API の直接利用・自動処理）は制限しない


def _perm(x_user: str | None, perm: str) -> str:
    """担当者の権限を確認する（デモ版は画面で選んだ担当者名で判定。本番は社内認証と連携）。"""
    user = _user(x_user)
    if not _can(user, perm):
        acc = next(u for u in _users() if u["name"] == user)
        raise HTTPException(403, f"{acc['role']}（{user}）には「{PERM_JA[perm]}」の権限がありません")
    return user


def _num(v, label: str, lo: float, hi: float, integer: bool = False):
    """画面以外から不正な値が来ても 500 にせず 422 で返す（数値の型・範囲チェック）。"""
    if isinstance(v, bool):
        raise HTTPException(422, f"{label}は数値で指定してください")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{label}は数値で指定してください")
    if not (lo <= x <= hi) or (integer and x != int(x)):
        raise HTTPException(422, f"{label}は{lo:g}〜{hi:g}の{'整数' if integer else '数値'}で指定してください")
    return int(x) if integer else x


def _text(v, label: str, required: bool = False, max_len: int = 2000) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise HTTPException(422, f"{label}は文字列で指定してください")
    v = v.strip()
    if required and not v:
        raise HTTPException(422, f"{label}を入力してください")
    if len(v) > max_len:
        raise HTTPException(422, f"{label}は{max_len}文字以内で入力してください")
    return v


def _date(v, label: str):
    import datetime as _dt
    if v in (None, ""):
        return None
    try:
        return _dt.date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise HTTPException(422, f"{label}は YYYY-MM-DD 形式で指定してください")


MAX_QTY = 999


def _is_scan(doc: dict) -> bool:
    """テキスト層のない PDF（スキャン図面など）。AI-OCR の対象。"""
    return doc.get("ext") == ".pdf" and not doc.get("text_layer", True) and doc["status"] != "error" and doc.get("include", True)


def _get(pid: str) -> dict:
    p = storage.load_project(pid)
    if not p:
        raise HTTPException(404, "案件が見つかりません")
    return p


def _status(p: dict) -> str:
    if not p["documents"]:
        return "資料待ち"
    a = p.get("analysis")
    if not a or p.get("analysis_stale"):
        return "解析待ち"
    st = (p.get("approval") or {}).get("status")
    if st == "approved":
        return "出力済" if p.get("exported_at") else "承認済"
    if st == "requested":
        return "承認待ち"
    if st == "returned":
        return "差戻し"
    return "確認中" if a["stats"]["blocking"] else "確認完了"


def _view(p: dict) -> dict:
    p["status"] = _status(p)
    return storage.strip_internal(p)


def _recompute(p: dict, user: str, reason: str):
    st = (p.get("approval") or {}).get("status")
    if st == "approved":
        p["approval"] = {"status": "revoked", "by": user, "at": storage.now_iso()}
        storage.add_history(p, user, "承認取消", f"承認後の変更（{reason}）のため承認を取り消しました")
    elif st == "requested":
        p["approval"] = {"status": "withdrawn", "by": user, "at": storage.now_iso()}
        storage.add_history(p, user, "承認依頼の取下げ", f"依頼後の変更（{reason}）のため、承認依頼を取り下げました")
    if p.get("analysis") and not p.get("analysis_stale"):
        p["analysis"] = analyze(p)


def _save(p: dict) -> dict:
    storage.save_project(p)
    return _view(p)


def _summary(p: dict) -> dict:
    a = p.get("analysis") or {}
    return {
        "id": p["id"], "quote_no": p["quote_no"], "name": p["name"], "customer": p.get("customer", ""),
        "owner": p.get("owner", ""), "due_date": p.get("due_date"), "created_at": p["created_at"],
        "updated_at": p.get("updated_at"), "status": _status(p), "documents": len(p["documents"]),
        "stats": a.get("stats"), "verdict": (a.get("fit") or {}).get("verdict"),
        "sale_total": (a.get("estimate") or {}).get("sale_total"),
        "approval": {k: (p.get("approval") or {}).get(k) for k in ("status", "by", "at", "comment")} if p.get("approval") else None,
        "revisions": len(p.get("revisions") or []), "modified_by": p.get("modified_by") or "",
    }


# ---------- 案件 ----------

@app.get("/api/health")
def health():
    return {"ok": True, "pdf_preview": exports.soffice_available(), "ai": ai.status(), "storage": storage.BACKEND}


@app.get("/api/projects")
def list_projects():
    return [_summary(p) for p in storage.list_projects()]


@app.post("/api/projects")
def create_project(body: dict = Body(...), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    user = _user(x_user)
    name = _text(body.get("name"), "案件名", required=True, max_len=200)
    p = {
        "id": storage.new_id(), "quote_no": storage.next_quote_no(), "name": name,
        "customer": _text(body.get("customer"), "顧客名", max_len=200), "owner": _text(body.get("owner"), "担当者", max_len=100) or user,
        "due_date": _date(body.get("due_date"), "回答期限"),
        "created_at": storage.now_iso(), "documents": [], "history": [], "settings": {},
        "field_overrides": {}, "component_overrides": {}, "extra_components": [], "custom_questions": [],
    }
    storage.add_history(p, user, "案件作成", p["name"])
    return _save(p)


DEMO_DOCS = ("送水ポンプ制御盤_製作仕様書.pdf", "仕様補足・変更連絡書_No1.docx", "外形図_スキャン.pdf")
EXTRA_SAMPLES = {"reply": "顧客回答メール_仕様確認.pdf"}


@app.post("/api/projects/demo")
def create_demo(analyze_now: bool = Query(True, alias="analyze"), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    """デモ案件を作成する。画面からは analyze=false で呼び、AI 読解の進捗を見せながら解析する。"""
    user = _user(x_user)
    p = create_project({"name": "第二浄水場 送水ポンプ制御盤", "customer": "湊川水道設備株式会社",
                        "due_date": "2026-11-13"}, x_user)
    for name in DEMO_DOCS:
        src = SAMPLES / name
        if src.exists():
            _register(p, src.read_bytes(), name, user)
    if analyze_now:
        p["analysis"] = analyze(p)
        storage.add_history(p, user, "解析実行", "デモ資料を自動解析")
    return _save(p)


@app.post("/api/projects/{pid}/samples/{kind}")
def add_sample(pid: str, kind: str, x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    name = EXTRA_SAMPLES.get(kind)
    if not name or not (SAMPLES / name).exists():
        raise HTTPException(404, "サンプルが見つかりません")
    _register(p, (SAMPLES / name).read_bytes(), name, _user(x_user))
    return _save(p)


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _view(_get(pid))


@app.patch("/api/projects/{pid}")
def update_project(pid: str, body: dict = Body(...), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    labels = {"name": "案件名", "customer": "顧客名", "due_date": "回答期限", "owner": "担当者"}
    changed = [k for k in labels if k in body]
    for k in changed:
        p[k] = _date(body[k], labels[k]) if k == "due_date" else _text(body[k], labels[k], required=(k == "name"), max_len=200)
    if not changed:
        return _view(p)
    storage.add_history(p, _user(x_user), "案件情報更新", "、".join(labels[k] for k in changed))
    return _save(p)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str, x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    _get(pid)
    storage.delete_project(pid)
    return {"ok": True}


# ---------- 資料 ----------

def _register(p: dict, data: bytes, filename: str, user: str) -> dict:
    filename = Path(filename).name
    ext = Path(filename).suffix.lower()
    did = storage.new_id()
    d = storage.project_dir(p["id"]) / "files"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{did}{ext}"
    path.write_bytes(data)
    digest = parsing.sha256(path)
    dup = next((x for x in p["documents"] if x.get("sha256") == digest), None)
    if dup:
        path.unlink()
        raise HTTPException(409, f"同じ内容の資料が既に登録されています（{dup['filename']}）")
    if ext in ALLOWED_EXT:
        info = parsing.inspect(path, ext)
    else:
        info = {"kind": ext.lstrip("."), "pages": None, "text_layer": False, "status": "error",
                "messages": ["未対応の形式です（PDF / Word(.docx) / Excel(.xlsx) に対応）。"]}
    doc = {"id": did, "filename": filename, "ext": ext, "size": len(data), "sha256": digest,
           "uploaded_at": storage.now_iso(), "uploaded_by": user, "include": True, **info,
           "role": "other", "received_date": None, "version": None, "title": None, "doc_no": None}
    if info["status"] != "error" and info.get("text_layer", True):
        try:
            parsed = parsing.parse(path, info["kind"])
            storage.save_parsed(p["id"], did, parsed)
            if not parsed["blocks"]:
                doc.update(status="warning", messages=["文字が含まれていません（空のファイル）。抽出対象になる情報がありません。"])
            meta = parsing.guess_meta(parsed, storage.load_master("dictionary")["meta_fields"])
            doc.update(role=meta["role"], received_date=meta.get("issue_date") or storage.now_iso()[:10],
                       version=meta.get("version"), title=meta.get("title"), doc_no=meta.get("doc_no"),
                       blocks=len(parsed["blocks"]), tables=sum(1 for b in parsed["blocks"] if b["type"] == "table"))
            if not parsed["blocks"]:
                doc["role"] = "other"
        except Exception as e:  # noqa: BLE001 — 解析失敗は資料単位のエラーとして表示する
            doc.update(status="error", messages=[f"解析中にエラーが発生しました：{e}"])
    elif info["status"] != "error":
        doc.update(role="drawing", received_date=storage.now_iso()[:10])
    p["documents"].append(doc)
    if p.get("analysis"):
        p["analysis_stale"] = True
    storage.add_history(p, user, "資料登録", f"{filename}（{ROLE_JA.get(doc['role'])}・{DOC_STATUS_JA[doc['status']]}）")
    return doc


@app.post("/api/projects/{pid}/documents")
async def upload_document(pid: str, file: UploadFile = File(...), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"ファイルサイズが上限（{MAX_UPLOAD_MB}MB）を超えています")
    _register(p, data, file.filename or "upload", _user(x_user))
    return _save(p)


@app.patch("/api/projects/{pid}/documents/{did}")
def update_document(pid: str, did: str, body: dict = Body(...), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    doc = next((d for d in p["documents"] if d["id"] == did), None)
    if not doc:
        raise HTTPException(404, "資料が見つかりません")
    if "role" in body and body["role"] not in ROLE_JA:
        raise HTTPException(422, "資料の種別が不正です")
    if "include" in body and not isinstance(body["include"], bool):
        raise HTTPException(422, "include は true / false で指定してください")
    if "received_date" in body:
        body["received_date"] = _date(body["received_date"], "受領日")
    if "version" in body:
        body["version"] = _text(body["version"], "版", max_len=40) or None
    changed = []
    for k in ("role", "received_date", "version", "include"):
        if k in body and body[k] != doc.get(k):
            doc[k] = body[k]
            changed.append(k)
    if changed:
        if p.get("analysis"):
            p["analysis_stale"] = True
        storage.add_history(p, _user(x_user), "資料情報更新", f"{doc['filename']}：{'、'.join(changed)}")
    return _save(p)


@app.delete("/api/projects/{pid}/documents/{did}")
def delete_document(pid: str, did: str, x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    doc = next((d for d in p["documents"] if d["id"] == did), None)
    if not doc:
        raise HTTPException(404, "資料が見つかりません")
    p["documents"].remove(doc)
    for sub in ("files", "parsed", "ai"):
        for f in (storage.project_dir(pid) / sub).glob(f"{did}.*"):
            f.unlink()
    if p.get("analysis"):
        p["analysis_stale"] = True
    storage.add_history(p, _user(x_user), "資料削除", doc["filename"])
    return _save(p)


@app.get("/api/projects/{pid}/documents/{did}/file")
def document_file(pid: str, did: str):
    p = _get(pid)
    doc = next((d for d in p["documents"] if d["id"] == did), None)
    if not doc:
        raise HTTPException(404)
    path = storage.project_dir(pid) / "files" / f"{did}{doc['ext']}"
    return FileResponse(path, filename=doc["filename"],
                        content_disposition_type="inline" if doc["ext"] == ".pdf" else "attachment")


@app.get("/api/projects/{pid}/documents/{did}/ocr")
def document_ocr(pid: str, did: str):
    """画像PDF を AI-OCR で読み取った結果（書き起こし・寸法注記）。まだ読み取っていなければ null。"""
    _get(pid)
    r = storage.load_ai(pid, did)
    return r if r and r.get("kind") == "ocr" else None


@app.get("/api/projects/{pid}/documents/{did}/parsed")
def document_parsed(pid: str, did: str):
    parsed = storage.load_parsed(pid, did)
    if parsed is None:
        raise HTTPException(404, "解析結果がありません")
    return parsed


# ---------- 解析・確認 ----------

@app.post("/api/projects/{pid}/analyze")
def run_analysis(pid: str, x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    user = _user(x_user)
    p["analysis_stale"] = False
    p["analysis"] = analyze(p)
    s = p["analysis"]["stats"]
    storage.add_history(p, user, "解析実行", f"項目 {s['fields_found']}件・機器 {s['components']}件・要確認 {s['issues']}件")
    if (p.get("approval") or {}).get("status") == "approved":
        p["approval"] = {"status": "revoked", "by": user, "at": storage.now_iso()}
    return _save(p)


@app.post("/api/projects/{pid}/fields/{key}")
def field_action(pid: str, key: str, body: dict = Body(...), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    user = _user(x_user)
    act = body.get("action")
    if act not in ("edit", "confirm", "choose", "ask"):
        raise HTTPException(422, "不正な操作です")
    field = next((f for f in (p.get("analysis") or {}).get("fields", []) if f["key"] == key), None)
    if not field:
        raise HTTPException(404, "項目が見つかりません")
    o = {"action": act, "by": user, "at": storage.now_iso(), "reason": _text(body.get("reason"), "理由", max_len=500)}
    if act == "edit":
        o["value"] = _text(body.get("value"), "値", max_len=2000)
        detail = f"{field['label']}：「{field['value']}」→「{o['value']}」"
    elif act == "choose":
        cands = field.get("candidates") or []
        if len(cands) < 2:
            raise HTTPException(409, "この項目には選択できる候補がありません")
        o["choice"] = _num(body.get("choice", 0), "候補番号", 0, len(cands) - 1, integer=True)
        detail = f"{field['label']}：「{field['candidates'][o['choice']]['value']}」を採用"
    elif act == "confirm":
        detail = f"{field['label']}：「{field['value']}」を確定"
    else:
        detail = f"{field['label']}：質疑書で顧客に確認"
    if o["reason"]:
        detail += f"（理由：{o['reason']}）"
    p.setdefault("field_overrides", {})[key] = o
    storage.add_history(p, user, {"edit": "値の修正", "confirm": "値の確定", "choose": "矛盾の解決", "ask": "質疑へ回す"}[act], detail)
    _recompute(p, user, detail)
    return _save(p)


@app.delete("/api/projects/{pid}/fields/{key}")
def field_reset(pid: str, key: str, x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    user = _user(x_user)
    if p.get("field_overrides", {}).pop(key, None):
        storage.add_history(p, user, "修正の取消", key)
        _recompute(p, user, "修正の取消")
    return _save(p)


@app.post("/api/projects/{pid}/components/{ckey}")
def component_action(pid: str, ckey: str, body: dict = Body(...), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    user = _user(x_user)
    if "qty" in body and body["qty"] is not None:
        body["qty"] = _num(body["qty"], "数量", 0, MAX_QTY, integer=True)
    if "model" in body:
        body["model"] = _text(body["model"], "型式", max_len=100)
    for k in ("deleted", "confirmed"):
        if k in body and not isinstance(body[k], bool):
            raise HTTPException(422, f"{k} は true / false で指定してください")
    known = {c["key"] for c in (p.get("analysis") or {}).get("components", [])}
    if p.get("analysis") and ckey not in known:
        raise HTTPException(404, "構成機器が見つかりません")
    o = p.setdefault("component_overrides", {}).setdefault(ckey, {})
    parts = []
    for k in ("qty", "model", "deleted", "confirmed"):
        if k in body and body[k] is not None:
            o[k] = body[k]
            parts.append({"qty": f"数量 {body[k]}", "model": f"型式 {body[k]}",
                          "deleted": "削除" if body[k] else "削除取消", "confirmed": "確定"}[k])
    o.update(by=user, at=storage.now_iso())
    storage.add_history(p, user, "構成機器の修正", f"{ckey}：{'・'.join(parts)}")
    _recompute(p, user, "構成機器の修正")
    return _save(p)


@app.delete("/api/projects/{pid}/components/{ckey}")
def component_reset(pid: str, ckey: str, x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    user = _user(x_user)
    p["extra_components"] = [e for e in p.get("extra_components", []) if e["key"] != ckey]
    p.get("component_overrides", {}).pop(ckey, None)
    storage.add_history(p, user, "構成機器の修正を取消", ckey)
    _recompute(p, user, "構成機器の修正取消")
    return _save(p)


@app.post("/api/projects/{pid}/components")
def component_add(pid: str, body: dict = Body(...), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    user = _user(x_user)
    name = _text(body.get("name"), "品名", required=True, max_len=100)
    mount = body.get("mount") or None
    if mount not in (None, "plate", "door", "terminal"):
        raise HTTPException(422, "取付位置が不正です")
    e = {"key": f"man-{storage.new_id()[:6]}", "name": name, "model": _text(body.get("model"), "型式", max_len=100),
         "spec": _text(body.get("spec"), "仕様", max_len=200), "qty": _num(body.get("qty") or 1, "数量", 1, MAX_QTY, integer=True),
         "mount": mount, "by": user}
    p.setdefault("extra_components", []).append(e)
    storage.add_history(p, user, "構成機器の追加", f"{e['name']} {e['model']} × {e['qty']}")
    _recompute(p, user, "構成機器の追加")
    return _save(p)


@app.patch("/api/projects/{pid}/settings")
def update_settings(pid: str, body: dict = Body(...), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    user = _user(x_user)
    s = p.setdefault("settings", {})
    details = []
    if "enclosure_id" in body:
        if body["enclosure_id"] and body["enclosure_id"] not in {e["id"] for e in storage.load_master("enclosures")}:
            raise HTTPException(422, "筐体がマスタにありません")
        s["enclosure_id"] = body["enclosure_id"] or None
        details.append(f"筐体を {body['enclosure_id']} に変更" if body["enclosure_id"] else "筐体を仕様書指定に戻す")
    for k in ("include_fan", "ai"):
        if k in body and not isinstance(body[k], bool):
            raise HTTPException(422, f"{k} は true / false で指定してください")
    if "margin" in body:
        body["margin"] = max(0.0, min(0.6, _num(body["margin"], "利益率", -1e6, 1e6)))  # 範囲外は 0〜60% に丸める
    if "include_fan" in body:
        s["include_fan"] = bool(body["include_fan"])
        details.append("推奨ファンを見積に含める" if body["include_fan"] else "推奨ファンを見積から外す")
    if "ai" in body:
        s["ai"] = bool(body["ai"])
        details.append("AI 読解の結果を使用" if body["ai"] else "AI 読解の結果を使用しない")
    if "margin" in body:
        s["margin"] = body["margin"]
        details.append(f"利益率 {s['margin'] * 100:.1f}%")
    if not details:
        return _view(p)
    storage.add_history(p, user, "設定変更", "・".join(details))
    _recompute(p, user, "・".join(details))
    return _save(p)


@app.post("/api/projects/{pid}/estimate/lines/{lid}")
def estimate_line(pid: str, lid: str, body: dict = Body(...), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    user = _user(x_user)
    lines = ((p.get("analysis") or {}).get("estimate") or {}).get("lines", [])
    if not any(ln["id"] == lid for ln in lines):
        raise HTTPException(404, "見積明細が見つかりません")
    vals = {}
    if body.get("qty") is not None:
        vals["qty"] = _num(body["qty"], "数量", 0, 10000)
    if body.get("unit_cost") is not None:
        vals["unit_cost"] = _num(body["unit_cost"], "単価", 0, 1e9)
    if not vals:
        raise HTTPException(422, "数量または単価を指定してください")
    o = p.setdefault("settings", {}).setdefault("line_overrides", {}).setdefault(lid, {})
    o.update(vals)
    storage.add_history(p, user, "見積明細の修正", f"{lid}：" + "・".join(f"{k}={v:g}" for k, v in o.items()))
    _recompute(p, user, "見積明細の修正")
    return _save(p)


@app.delete("/api/projects/{pid}/estimate/lines/{lid}")
def estimate_line_reset(pid: str, lid: str, x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    user = _user(x_user)
    p.get("settings", {}).get("line_overrides", {}).pop(lid, None)
    storage.add_history(p, user, "見積明細の修正を取消", lid)
    _recompute(p, user, "見積明細の修正取消")
    return _save(p)


@app.post("/api/projects/{pid}/questions")
def add_question(pid: str, body: dict = Body(...), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    user = _user(x_user)
    q = {"id": storage.new_id()[:8], "question": _text(body.get("question"), "質疑内容", required=True, max_len=1000),
         "item": _text(body.get("item"), "項目", max_len=100), "category": _text(body.get("category"), "分類", max_len=40) or "その他", "by": user}
    p.setdefault("custom_questions", []).append(q)
    storage.add_history(p, user, "質疑の追加", q["question"][:40])
    _recompute(p, user, "質疑の追加")
    return _save(p)


@app.delete("/api/projects/{pid}/questions/{qid}")
def delete_question(pid: str, qid: str, x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    p = _get(pid)
    user = _user(x_user)
    p["custom_questions"] = [q for q in p.get("custom_questions", []) if q["id"] != qid]
    storage.add_history(p, user, "質疑の削除", qid)
    _recompute(p, user, "質疑の削除")
    return _save(p)


def _approvable(p: dict) -> dict:
    a = p.get("analysis")
    if not a or p.get("analysis_stale"):
        raise HTTPException(409, "最新の解析結果がありません。解析を実行してください。")
    blocking = [i for i in a["issues"] if i.get("blocking")]
    if blocking:
        raise HTTPException(409, f"未解決の要確認事項が {len(blocking)} 件あるため承認できません。")
    return a


@app.post("/api/projects/{pid}/approval/request")
def request_approval(pid: str, body: dict = Body(default={}), x_user: str | None = Header(None)):
    user = _perm(x_user, "request")
    p = _get(pid)
    a = _approvable(p)
    if (p.get("approval") or {}).get("status") in ("approved", "requested"):
        raise HTTPException(409, "既に承認依頼中、または承認済みです")
    comment = _text(body.get("comment"), "コメント", max_len=500)
    p["approval"] = {"status": "requested", "by": user, "at": storage.now_iso(), "comment": comment,
                     "sale_total": a["estimate"]["sale_total"]}
    storage.add_history(p, user, "承認依頼", f"見積金額 {a['estimate']['sale_total']:,}円（税抜）" + (f"／{comment}" if comment else ""))
    return _save(p)


@app.post("/api/projects/{pid}/approve")
def approve(pid: str, body: dict = Body(default={}), x_user: str | None = Header(None)):
    user = _perm(x_user, "approve")
    p = _get(pid)
    a = _approvable(p)
    comment = _text(body.get("comment"), "コメント", max_len=500)
    req = p["approval"] if (p.get("approval") or {}).get("status") == "requested" else {}
    rev = len(p.get("revisions") or []) + 1
    p.setdefault("revisions", []).append(revisions.snapshot(
        p, a, rev, approved_by=user, comment=comment, requested_by=req.get("by"), requested_at=req.get("at")))
    p["approval"] = {"status": "approved", "by": user, "at": storage.now_iso(), "comment": comment,
                     "sale_total": a["estimate"]["sale_total"], "rev": rev, "requested_by": req.get("by"), "requested_at": req.get("at")}
    storage.add_history(p, user, "承認", f"第{rev}版・見積金額 {a['estimate']['sale_total']:,}円（税抜）" + (f"／{comment}" if comment else ""))
    return _save(p)


@app.post("/api/projects/{pid}/approval/return")
def return_approval(pid: str, body: dict = Body(default={}), x_user: str | None = Header(None)):
    user = _perm(x_user, "approve")
    p = _get(pid)
    req = p.get("approval") or {}
    if req.get("status") != "requested":
        raise HTTPException(409, "承認依頼中の案件ではありません")
    comment = _text(body.get("comment"), "差戻しの理由", required=True, max_len=500)
    p["approval"] = {"status": "returned", "by": user, "at": storage.now_iso(), "comment": comment,
                     "requested_by": req.get("by"), "requested_at": req.get("at")}
    storage.add_history(p, user, "差戻し", comment)
    return _save(p)


@app.post("/api/projects/{pid}/unapprove")
def unapprove(pid: str, x_user: str | None = Header(None)):
    user = _perm(x_user, "approve")
    p = _get(pid)
    p["approval"] = {"status": "revoked", "by": user, "at": storage.now_iso()}
    storage.add_history(p, user, "承認取消", "")
    return _save(p)


@app.get("/api/projects/{pid}/revisions/compare")
def compare_revisions(pid: str, a: str = Query(...), b: str = Query("current")):
    """承認済みの版どうし、または版と現在の作業中の内容を比較する。"""
    p = _get(pid)
    revs = {str(r["rev"]): r for r in p.get("revisions") or []}

    def pick(k: str) -> dict:
        if k == "current":
            if not p.get("analysis"):
                raise HTTPException(409, "解析結果がありません")
            return revisions.snapshot(p, p["analysis"], "current")
        if k not in revs:
            raise HTTPException(404, f"第{k}版が見つかりません")
        return revs[k]
    return revisions.diff(pick(a), pick(b))


@app.get("/api/projects/{pid}/rev")
def project_rev(pid: str):
    """画面が定期的に確認する、案件の更新番号と最終更新者（他の担当者の更新に気付けるように）。"""
    r = storage.project_rev(pid)
    if not r:
        raise HTTPException(404, "案件が見つかりません")
    return r


@app.get("/api/projects/{pid}/similar")
def similar_projects(pid: str, limit: int = Query(5, ge=1, le=20)):
    """類似過去案件（C12）：仕様・構成機器・盤サイズ・金額が近い過去の見積を、一致した点と異なる点付きで返す。"""
    p = _get(pid)
    if not p.get("analysis"):
        raise HTTPException(409, "解析結果がありません")
    return similar.search(p, storage.list_projects(), storage.load_master("parts"), limit)


@app.post("/api/projects/{pid}/fit/review")
def fit_review(pid: str, body: dict = Body(...), x_user: str | None = Header(None)):
    """収容判定に対する設計者の最終判断を記録する（G4：判定一致率の計測に使う。見積の計算は変えない）。"""
    user = _perm(x_user, "edit")
    p = _get(pid)
    a = p.get("analysis")
    if not a:
        raise HTTPException(409, "解析結果がありません")
    decision = body.get("decision")
    if decision not in ("agree", "disagree"):
        raise HTTPException(422, "decision は agree または disagree で指定してください")
    enc = a["fit"].get("enclosure") or {}
    system = {"verdict": a["fit"]["verdict"], "enclosure": enc.get("name"), "enclosure_id": enc.get("id")}
    r = {"decision": decision, "by": user, "at": storage.now_iso(), "system": system,
         "reason": _text(body.get("reason"), "理由", required=decision == "disagree", max_len=500)}
    if decision == "agree":
        r.update(final_verdict=system["verdict"], final_enclosure=system["enclosure"])
    else:
        if body.get("final_verdict") not in ("ok", "ng"):
            raise HTTPException(422, "設計者の判断（可・不可）を選んでください")
        r.update(final_verdict=body["final_verdict"], final_enclosure=_text(body.get("final_enclosure"), "筐体", max_len=100) or None)
    p["fit_review"] = r
    verdict_ja = {"ok": "可", "ng": "不可"}
    storage.add_history(p, user, "収容判定の最終判断",
                        "システムの判定どおり" if decision == "agree" else
                        f"システム「{verdict_ja.get(system['verdict'], system['verdict'])}」→ 設計者「{verdict_ja[r['final_verdict']]}」"
                        + (f"・{r['final_enclosure']}" if r.get("final_enclosure") else "") + f"（{r['reason']}）")
    return _save(p)


@app.delete("/api/projects/{pid}/fit/review")
def fit_review_reset(pid: str, x_user: str | None = Header(None)):
    user = _perm(x_user, "edit")
    p = _get(pid)
    if p.pop("fit_review", None):
        storage.add_history(p, user, "収容判定の最終判断を取消", "")
    return _save(p)


@app.get("/api/report/fit")
def fit_report():
    return report.fit_agreement(storage.list_projects())


@app.get("/api/report/effect")
def effect_report():
    return report.effect(storage.list_projects(history=True), storage.load_master("rules"))


@app.get("/api/report/regression")
def regression_report():
    """回帰チェック（G3）：保存済みの解析結果と、現在のマスタ・ルールで解析し直した結果を比べる。案件は変更しない。"""
    return impact.regression(storage.list_projects())


@app.get("/api/users")
def users():
    return [{"name": u["name"], "role": u["role"], "perms": u["perms"]} for u in _users()]


@app.get("/api/report/accuracy")
def accuracy_report():
    return report.accuracy(storage.list_projects())


# ---------- AI ----------

def _ai_call(fn):
    try:
        return fn()
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e))
    except ai.AIError as e:
        raise HTTPException(502, str(e))


def _require_ai():
    st = ai.status()
    if not st["configured"]:
        raise HTTPException(503, "OpenAI API キーが設定されていません（.env の OPENAI_API_KEY）")
    if not st["enabled"]:
        raise HTTPException(503, "AI 機能は設定で無効になっています")


AI_MODELS = ["gpt-5.4-mini", "gpt-5.4", "gpt-5.5", "gpt-5.4-nano", "gpt-4.1-mini", "gpt-4.1"]


@app.get("/api/ai/settings")
def get_ai_settings():
    return {**ai.status(), "models": AI_MODELS}


@app.put("/api/ai/settings")
def put_ai_settings(body: dict = Body(...), x_user: str | None = Header(None)):
    _perm(x_user, "master")
    if "enabled" in body and not isinstance(body["enabled"], bool):
        raise HTTPException(422, "enabled は true / false で指定してください")
    for k in ("model", "review_model"):
        if k in body and body[k] not in AI_MODELS:
            raise HTTPException(422, f"未対応のモデルです：{body[k]}")
    ai.save_settings(body)
    return get_ai_settings()


@app.post("/api/ai/test")
def test_ai():
    _require_ai()
    schema = {"type": "object", "additionalProperties": False, "required": ["reply"], "properties": {"reply": {"type": "string"}}}
    data, usage = _ai_call(lambda: ai.call_json(ai.settings()["model"], "接続確認です。", "「接続OK」とだけ返してください。", schema, "ping"))
    return {"reply": data["reply"], "usage": usage}


@app.post("/api/projects/{pid}/documents/{did}/ai")
def ai_read_document(pid: str, did: str, force: bool = Query(False), x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    _require_ai()
    p = _get(pid)
    doc = next((d for d in p["documents"] if d["id"] == did), None)
    if not doc:
        raise HTTPException(404, "資料が見つかりません")
    parsed = storage.load_parsed(pid, did)
    if parsed is None:
        if not _is_scan(doc):
            raise HTTPException(409, "この資料は読み取れる文字がないため AI 読解の対象外です")
        path = storage.project_dir(pid) / "files" / f"{did}{doc['ext']}"
        res = _ai_call(lambda: ai.ocr_document(p, doc, path, force=force))
    else:
        res = _ai_call(lambda: ai.extract_document(p, doc, parsed, storage.load_master("dictionary"), force=force))
    if not res.get("cached"):
        p2 = _get(pid)
        st = res["stats"]
        detail = (f"{doc['filename']}：文字 {st['lines']}行・寸法 {st['dimensions']}件（照合で除外 {st['rejected']}）" if res.get("kind") == "ocr" else
                  f"{doc['filename']}：項目 {st['fields']}・機器 {st['components']}・訂正 {st['corrections']}（根拠検証で除外 {st['rejected']}）")
        storage.add_history(p2, _user(x_user), "AI-OCR" if res.get("kind") == "ocr" else "AI 読解",
                            f"{detail}／{res['usage']['model']}・{res['usage']['seconds']}秒")
        if p2.get("analysis"):
            p2["analysis_stale"] = True
        storage.save_project(p2)
    return {k: res.get(k) for k in ("stats", "usage", "cached", "model", "at", "kind")}


@app.post("/api/projects/{pid}/ai/ask")
def ai_ask(pid: str, body: dict = Body(...), x_user: str | None = Header(None)):
    _require_ai()
    p = _get(pid)
    q = _text(body.get("question"), "質問", required=True, max_len=1000)
    docs = [d for d in p["documents"] if d["status"] != "error" and d.get("include", True)
            and (d.get("text_layer", True) or (_is_scan(d) and (storage.load_ai(pid, d["id"]) or {}).get("kind") == "ocr"))]
    if not docs:
        raise HTTPException(409, "質問の根拠にできる資料がありません。文字を含む資料を登録してください。")
    res = _ai_call(lambda: ai.ask(p, docs, q, p.get("chat", [])))
    p = _get(pid)  # AI の応答待ちの間に行われた操作を上書きしないよう、最新の案件に追記する
    chat = p.setdefault("chat", [])
    chat.append({"role": "user", "content": q, "at": storage.now_iso(), "user": _user(x_user)})
    chat.append({"role": "assistant", "content": res["answer"], "citations": res["citations"], "unverified": res["unverified"],
                 "usage": res["usage"], "at": storage.now_iso()})
    p["chat"] = chat[-40:]
    storage.save_project(p)
    return _view(p)


@app.delete("/api/projects/{pid}/ai/chat")
def ai_chat_clear(pid: str):
    p = _get(pid)
    p["chat"] = []
    return _save(p)


@app.post("/api/projects/{pid}/ai/review")
def ai_review(pid: str, x_user: str | None = Header(None)):
    _perm(x_user, "edit")
    _require_ai()
    p = _get(pid)
    if not p.get("analysis"):
        raise HTTPException(409, "解析結果がありません")
    review = _ai_call(lambda: ai.review(p))
    p = _get(pid)  # レビュー中（数十秒）の操作を上書きしない
    p["ai_review"] = review
    storage.add_history(p, _user(x_user), "AI 設計レビュー", f"指摘 {len(p['ai_review']['findings'])}件（{p['ai_review']['usage']['model']}）")
    return _save(p)


@app.post("/api/projects/{pid}/ai/email")
def ai_email(pid: str, body: dict = Body(default={}), x_user: str | None = Header(None)):
    _perm(x_user, "export")
    _require_ai()
    p = _get(pid)
    if not p.get("analysis"):
        raise HTTPException(409, "解析結果がありません")
    kind = body.get("kind", "quote")
    if kind not in ("quote", "questions"):
        raise HTTPException(422, "不正な種類です")
    res = _ai_call(lambda: ai.draft_email(p, kind, _user(x_user)))
    p = _get(pid)
    storage.add_history(p, _user(x_user), "AI メール文案", {"quote": "見積提出メール", "questions": "質疑確認メール"}[kind])
    storage.save_project(p)
    return res


# ---------- 出力 ----------

def _download(path: Path, media: str):
    return FileResponse(path, media_type=media, filename=path.name,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(path.name)}"})


@app.get("/api/projects/{pid}/export/{kind}")
def export(pid: str, kind: str, force: bool = Query(False), x_user: str | None = Header(None)):
    p = _get(pid)
    approved = (p.get("approval") or {}).get("status") == "approved"
    user = _perm(x_user, "export" if approved or kind not in ("estimate", "estimate-pdf", "sales-csv", "purchase-csv") else "draft")
    a = p.get("analysis")
    if not a:
        raise HTTPException(409, "解析結果がありません")
    out = storage.project_dir(pid) / "exports"
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if kind in ("estimate", "estimate-pdf"):
        try:
            path = exports.export_estimate(p, a, out, force=force)
        except exports.ExportBlocked as e:
            return JSONResponse(status_code=409, content={
                "detail": "未解決の要確認事項があります", "blocking": [{"title": i["title"], "detail": i["detail"]} for i in e.items]})
        except ValueError as e:
            raise HTTPException(422, str(e))
        if kind == "estimate-pdf":
            try:
                pdf = exports.to_pdf(path)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(503, f"PDF変換に失敗しました：{e}")
            return FileResponse(pdf, media_type="application/pdf")
        if (p.get("approval") or {}).get("status") == "approved":
            p["exported_at"] = storage.now_iso()
        storage.add_history(p, user, "見積書出力", path.name + ("（注意書き付き）" if force else ""))
        storage.save_project(p)
        return _download(path, xlsx)
    if kind == "questions":
        path = exports.export_questions(p, a, out)
        storage.add_history(p, user, "質疑書出力", f"{len(a['questions'])}件")
        storage.save_project(p)
        return _download(path, xlsx)
    if kind == "basis":
        path = exports.export_basis(p, a, out)
        storage.add_history(p, user, "見積根拠書出力", path.name)
        storage.save_project(p)
        return _download(path, xlsx)
    if kind in ("sales-csv", "purchase-csv"):
        if [i for i in a["issues"] if i.get("blocking")]:
            raise HTTPException(409, "未解決の要確認事項があるため、他システムへの連携データは出力できません")
        fn = exports.export_sales_csv if kind == "sales-csv" else exports.export_purchase_csv
        path = fn(p, a, out)
        storage.add_history(p, user, "連携CSV出力", path.name + ("" if approved else "（未承認）"))
        storage.save_project(p)
        return _download(path, "text/csv; charset=utf-8")
    raise HTTPException(404)


# ---------- マスタ ----------

@app.get("/api/master/cellmap")
def get_cellmap():
    return json.loads(CELLMAP.read_text(encoding="utf-8"))


@app.get("/api/master/{name}")
def get_master(name: str):
    if name not in MASTER_NAMES | MASTER_READONLY:
        raise HTTPException(404)
    return storage.load_master(name)


def _is_num(v, positive=False, allow_none=False):
    if v is None:
        return allow_none
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return False
    return v > 0 if positive else v >= 0


def _validate_master(name: str, body):
    """壊れたマスタが保存されると以後の解析がすべて失敗するため、保存前に形と値を検査する。"""
    def bad(msg):
        raise HTTPException(422, f"マスタの内容が不正です：{msg}")

    if name == "parts":
        if not isinstance(body, list) or not all(isinstance(x, dict) for x in body):
            bad("部品の一覧ではありません")
        seen = set()
        for x in body:
            m = x.get("model")
            if not isinstance(m, str) or not m.strip() or m in seen:
                bad(f"型式が空または重複しています（{m}）")
            seen.add(m)
            if not isinstance(x.get("name"), str):
                bad(f"{m}：品名がありません")
            if not _is_num(x.get("price"), allow_none=True):
                bad(f"{m}：単価は0以上の数値にしてください")
            for k in ("w", "h", "d", "heat_w"):
                if not _is_num(x.get(k), allow_none=True):
                    bad(f"{m}：{k} は0以上の数値にしてください")
    elif name == "enclosures":
        if not isinstance(body, list) or not body or not all(isinstance(x, dict) for x in body):
            bad("筐体の一覧ではありません")
        for x in body:
            if not isinstance(x.get("id"), str) or not x["id"]:
                bad("筐体 ID がありません")
            for k in ("w", "h", "d", "plate_w", "plate_h"):
                if not _is_num(x.get(k), positive=True):
                    bad(f"{x['id']}：{k} は正の数値にしてください")
            if not _is_num(x.get("price"), allow_none=True):
                bad(f"{x['id']}：単価は0以上の数値にしてください")
    else:
        cur = storage.load_master(name)
        if not isinstance(body, dict):
            bad("形式が違います")
        for k, v in cur.items():
            if k not in body or type(body[k]) is not type(v):
                bad(f"「{k}」がないか、形式が違います")
        if name == "rules":
            for g, items in cur.items():
                if not isinstance(items, dict):
                    continue
                for k in items:
                    if not _is_num(body[g].get(k)):
                        bad(f"{g}.{k} は0以上の数値にしてください")
            for g, k in (("thermal", "k"), ("cost", "round_unit"), ("layout", "max_occupancy"), ("thermal", "airflow_factor")):
                if not _is_num(body[g][k], positive=True):
                    bad(f"{g}.{k} は正の数値にしてください")
            if body["cost"]["default_margin"] >= 1 or body["layout"]["max_occupancy"] > 1:
                bad("利益率・占有率は1未満にしてください")
            if body.get("conflict_policy") not in ("newer", "main"):
                bad("仮採用ルールが不正です")
            m = body.get("market") or {}
            for k in ("steel_index_base", "usd_jpy_base", "steel_index", "usd_jpy"):
                if k in m and not _is_num(m[k], positive=True):
                    bad(f"market.{k} は正の数値にしてください")
            for k in ("steel_share", "import_share"):
                if k in m and m[k] > 1:
                    bad(f"market.{k}（市況に連動する割合）は 0〜1 にしてください")
            if "effect" in body and not _is_num(body["effect"].get("baseline_hours"), positive=True):
                bad("effect.baseline_hours は正の数値にしてください")


def _project_lock(pid: str) -> threading.Lock:
    with _locks_guard:
        return _project_locks.setdefault(pid, threading.Lock())


def _recompute_affected(user: str, reason: str) -> list[dict]:
    """マスタ変更後、結果が変わる案件だけを再計算して保存する。承認済み・承認待ちの見積は変えない（影響確認で知らせる）。"""
    out = []
    for s in storage.list_projects():
        if not s.get("analysis") or s.get("analysis_stale") or (s.get("approval") or {}).get("status") in ("approved", "requested"):
            continue
        with _project_lock(s["id"]):
            p = storage.load_project(s["id"])
            if not p or not p.get("analysis"):
                continue
            before = impact._digest(p["analysis"])
            new = analyze(p)
            changes = impact._changes(before, impact._digest(new))
            if not changes:
                continue
            p["analysis"] = new
            storage.add_history(p, user, "マスタ変更による再計算", f"{reason}：" + "・".join(
                f"{c['label']} {c['a']:,}→{c['b']:,}" if isinstance(c["a"], int) and isinstance(c["b"], int) else f"{c['label']} {c['a']}→{c['b']}"
                for c in changes))
            try:
                storage.save_project(p)
            except storage.Conflict:
                continue  # 同時に担当者が更新した案件は、その担当者の次の操作で再計算される
            out.append({"id": p["id"], "quote_no": p["quote_no"], "name": p["name"]})
    return out


def _save_master(name: str, data, user: str, summary: str | None = None, recompute: bool = False) -> dict:
    """マスタを保存し、版を記録する（初回は変更前の内容も第1版として残す）。"""
    before = storage.load_master(name)
    if not storage.list_master_versions(name):
        storage.add_master_version(name, before, "初期データ", "初期データ")
    storage.save_master(name, data)
    v = storage.add_master_version(name, data, user, summary or impact.diff_master(name, before, data))
    done = _recompute_affected(user, f"{MASTER_JA[name]}の変更（第{v}版）") if recompute else []
    return {"ok": True, "by": user, "version": v, "recomputed": done}


@app.put("/api/master/{name}")
def put_master(name: str, body=Body(...), recompute: bool = Query(False), x_user: str | None = Header(None)):
    user = _perm(x_user, "master")
    if name not in MASTER_NAMES:
        raise HTTPException(404)
    _validate_master(name, body)
    return _save_master(name, body, user, recompute=recompute)


@app.post("/api/master/{name}/impact")
def master_impact(name: str, body=Body(...), x_user: str | None = Header(None)):
    """保存前のマスタで全案件を再解析し、判定・金額が変わる案件を示す（C13）。保存はしない。"""
    _perm(x_user, "master")
    if name not in MASTER_NAMES:
        raise HTTPException(404)
    _validate_master(name, body)
    res = impact.preview(storage.list_projects(), {name: body})
    res["summary"] = impact.diff_master(name, storage.load_master(name), body)
    return res


@app.get("/api/master/{name}/versions")
def master_versions(name: str):
    if name not in MASTER_NAMES:
        raise HTTPException(404)
    return storage.list_master_versions(name)


@app.post("/api/master/{name}/versions/{version}/restore")
def restore_master(name: str, version: int, recompute: bool = Query(False), x_user: str | None = Header(None)):
    user = _perm(x_user, "master")
    if name not in MASTER_NAMES:
        raise HTTPException(404)
    data = storage.load_master_version(name, version)
    if data is None:
        raise HTTPException(404, f"第{version}版が見つかりません")
    _validate_master(name, data)
    return _save_master(name, data, user, summary=f"第{version}版に戻す", recompute=recompute)


# ---------- 修正履歴からの改善候補（F7） ----------

def _learning_state() -> dict:
    try:
        return storage.load_master("learning")
    except (OSError, ValueError):
        return {"applied": [], "dismissed": []}


def _candidates() -> dict:
    return learning.candidates(storage.list_projects(), storage.load_master("dictionary"), storage.load_master("parts"),
                               _learning_state())


@app.get("/api/learning")
def learning_candidates():
    return _candidates()


@app.post("/api/learning/{cid}/{action}")
def learning_decide(cid: str, action: str, x_user: str | None = Header(None)):
    user = _perm(x_user, "master")
    if action not in ("apply", "dismiss"):
        raise HTTPException(404)
    c = next((x for x in _candidates()["items"] if x["id"] == cid), None)
    if not c:
        raise HTTPException(404, "候補が見つかりません（判断済みか、対象の修正が取り消されています）")
    state = _learning_state()
    res = {"ok": True}
    if action == "apply":
        dic, parts = storage.load_master("dictionary"), storage.load_master("parts")
        try:
            name = learning.apply(c, dic, parts)
        except ValueError as e:
            raise HTTPException(409, str(e))
        res = _save_master(name, dic if name == "dictionary" else parts, user, summary=f"改善候補を反映：{c['title']}")
        res["master"] = name
    state.setdefault("applied" if action == "apply" else "dismissed", []).append(
        {"id": cid, "at": storage.now_iso(), "by": user, "title": c["title"], "kind": c["kind"]})
    storage.save_master("learning", state)
    return res


@app.get("/api/samples/{name}")
def sample_file(name: str):
    path = SAMPLES / Path(name).name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, filename=path.name)


# ---------- フロントエンド ----------

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404, "API が見つかりません")
        target = (FRONTEND_DIST / full_path).resolve()
        # frontend/dist の外（../.env など）は配信しない
        if full_path and target.is_relative_to(FRONTEND_DIST.resolve()) and target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")

