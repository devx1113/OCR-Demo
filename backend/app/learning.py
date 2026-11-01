"""修正履歴を使った辞書・マスタの改善候補（F7）。

担当者が各案件で行った修正（型式の訂正・AI だけが読んだ値の確定・機器の手動追加・値の修正）を集計し、
変換辞書・部品マスタへの追加候補として提示する。修正を自動で反映することはせず、
マスタ権限のある担当者が内容を確認して「反映」したものだけを辞書・マスタに加える（反映したら版を記録）。
"""
import hashlib
import re

from .normalize import label_key, match_model, nfkc, normalize_model, strip_paren

KIND_JA = {"part_alias": "型式の別表記", "name_alias": "機器名称の別表記", "field_alias": "項目名の別表記",
           "unregistered": "部品マスタ未登録", "frequent_edit": "修正が多い項目"}


def _cid(*xs) -> str:
    return hashlib.sha1("|".join(map(str, xs)).encode()).hexdigest()[:12]


def _label_from_source(text: str) -> str | None:
    """根拠の行から項目名を取り出す（「保護構造：IP4X」「保護構造 | IP4X」の左側）。"""
    t = nfkc(text or "").strip()
    if " | " in t:
        head = t.split(" | ", 1)[0].strip()
    else:
        m = re.match(r"^[\s・●○■□\-\d.()（）]*([^:：|]{2,16}?)\s*[:：]", t)
        head = m.group(1).strip() if m else None
    if not head or len(head) > 16 or re.search(r"\d", head):  # 日付・番号などは項目名ではない
        return None
    return head


def candidates(projects: list[dict], dic: dict, parts: list[dict], state: dict) -> dict:
    """未判断の候補（items）と、これまでの判断の記録（decisions：反映・見送り）を返す。
    反映した候補は辞書・マスタに入るため、次からは候補として出てこない。"""
    decided = {x["id"] for k in ("applied", "dismissed") for x in state.get(k, [])}
    by_model = {p["model"]: p for p in parts}
    found: dict[str, dict] = {}

    def add(cid, base, project, example):
        c = found.setdefault(cid, {**base, "id": cid, "projects": [], "examples": []})
        if project["id"] not in {p["id"] for p in c["projects"]}:
            c["projects"].append({"id": project["id"], "quote_no": project["quote_no"], "name": project["name"]})
        if example and example not in c["examples"] and len(c["examples"]) < 3:
            c["examples"].append(example)

    field_aliases = {f["key"]: {label_key(a) for a in [f["label"], *f.get("aliases", [])]} for f in dic["fields"]}
    name_aliases = {label_key(a) for k, v in dic["component_names"].items() for a in [k, *v]}
    edits: dict[str, dict] = {}

    for p in projects:
        a = p.get("analysis")
        if not a:
            continue
        overrides = p.get("component_overrides") or {}
        for c in a["components"]:
            if c.get("deleted"):
                continue
            o = overrides.get(c["key"]) or {}
            raw = normalize_model(c.get("raw_model") or "")
            part = by_model.get(c.get("model") or "")
            # 1) 資料の型式表記を担当者が正しい型式に直した → 部品マスタの別名に追加
            if o.get("model") and part and raw and raw != part["model"] and raw not in part.get("aliases", []):
                m = match_model(raw, parts)
                if not m or m["kind"] == "fuzzy":
                    add(_cid("part_alias", part["model"], raw),
                        {"kind": "part_alias", "target": part["model"], "value": raw,
                         "title": f"「{raw}」を {part['model']}（{part['name']}）の別表記に追加",
                         "effect": f"次回から資料に「{raw}」とあれば {part['model']} として部品マスタと照合します",
                         "applicable": True}, p, f"{c['name']}：{c.get('raw_model')} → {o['model']}（{o.get('by', '')}）")
            # 2) 型式で照合できたが名称が辞書にない → 機器名称の別表記に追加
            base, _ = strip_paren(c.get("raw_name") or "")
            if part and c.get("in_master") and base and not c.get("aliased") and label_key(base) not in name_aliases \
                    and label_key(base) != label_key(part["name"]) and c.get("origin") != "manual":
                add(_cid("name_alias", part["name"], base),
                    {"kind": "name_alias", "target": part["name"], "value": base,
                     "title": f"「{base}」を機器名称「{part['name']}」の別表記に追加",
                     "effect": f"次回から「{base}」を「{part['name']}」に統一して表示・集計します", "applicable": True},
                    p, f"{c.get('raw_name')}（型式 {c.get('model')}）")
            # 4) マスタにない型式（担当者の手動追加を含む） → 部品マスタへの登録を促す
            if c.get("status") == "no_master" and c.get("model") and not c.get("candidate"):
                add(_cid("unregistered", c["model"]),
                    {"kind": "unregistered", "target": c["model"], "value": c["name"],
                     "title": f"{c['model']}（{c['name']}）を部品マスタに登録",
                     "effect": "寸法・発熱・単価を登録すると、収容判定と見積で「要見積」にならなくなります",
                     "applicable": False}, p, f"{c['name']} {c['model']} × {c.get('qty')}（{c.get('doc_name')}）")

        for f in a["fields"]:
            # 3) AI だけが読んだ値を担当者が確定 → その行の項目名をルール辞書に追加（次回から AI なしでも抽出）
            if f.get("methods") == ["ai"] and f["status"] == "confirmed" and f.get("sources"):
                label = _label_from_source(f["sources"][0].get("text", ""))
                if label and label_key(label) not in field_aliases.get(f["key"], set()):
                    add(_cid("field_alias", f["key"], label),
                        {"kind": "field_alias", "target": f["key"], "target_label": f["label"], "value": label,
                         "title": f"「{label}」を項目「{f['label']}」の別表記に追加",
                         "effect": "次回から AI を使わなくても、ルール抽出でこの項目を読み取れます", "applicable": True},
                        p, f"{f['sources'][0].get('doc_name', '')}：{f['sources'][0].get('text', '')[:60]}")
            # 5) 抽出値を担当者が修正した項目を集計 → 抽出ルールの見直し候補
            if f["status"] == "edited" and f.get("original"):
                e = edits.setdefault(f["key"], {"label": f["label"], "items": []})
                e["items"].append((p, f"{p['quote_no']}：「{f.get('original')}」→「{f['value']}」"))

    for key, e in edits.items():
        if len({p["id"] for p, _ in e["items"]}) < 2:
            continue
        cid = _cid("frequent_edit", key, len(e["items"]))
        for p, ex in e["items"]:
            add(cid, {"kind": "frequent_edit", "target": key, "value": e["label"],
                      "title": f"「{e['label']}」は {len({p['id'] for p, _ in e['items']})} 案件で抽出値が修正されています",
                      "effect": "抽出ルール・項目名の別表記・値の書式の見直しを検討してください（自動では変更しません）",
                      "applicable": False}, p, ex)

    items = []
    for c in found.values():
        if c["id"] in decided:
            continue
        c["kind_ja"] = KIND_JA[c["kind"]]
        c["count"] = len(c["projects"])
        items.append(c)
    items.sort(key=lambda c: (not c["applicable"], -c["count"], c["title"]))
    decisions = sorted([{**x, "action": k} for k in ("applied", "dismissed") for x in state.get(k, [])],
                       key=lambda x: x.get("at") or "", reverse=True)
    return {"items": items, "open": len(items), "applied": len(state.get("applied", [])), "decisions": decisions}


def apply(c: dict, dic: dict, parts: list[dict]) -> str:
    """候補を辞書・マスタに反映し、変更したマスタ名を返す（dic・parts を書き換える）。"""
    if c["kind"] == "part_alias":
        part = next((p for p in parts if p["model"] == c["target"]), None)
        if not part:
            raise ValueError("部品マスタに対象の型式がありません")
        if c["value"] not in part.setdefault("aliases", []):
            part["aliases"].append(c["value"])
        return "parts"
    if c["kind"] == "name_alias":
        lst = dic["component_names"].setdefault(c["target"], [])
        if c["value"] not in lst:
            lst.append(c["value"])
        return "dictionary"
    if c["kind"] == "field_alias":
        f = next((f for f in dic["fields"] if f["key"] == c["target"]), None)
        if not f:
            raise ValueError("対象の項目がありません")
        if c["value"] not in f["aliases"]:
            f["aliases"].append(c["value"])
        return "dictionary"
    raise ValueError("この候補は自動で反映できません（内容を確認して、マスタ・ルールを直接更新してください）")
