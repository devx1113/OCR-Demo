"""JSON ファイルで保存していた案件を、データベース（PostgreSQL）へ取り込む。元のファイルは読むだけで変更しない。

    python -m app.import_json <案件フォルダ>      例：python -m app.import_json /import

<案件フォルダ>/<案件ID>/project.json・parsed/・ai/・files/・exports/ を読み、
案件・資料・履歴・構造化結果・AI 結果を DB に登録し、ファイルは保存先（PROJECTS）へコピーする。
同じ案件 ID・見積番号が既にあれば取り込まない（何度実行しても重複しない）。
"""
import json
import shutil
import sys
from pathlib import Path

from . import storage


def import_dir(src: Path) -> tuple[list[str], list[str]]:
    if storage.BACKEND != "db":
        raise SystemExit("DATABASE_URL が設定されていません（取り込み先のデータベースを指定してください）")
    from . import storage_db
    c = storage_db.db()
    done, skipped = [], []
    for d in sorted(p for p in src.iterdir() if (p / "project.json").exists()):
        p = json.loads((d / "project.json").read_text(encoding="utf-8"))
        pid = p["id"]
        if c.project.find_unique(where={"id": pid}) or c.project.find_unique(where={"quoteNo": p["quote_no"]}):
            skipped.append(f"{p['quote_no']} {p['name']}（登録済み）")
            continue
        for x in ("parsed", "ai"):
            for f in sorted((d / x).glob("*.json")) if (d / x).exists() else []:
                data = json.loads(f.read_text(encoding="utf-8"))
                (storage.save_parsed if x == "parsed" else storage.save_ai)(pid, f.stem, data)
        updated, by = p.get("updated_at"), p.get("modified_by") or (p.get("history") or [{}])[0].get("user", "")
        p.pop("rev", None)
        storage.current_user.set(by)
        storage.save_project(p)
        if updated:  # 取り込みで更新日時が変わらないよう、元の値に戻す
            c.project.update(where={"id": pid}, data={"updatedAt": storage_db._to_dt(updated)})
        for sub in ("files", "exports"):
            if (d / sub).exists():
                shutil.copytree(d / sub, storage.project_dir(pid) / sub, dirs_exist_ok=True)
        done.append(f"{p['quote_no']} {p['name']}（資料 {len(p['documents'])} 件・履歴 {len(p.get('history', []))} 件）")
    return done, skipped


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    done, skipped = import_dir(Path(sys.argv[1]))
    for x in done:
        print("取り込み：", x)
    for x in skipped:
        print("スキップ：", x)
    print(f"完了：{len(done)} 件を取り込み、{len(skipped)} 件をスキップしました")


if __name__ == "__main__":
    main()
