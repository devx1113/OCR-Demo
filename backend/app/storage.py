"""案件・マスタの永続化。

環境変数 DATABASE_URL があれば PostgreSQL（Prisma、storage_db.py）に、なければ JSON ファイルに保存する。
どちらの場合も、取り込んだ資料ファイルと出力した Excel は PROJECTS 配下（Docker ではボリューム）に置く。
"""
import json
import os
import re
import shutil
import threading
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from .config import MASTER, PROJECTS

_lock = threading.RLock()

# 現在のリクエストの担当者（API の入口で設定）。案件を保存した人を記録し、同時編集の検知に使う
current_user: ContextVar[str] = ContextVar("current_user", default="")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    tmp.replace(path)


# ---------- マスタ ----------

def load_master(name: str):
    with _lock:
        return _read(MASTER / f"{name}.json")


def save_master(name: str, data):
    with _lock:
        _write(MASTER / f"{name}.json", data)


MASTER_VERSIONS_KEEP = 30


def _versions_file(name: str) -> Path:
    return MASTER / "_versions" / f"{name}.json"


def add_master_version(name: str, data, by: str, summary: str) -> int:
    """マスタの版を記録する（新しい順・最大 MASTER_VERSIONS_KEEP 件）。"""
    with _lock:
        f = _versions_file(name)
        f.parent.mkdir(exist_ok=True)
        vs = _read(f) if f.exists() else []
        n = (vs[0]["version"] if vs else 0) + 1
        vs.insert(0, {"version": n, "at": now_iso(), "by": by, "summary": summary, "data": data})
        _write(f, vs[:MASTER_VERSIONS_KEEP])
        return n


def list_master_versions(name: str) -> list[dict]:
    with _lock:
        f = _versions_file(name)
        return [{k: v[k] for k in ("version", "at", "by", "summary")} for v in (_read(f) if f.exists() else [])]


def load_master_version(name: str, version: int):
    with _lock:
        f = _versions_file(name)
        return next((v["data"] for v in (_read(f) if f.exists() else []) if v["version"] == version), None)


# ---------- 案件 ----------

_ID = re.compile(r"[0-9a-f]{12}")


class InvalidId(ValueError):
    pass


class Conflict(Exception):
    """読み込んだ後に他の担当者が案件を保存していた（楽観的排他制御）。"""

    def __init__(self, modified_by: str, updated_at: str | None):
        super().__init__(modified_by)
        self.modified_by = modified_by
        self.updated_at = updated_at


def project_dir(pid: str) -> Path:
    if not _ID.fullmatch(pid or ""):
        raise InvalidId(pid)
    return PROJECTS / pid


def list_projects(history: bool = True) -> list[dict]:  # noqa: ARG001 — ファイル保存では常に履歴を含む
    out = []
    with _lock:
        for d in PROJECTS.iterdir():
            f = d / "project.json"
            if f.exists():
                try:
                    out.append(_read(f))
                except (OSError, ValueError):  # 壊れた案件ファイルで一覧全体を止めない
                    continue
    return sorted(out, key=lambda p: (p["created_at"], p.get("quote_no", "")), reverse=True)


def load_project(pid: str) -> dict | None:
    f = project_dir(pid) / "project.json"
    with _lock:
        return _read(f) if f.exists() else None


def save_project(project: dict):
    project["updated_at"] = now_iso()
    project["rev"] = int(project.get("rev") or 0) + 1
    project["modified_by"] = current_user.get() or project.get("modified_by") or ""
    d = project_dir(project["id"])
    (d / "files").mkdir(parents=True, exist_ok=True)
    (d / "parsed").mkdir(exist_ok=True)
    with _lock:
        _write(d / "project.json", project)


def project_rev(pid: str) -> dict | None:
    p = load_project(pid)
    return {"rev": int(p.get("rev") or 0), "modified_by": p.get("modified_by") or "", "updated_at": p.get("updated_at")} if p else None


def strip_internal(p: dict) -> dict:
    return p


def delete_project(pid: str):
    with _lock:
        shutil.rmtree(project_dir(pid), ignore_errors=True)


def next_quote_no() -> str:
    year = datetime.now().year
    nums = []
    for p in list_projects():
        q = p.get("quote_no", "")
        if q.startswith(f"Q{year}-"):
            try:
                nums.append(int(q.split("-")[1]))
            except ValueError:
                pass
    return f"Q{year}-{(max(nums) + 1) if nums else 1:04d}"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _doc_id(doc_id: str) -> str:
    if not _ID.fullmatch(doc_id or ""):
        raise InvalidId(doc_id)
    return doc_id


def save_parsed(pid: str, doc_id: str, parsed: dict):
    _doc_id(doc_id)
    with _lock:
        _write(project_dir(pid) / "parsed" / f"{doc_id}.json", parsed)


def load_parsed(pid: str, doc_id: str) -> dict | None:
    _doc_id(doc_id)
    f = project_dir(pid) / "parsed" / f"{doc_id}.json"
    with _lock:
        return _read(f) if f.exists() else None


def save_ai(pid: str, doc_id: str, data: dict):
    _doc_id(doc_id)
    d = project_dir(pid) / "ai"
    d.mkdir(parents=True, exist_ok=True)
    with _lock:
        _write(d / f"{doc_id}.json", data)


def load_ai(pid: str, doc_id: str) -> dict | None:
    _doc_id(doc_id)
    f = project_dir(pid) / "ai" / f"{doc_id}.json"
    with _lock:
        return _read(f) if f.exists() else None


def add_history(project: dict, user: str, action: str, detail: str = ""):
    project.setdefault("history", []).insert(0, {
        "at": now_iso(), "user": user, "action": action, "detail": detail,
    })


# ---------- 保存先の切り替え ----------

BACKEND = "db" if os.environ.get("DATABASE_URL") else "files"

if BACKEND == "db":
    from . import storage_db as _db

    load_master, save_master = _db.load_master, _db.save_master
    add_master_version, list_master_versions, load_master_version = _db.add_master_version, _db.list_master_versions, _db.load_master_version
    list_projects, load_project, save_project, project_rev = _db.list_projects, _db.load_project, _db.save_project, _db.project_rev
    _delete_rows, next_quote_no = _db.delete_project, _db.next_quote_no
    save_parsed, load_parsed, save_ai, load_ai = _db.save_parsed, _db.load_parsed, _db.save_ai, _db.load_ai
    strip_internal = _db.strip_internal

    def delete_project(pid: str):  # noqa: F811 — DB の行と、ボリューム上のファイルの両方を消す
        _delete_rows(pid)
        with _lock:
            shutil.rmtree(project_dir(pid), ignore_errors=True)
