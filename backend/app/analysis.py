"""解析パイプライン：資料ごとの抽出 → 資料間の統合（矛盾・変更の反映）→ 担当者の修正を適用
→ マスタ照合 → 収容判定 → 見積 → 要確認一覧・質疑書。

担当者の修正（overrides）は再解析しても失われないよう、抽出結果とは別に保持して毎回最後に適用する。
"""
import time

from . import storage
from .estimate import run_estimate
from .extract import Extractor
from .fit import run_fit
from .normalize import (compare_key, display_value, label_key, match_model, model_key, normalize_component_name,
                        normalize_model, parse_length, parse_qty, parse_value, strip_paren)

FIELD_OK = {"ok", "confirmed", "edited", "resolved", "changed"}


MASTER_KEYS = ("dictionary", "parts", "rules", "enclosures")


def _masters(override: dict | None = None):
    """解析に使うマスタ。override は変更前の影響確認用（保存前のマスタで再解析する）。"""
    override = override or {}
    return tuple(override[k] if k in override else storage.load_master(k) for k in MASTER_KEYS)


def _ordered_docs(project):
    docs = [d for d in project["documents"] if d["status"] != "error" and d.get("text_layer", True) and d.get("include", True)]
    rank = {"main": 0, "supplement": 1, "drawing": 2, "other": 3}
    return sorted(docs, key=lambda d: (rank.get(d.get("role"), 9), d.get("received_date") or "", d["uploaded_at"]))


# ---------- ルール抽出と AI 読解の突き合わせ ----------

def combine_ai(ex: Extractor, res: dict, ai_res: dict | None):
    """同じ資料について、ルール抽出の候補と AI 読解（根拠検証済み）の候補を突き合わせる。"""
    for c in res["fields"]:
        c.setdefault("method", "rule")
    if not ai_res:
        return
    by_key: dict[str, list] = {}
    for c in res["fields"]:
        by_key.setdefault(c["key"], []).append(c)
    for a in ai_res.get("fields", []):
        f = ex.fields.get(a["key"])
        if not f or not a.get("verified") or not a.get("source"):
            continue
        cand = ex.field_candidate(f, a["value"], 0.86, a["source"])
        if f["type"] != "text" and cand["parsed"] in (None, "", []):
            continue  # 項目の型として解釈できない値（例：設置場所に地名）は採用しない
        cand.update(method="ai", ai_quote=a.get("quote", ""))
        rules = by_key.get(a["key"], [])
        same = [r for r in rules if r["cmp"] == cand["cmp"]]
        if same:
            for r in same:
                r["method"] = "rule+ai"
                r["confidence"] = max(r["confidence"], 0.99)
            continue
        same_place = [r for r in rules if set(r["source"]["ids"]) & set(a["source"]["ids"])]
        if same_place:
            for r in same_place:
                r.setdefault("ai_alt", []).append({"value": cand["display"], "source": a["source"]})
            continue
        res["fields"].append(cand)
        by_key.setdefault(a["key"], []).append(cand)


# ---------- 項目の統合 ----------

def merge_fields(dic, docs, per_doc, policy):
    fields = {}
    for f in dic["fields"]:
        cands = []
        for d in docs:
            for c in per_doc[d["id"]]["fields"]:
                if c["key"] == f["key"]:
                    cands.append({**c, "doc_id": d["id"], "doc_name": d["filename"], "doc_role": d["role"],
                                  "doc_date": d.get("received_date") or ""})
        item = {"key": f["key"], "label": f["label"], "group": f["group"], "type": f["type"],
                "required": f["required"], "options": f.get("options"), "value": "", "parsed": None, "raw": "",
                "status": "missing" if f["required"] else "empty", "confidence": 0.0,
                "sources": [], "candidates": [], "change": None, "note": "", "history": [], "methods": [], "ai_alt": []}
        ai_ref: list[dict] = []
        if cands:
            item["methods"] = sorted({c.get("method", "rule") for c in cands})
            distinct = {}
            for c in cands:
                distinct.setdefault(c["cmp"], []).append(c)
            # AI だけが拾った短い言い換え（例：「1回」と「1回（発注者立会）」）は、包含する値の裏付けとして扱う
            for cmp in [k for k, cs in distinct.items() if all(c.get("method") == "ai" for c in cs)]:
                host = next((k for k in distinct if k != cmp and f["type"] in ("text", "list") and cmp and cmp in k), None)
                if host:
                    for c in distinct.pop(cmp):
                        c["method"] = "ai-support"
                        distinct[host].append(c)
            # AI だけが読んだ値が、ルールで抽出した値と食い違う場合は「矛盾」にせず参考値として添える
            # （LLM の読み違いで承認を止めないため。案件名・発注者は表題や宛先の誤読が多いため参考値にもしない）
            if any(any("rule" in c.get("method", "rule") for c in cs) for cs in distinct.values()):
                for cmp in [k for k, cs in distinct.items() if all(c.get("method") == "ai" for c in cs)]:
                    for c in distinct.pop(cmp):
                        if f["group"] != "project":
                            ai_ref.append({"value": c["display"], "source": c["source"]})
            if len(distinct) == 1:
                cands = [c for cs in distinct.values() for c in cs]
                first = cands[0]
                conf = min(0.99, max(c["confidence"] for c in cands) + 0.02 * (len(cands) - 1))
                alts = [x for c in cands for x in c.get("ai_alt", [])] + ai_ref
                ai_only = all(c.get("method") == "ai" for c in cands)
                item.update(value=first["display"], parsed=first["parsed"], raw=first["raw"], confidence=round(conf, 2),
                            sources=[c["source"] for c in cands], ai_alt=alts,
                            status="ok" if conf >= 0.9 and first["parsed"] not in (None, "", []) and not alts else "review")
                if len({c["doc_id"] for c in cands}) > 1:
                    item["note"] = f"{len({c['doc_id'] for c in cands})}資料で一致"
                if item["status"] == "review":
                    if alts:
                        item["note"] = (f"AI が別の記載「{alts[0]['value']}」を検出しました（{alts[0]['source']['doc_name']}）。"
                                        "ルール抽出の値を表示しています")
                    elif ai_only:
                        item["note"] = "AI が本文から読み取った値です（引用が原文に存在することを照合済み）"
                    elif first["parsed"] in (None, "", []):
                        item["note"] = "値を解釈できませんでした"
                    else:
                        item["note"] = "項目名が一部一致のため確認してください"
            else:
                groups = []
                for cmp, cs in distinct.items():
                    groups.append({"value": cs[0]["display"], "parsed": cs[0]["parsed"], "raw": cs[0]["raw"],
                                   "methods": sorted({c.get("method", "rule") for c in cs}),
                                   "sources": [c["source"] for c in cs], "doc_name": cs[0]["doc_name"],
                                   "doc_date": max(c["doc_date"] for c in cs), "doc_role": cs[0]["doc_role"]})
                if policy == "newer":
                    pick = max(range(len(groups)), key=lambda i: groups[i]["doc_date"])
                    basis = "受領日が新しい資料を仮採用"
                else:
                    pick = next((i for i, g in enumerate(groups) if g["doc_role"] == "main"), 0)
                    basis = "主仕様書を仮採用"
                g = groups[pick]
                item.update(value=g["value"], parsed=g["parsed"], raw=g["raw"], status="conflict",
                            confidence=0.5, sources=[s for gg in groups for s in gg["sources"]],
                            candidates=groups, provisional=pick, note=f"資料間で値が異なります（{basis}）")
        fields[f["key"]] = item
    return fields


def apply_field_changes(fields, changes):
    unresolved = []
    for ch in changes:
        if ch["kind"] != "field":
            continue
        item = fields.get(ch.get("key"))
        if not item:
            unresolved.append(ch)
            continue
        before_val = item["value"]
        sub = ch.get("sub")
        if item["type"] == "dims" and sub:
            b, a = parse_length(ch["before"]), parse_length(ch["after"])
            cur = (item["parsed"] or {}).get(sub)
            matches = bool(b) and cur == b["mm"]
            if a:
                parsed = dict(item["parsed"] or {})
                parsed[sub] = a["mm"]
                item["parsed"] = parsed
                item["value"] = display_value("dims", parsed, "")
            label = {"w": "幅", "h": "高さ", "d": "奥行"}[sub]
            desc = f"{label} {ch['before']}（{b['mm'] if b else '?'}mm）→ {ch['after']}（{a['mm'] if a else '?'}mm）"
        else:
            bp = parse_value(item["type"], ch["before"])
            matches = compare_key(item["type"], bp, ch["before"]) == compare_key(item["type"], item["parsed"], item["raw"])
            ap = parse_value(item["type"], ch["after"])
            item.update(parsed=ap, raw=ch["after"], value=display_value(item["type"], ap, ch["after"]))
            desc = f"{ch['before']} → {ch['after']}"
        item["change"] = {"from": before_val, "to": item["value"], "desc": desc, "reason": ch.get("reason", ""),
                          "source": ch["source"], "before_matches": matches}
        item["sources"] = item["sources"] + [ch["source"]]
        if item["status"] != "conflict":
            item["status"] = "changed" if matches else "review"
            item["note"] = "変更連絡を反映" if matches else f"変更前の値（{ch['before']}）が現在値（{before_val}）と一致しません"
    return unresolved


def infer_fields(fields):
    loc, ptype = fields.get("location"), fields.get("panel_type")
    if loc and ptype and loc["status"] == "missing" and ptype["value"]:
        for opt in ("屋外", "屋内"):
            if opt in ptype["value"]:
                loc.update(value=opt, parsed=opt, raw=opt, status="inferred", confidence=0.75,
                           sources=list(ptype["sources"]), note=f"形式「{ptype['value']}」から推定")
                break


def apply_field_overrides(fields, overrides):
    for key, o in (overrides or {}).items():
        item = fields.get(key)
        if not item:
            continue
        item["override"] = o
        act = o["action"]
        if act == "edit":
            item["original"] = item["value"]
            parsed = parse_value(item["type"], o["value"])
            item.update(value=display_value(item["type"], parsed, o["value"]), parsed=parsed, raw=o["value"],
                        status="edited", confidence=1.0)
        elif act == "choose" and item["candidates"]:
            g = item["candidates"][min(o["choice"], len(item["candidates"]) - 1)]
            item.update(value=g["value"], parsed=g["parsed"], raw=g["raw"], status="resolved", confidence=1.0, provisional=o["choice"])
        elif act == "confirm":
            item.update(status="confirmed", confidence=1.0)
        elif act == "ask":
            item["status"] = "asked"


# ---------- 構成機器の統合 ----------

def merge_components(dic, docs, per_doc, parts, overrides, extra, ai_by_doc=None):
    names = dic["component_names"]
    comps, by_no, issues = [], {}, []
    for d in docs:
        for r in per_doc[d["id"]]["components"]:
            base, note = strip_paren(r["raw_name"])
            name, aliased = normalize_component_name(r["raw_name"], names)
            key = f"no{r['no']}" if r["no"] is not None else f"{name}-{normalize_model(r['raw_model'])}"
            if key in by_no:
                key = f"{key}-{d['id'][:4]}"
            c = {"key": key, "no": r["no"], "name": name, "raw_name": r["raw_name"], "name_note": note,
                 "aliased": aliased, "raw_model": r["raw_model"], "model": normalize_model(r["raw_model"]),
                 "spec": r["spec"], "qty": r["qty"], "qty_raw": r["qty_raw"], "mount_raw": r["mount_raw"],
                 "mount": r["mount"], "confidence": r["confidence"], "sources": [r["source"]],
                 "origin": "main" if d["role"] == "main" else "added", "doc_name": d["filename"],
                 "changes": [], "notes": []}
            if aliased:
                c["notes"].append(f"名称を正規化：{base} → {name}")
            comps.append(c)
            by_no[key] = c

    for d in docs:
        for ch in per_doc[d["id"]]["changes"]:
            if ch["kind"] != "component":
                continue
            c = by_no.get(f"no{ch['no']}")
            if not c:
                issues.append({"severity": "medium", "type": "change_target", "title": f"変更対象 No.{ch['no']} が見つかりません",
                               "detail": ch["target"], "target": None})
                continue
            if ch["attr"] == "model":
                before, _ = strip_paren(ch["before"])
                after, after_note = strip_paren(ch["after"])
                matches = normalize_model(before).replace(" ", "") == c["model"].replace(" ", "")
                c["changes"].append({"attr": "型式", "from": c["model"], "to": normalize_model(after), "reason": ch["reason"],
                                     "source": ch["source"], "before_matches": matches})
                c.setdefault("prev_models", []).append(c["model"])
                c["model"] = normalize_model(after)
                c["raw_model"] = after
                if after_note:
                    c["spec_changed_hint"] = after_note
            elif ch["attr"] == "qty":
                b, a = parse_qty(ch["before"]), parse_qty(ch["after"])
                matches = bool(b) and b["n"] == c["qty"]
                c["changes"].append({"attr": "数量", "from": c["qty"], "to": a["n"] if a else None, "reason": ch["reason"],
                                     "source": ch["source"], "before_matches": matches})
                if a:
                    c["qty"] = a["n"]
            else:
                c["changes"].append({"attr": "仕様", "from": c["spec"], "to": ch["after"], "reason": ch["reason"],
                                     "source": ch["source"], "before_matches": True})
                c["spec"] = ch["after"]
            c["sources"].append(ch["source"])

    _combine_ai_components(comps, docs, ai_by_doc or {}, names)

    for e in extra or []:
        comps.append({"key": e["key"], "no": None, "name": e["name"], "raw_name": e["name"], "name_note": "", "aliased": False,
                      "raw_model": e.get("model", ""), "model": normalize_model(e.get("model", "")), "spec": e.get("spec", ""),
                      "qty": e.get("qty", 1), "qty_raw": str(e.get("qty", 1)), "mount_raw": "", "mount": e.get("mount"),
                      "confidence": 1.0, "sources": [], "origin": "manual", "doc_name": "手動追加", "changes": [],
                      "notes": [f"{e.get('by', '')} が手動で追加"]})

    for c in comps:
        o = (overrides or {}).get(c["key"])
        if o:
            c["override"] = o
            if o.get("confirmed"):
                c["candidate"] = False
            if o.get("deleted"):
                c["deleted"] = True
            if o.get("model") is not None:
                c["notes"].append(f"型式を修正：{c['model']} → {normalize_model(o['model'])}")
                c["model"] = normalize_model(o["model"])
            if o.get("qty") is not None:
                if o["qty"] != c["qty"]:
                    c["notes"].append(f"数量を修正：{c['qty']} → {o['qty']}")
                c["qty"] = o["qty"]
        _attach_master(c, parts)
        _component_status(c)
    return comps, issues


def _combine_ai_components(comps, docs, ai_by_doc, names):
    """AI が読み取った機器で、ルール抽出の機器を裏付ける。ルールで拾えなかった機器は「AI抽出」として追加する。"""
    keys = {model_key(m) for c in comps for m in [c["model"], *c.get("prev_models", [])] if m}
    labels = {label_key(c["name"]) for c in comps}
    for d in docs:
        ai_res = ai_by_doc.get(d["id"])
        if not ai_res:
            continue
        for i, a in enumerate(ai_res.get("components", [])):
            if not a.get("verified"):
                continue
            mk = model_key(a.get("model") or "")
            name, _ = normalize_component_name(a.get("name") or "", names)
            hit = [c for c in comps if (mk and mk in {model_key(m) for m in [c["model"], *c.get("prev_models", [])]})
                   or (not mk and label_key(c["name"]) == label_key(name))]
            if hit:
                for c in hit:
                    c["ai_verified"] = True
                continue
            if (mk and mk in keys) or (not mk and label_key(name) in labels):
                continue
            comps.append({"key": f"ai-{d['id'][:4]}-{i}", "no": None, "name": name, "raw_name": a.get("name") or "",
                          "name_note": "", "aliased": False, "raw_model": a.get("model") or "",
                          "model": normalize_model(a.get("model") or ""), "spec": a.get("spec") or "",
                          "qty": int(a["qty"]) if isinstance(a.get("qty"), (int, float)) else None, "qty_raw": str(a.get("qty") or ""),
                          "mount_raw": "", "mount": a.get("mount"), "confidence": 0.8, "sources": [a["source"]],
                          "origin": "ai", "doc_name": d["filename"], "changes": [], "candidate": True,
                          "notes": [f"AI が本文から読み取った機器です：「{a.get('quote', '')}」",
                                    "確定するまで収容判定・見積には含めません"]})
            keys.add(mk)
            labels.add(label_key(name))


def _attach_master(c, parts):
    m = match_model(c["model"], parts)
    c["in_master"] = bool(m and m["kind"] != "fuzzy")
    c["master_match"] = None
    if m:
        p = m["part"]
        c["master_match"] = {"model": p["model"], "name": p["name"], "kind": m["kind"], "score": m["score"]}
        if m["kind"] == "normalized" and normalize_model(c["raw_model"]) != p["model"]:
            c["notes"].append(f"型式の表記揺れを補正：{c['raw_model']} → {p['model']}")
        if m["kind"] != "fuzzy":
            c["model"] = p["model"]
            for k in ("w", "h", "d", "heat_w", "price", "price_valid_until", "category", "clearance", "maker", "imported"):
                c[k] = p.get(k)
            if c.get("spec_changed_hint"):
                c["spec"] = p.get("spec", c["spec"])
            c["layout_mount"] = p["mount"]
            if c["mount"] and c["mount"] != p["mount"] and not (c["mount"] == "plate" and p["mount"] == "terminal"):
                c["notes"].append(f"取付位置が仕様書（{c['mount_raw']}）とマスタで異なります")
            return
    c["layout_mount"] = c["mount"]


def _component_status(c):
    if c.get("deleted"):
        c["status"] = "deleted"
    elif (c.get("override") or {}).get("confirmed"):
        c["status"] = "confirmed"
    elif c["origin"] == "ai":
        c["status"] = "ai"
    elif c["master_match"] and c["master_match"]["kind"] == "fuzzy":
        c["status"] = "review"
    elif not c["in_master"]:
        c["status"] = "no_master"
    elif any(not ch["before_matches"] for ch in c["changes"]) or c["qty"] is None:
        c["status"] = "review"
    elif c["changes"]:
        c["status"] = "changed"
    elif c["origin"] == "added":
        c["status"] = "added"
    else:
        c["status"] = "ok"


# ---------- 要確認一覧・質疑・前提条件 ----------

AXIS_JA = {"w": "幅", "h": "高さ", "d": "奥行"}


def drawing_checks(project: dict, fields: dict, use_ai: bool) -> list[dict]:
    """AI-OCR で読んだ図面の寸法注記を、仕様（変更連絡を反映した後の値）と照合する。
    図面が変更連絡の「変更前」の値と一致する場合は、旧版の図面の可能性として知らせる。"""
    if not use_ai:
        return []
    f = fields.get("outer_dims") or {}
    spec = f.get("parsed") if isinstance(f.get("parsed"), dict) else {}
    before = parse_value("dims", f["change"]["from"]) if f.get("change") else None
    out = []
    for d in project["documents"]:
        if d.get("text_layer", True) or d["status"] == "error" or not d.get("include", True):
            continue
        r = storage.load_ai(project["id"], d["id"])
        if not r or r.get("kind") != "ocr":
            continue
        dims = {}
        for x in r.get("dimensions", []):
            k = {"W": "w", "H": "h", "D": "d"}.get(x["axis"])
            if k and k not in dims and x.get("value_mm") is not None:
                dims[k] = x
        items = []
        for k in ("w", "h", "d"):
            if k not in dims:
                continue
            dv = round(dims[k]["value_mm"])
            sv = spec.get(k)
            items.append({"axis": k, "label": AXIS_JA[k], "drawing": dv, "spec": sv, "match": sv is None or sv == dv,
                          "matches_before": bool(before) and sv != dv and (before or {}).get(k) == dv,
                          "source": dims[k]["source"]})
        out.append({"doc_id": d["id"], "doc_name": d["filename"], "title": r.get("title", ""), "drawing_no": r.get("drawing_no", ""),
                    "scale": r.get("scale", ""), "doc_kind": r.get("doc_kind"), "items": items,
                    "mismatch": [i for i in items if not i["match"]], "lines": len(r.get("lines", [])), "model": r.get("model")})
    return out


def collect_issues(fields, comps, fit, est, comp_issues, docs_all, drawings=()):
    issues = list(comp_issues)
    for f in fields.values():
        t = {"kind": "field", "key": f["key"]}
        if f["status"] == "conflict":
            vals = " / ".join(f"{g['value']}（{g['doc_name']}）" for g in f["candidates"])
            issues.append({"severity": "high", "type": "conflict", "blocking": True, "title": f"{f['label']}：資料間で値が異なります",
                           "detail": vals, "target": t})
        elif f["status"] == "missing":
            issues.append({"severity": "high", "type": "missing", "blocking": True, "title": f"{f['label']}：記載が見つかりません",
                           "detail": "値を入力するか、質疑書で顧客に確認してください。", "target": t})
        elif f["status"] in ("review", "inferred"):
            issues.append({"severity": "medium", "type": "review", "blocking": False, "title": f"{f['label']}：確認が必要です",
                           "detail": f["note"], "target": t})
        elif f["status"] == "asked":
            issues.append({"severity": "low", "type": "asked", "blocking": False, "title": f"{f['label']}：質疑回答待ち",
                           "detail": f"「{f['value'] or '未定'}」として見積", "target": t})
    for c in comps:
        t = {"kind": "component", "key": c["key"]}
        label = f"{c['name']}（{c['model'] or '型式なし'}）"
        if c["status"] == "ai":
            issues.append({"severity": "medium", "type": "ai_component", "blocking": False, "title": f"{label}：AI が追加の機器を検出",
                           "detail": "本文の記載から読み取った候補です。確定すると収容判定・見積に反映されます。", "target": t})
        elif c["status"] == "no_master":
            issues.append({"severity": "high", "type": "no_master", "blocking": False, "title": f"{label}：部品マスタ未登録",
                           "detail": "寸法・単価が取得できません。マスタ登録または型式の修正が必要です。", "target": t})
        elif c["status"] == "review":
            mm = c.get("master_match")
            detail = f"近い型式の候補：{mm['model']}" if mm and mm["kind"] == "fuzzy" else "変更前の値が一致しない、または数量が不明です"
            issues.append({"severity": "medium", "type": "review", "blocking": False, "title": f"{label}：確認が必要です",
                           "detail": detail, "target": t})
    if fit:
        if fit["verdict"] == "ng":
            ngs = [ch["label"] for ch in fit["checks"] if ch["status"] == "ng"]
            issues.append({"severity": "high", "type": "fit", "blocking": True, "title": "収容判定：不可",
                           "detail": "、".join(ngs) + "を満たしません。代替筐体を検討してください。", "target": {"kind": "fit"}})
        elif fit["verdict"] == "insufficient":
            issues.append({"severity": "high", "type": "fit", "blocking": True, "title": "収容判定：情報不足",
                           "detail": "判定に必要な寸法データが不足しています。", "target": {"kind": "fit"}})
        th = fit.get("thermal")
        if th and th["need_fan"]:
            issues.append({"severity": "low", "type": "thermal", "blocking": False, "title": "換気ファンの追加を推奨",
                           "detail": f"盤内温度 {th['internal_temp']}℃（上限 {th['max_internal']}℃）", "target": {"kind": "fit"}})
    if est:
        for l in est["rfq"]:
            issues.append({"severity": "medium", "type": "rfq", "blocking": False, "title": f"{l['name']}：単価未登録",
                           "detail": "仕入先への見積依頼が必要です。", "target": {"kind": "estimate", "key": l["id"]}})
        for l in est["expired"]:
            issues.append({"severity": "medium", "type": "expired", "blocking": False, "title": f"{l['name']}：単価の有効期限切れ",
                           "detail": "最新単価を確認してください。", "target": {"kind": "estimate", "key": l["id"]}})
    ocr_done = {g["doc_id"] for g in drawings}
    for g in drawings:
        if g["mismatch"]:
            parts = "、".join(f"{m['label']} 図面 {m['drawing']}mm／仕様 {m['spec']}mm" for m in g["mismatch"])
            old_ver = any(m["matches_before"] for m in g["mismatch"])
            issues.append({"severity": "high", "type": "drawing", "blocking": False, "title": "外形図：仕様と寸法が異なります",
                           "detail": f"{parts}。" + ("図面は変更連絡の変更前の値と一致しており、旧版の図面の可能性があります。" if old_ver else ""),
                           "target": {"kind": "field", "key": "outer_dims"}})
    for d in docs_all:
        if d["status"] == "warning" and d["id"] not in ocr_done:
            issues.append({"severity": "low", "type": "document", "blocking": False, "title": f"{d['filename']}：抽出対象外",
                           "detail": "；".join(d["messages"]), "target": {"kind": "document", "key": d["id"]}})
    order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: order[i["severity"]])
    for i, it in enumerate(issues):
        it["id"] = f"i{i}"
    return issues


def build_questions(fields, fit, custom, drawings=()):
    """質疑書の項目と、見積書に記載する前提条件（assumption）を作る。{no} は質疑番号に置換する。"""
    qs = []
    for f in fields.values():
        refs = sorted({s["doc_name"] + (f" p.{s['page']}" if s.get("page") else "") for s in f["sources"]})
        assume = f"※{f['label']}は「{f['value']}」として見積もっております（質疑No.{{no}}・回答により変更の可能性があります）"
        if f["status"] == "conflict" or (f["status"] == "asked" and f["candidates"]):
            parts = "、".join(f"「{g['doc_name']}」では「{g['value']}」" for g in f["candidates"])
            qs.append({"category": "資料間の相違", "item": f["label"],
                       "question": f"{f['label']}について、{parts}と記載されています。いずれが正となるかご教示ください。"
                                   f"（当方では「{f['value']}」として見積もっております）",
                       "refs": refs, "key": f["key"], "assumption": assume})
        elif f["status"] == "missing" or (f["status"] == "asked" and not f["candidates"]):
            q = f"{f['label']}の記載が見当たりません。ご指示ください。"
            if f["value"]:
                q += f"（当方では「{f['value']}」として見積もっております）"
            qs.append({"category": "記載なし", "item": f["label"], "question": q, "refs": refs, "key": f["key"],
                       "assumption": assume if f["value"] else
                       f"※{f['label']}は記載がないため当社標準仕様として見積もっております（質疑No.{{no}}）"})
        elif f.get("change") and not f["change"]["before_matches"]:
            qs.append({"category": "変更内容の確認", "item": f["label"],
                       "question": f"{f['label']}の変更連絡（{f['change']['desc']}）について、変更前の値が仕様書の記載（{f['change']['from']}）"
                                   f"と一致しません。変更後の値をご確認ください。", "refs": refs, "key": f["key"],
                       "assumption": f"※{f['label']}は変更連絡書の変更後の値「{f['value']}」として見積もっております（質疑No.{{no}}）"})
    if fit and fit.get("selected_id") and fit.get("spec_enclosure"):
        se, e = fit["spec_enclosure"], fit["enclosure"]
        if (se["w"], se["h"], se["d"]) != (e["w"], e["h"], e["d"]):
            qs.append({"category": "仕様変更のご提案", "item": "外形寸法",
                       "question": f"機器構成の変更に伴い、ご指定の外形寸法（W{se['w']}×H{se['h']}×D{se['d']}）では"
                                   f"機器が収容できないため、W{e['w']}×H{e['h']}×D{e['d']} への変更をご提案いたします。"
                                   f"設置スペースへの影響を含め、ご承認いただけますでしょうか。",
                       "refs": [], "key": None,
                       "assumption": f"※盤外形寸法は機器収容のため W{e['w']}×H{e['h']}×D{e['d']} に変更して見積もっております"
                                     f"（質疑No.{{no}}・ご承認をお願いいたします）"})
    for g in drawings:
        if g["mismatch"]:
            parts = "、".join(f"{m['label']}（図面 {m['drawing']}mm／仕様 {m['spec']}mm）" for m in g["mismatch"])
            old_ver = any(m["matches_before"] for m in g["mismatch"])
            qs.append({"category": "図面と仕様の相違", "item": "外形寸法",
                       "question": f"ご提示の{g['doc_kind'] or '図面'}（{g['doc_name']}{'・図番 ' + g['drawing_no'] if g['drawing_no'] else ''}）の寸法が、仕様書・変更連絡の内容と異なります：{parts}。"
                                   + ("変更連絡前の図面と思われますので、" if old_ver else "") + "最新の図面をご提示いただけますでしょうか。",
                       "refs": [g["doc_name"]], "key": "outer_dims",
                       "assumption": f"※外形寸法は仕様書・変更連絡の値（{fields['outer_dims']['value']}）で見積もっております（質疑No.{{no}}）"})
    for c in custom or []:
        qs.append({"category": c.get("category") or "その他", "item": c.get("item") or "", "question": c["question"],
                   "refs": [], "key": None, "custom_id": c["id"]})
    for i, q in enumerate(qs, 1):
        q["no"] = i
        if q.get("assumption"):
            q["assumption"] = q["assumption"].replace("{no}", str(i))
    return qs


def build_conditions(fields, questions):
    v = lambda k: fields.get(k, {}).get("value") or ""
    out = []
    if v("scope"):
        out.append(f"見積範囲：{v('scope')}")
    if v("exclusions"):
        out.append(f"別途（本見積に含まず）：{v('exclusions')}")
    if v("tests"):
        out.append(f"試験：{v('tests')}" + (f"（立会検査 {v('witness')}）" if v("witness") else ""))
    if v("documents"):
        out.append(f"提出図書：{v('documents')}")
    out.extend(q["assumption"] for q in questions if q.get("assumption"))
    return out


# ---------- エントリポイント ----------

def analyze(project: dict, masters: dict | None = None) -> dict:
    t0 = time.perf_counter()
    timings = []

    def lap(name):
        nonlocal t0
        t = time.perf_counter()
        timings.append({"stage": name, "ms": round((t - t0) * 1000, 1)})
        t0 = t

    dic, parts, rules, encs = _masters(masters)
    docs = _ordered_docs(project)
    ex = Extractor(dic)
    use_ai = project.get("settings", {}).get("ai", True)
    per_doc, ai_by_doc = {}, {}
    for d in docs:
        parsed = storage.load_parsed(project["id"], d["id"]) or {"blocks": []}
        per_doc[d["id"]] = ex.run(d, parsed)
        ai_res = storage.load_ai(project["id"], d["id"]) if use_ai else None
        if ai_res:
            ai_by_doc[d["id"]] = ai_res
        combine_ai(ex, per_doc[d["id"]], ai_res)
    lap("項目抽出")

    fields = merge_fields(dic, docs, per_doc, rules.get("conflict_policy", "newer"))
    all_changes = [ch for d in docs for ch in per_doc[d["id"]]["changes"]]
    apply_field_changes(fields, all_changes)
    infer_fields(fields)
    apply_field_overrides(fields, project.get("field_overrides"))
    lap("資料間照合")

    comps, comp_issues = merge_components(dic, docs, per_doc, parts, project.get("component_overrides"),
                                          project.get("extra_components"), ai_by_doc)
    lap("マスタ照合")

    settings = project.get("settings", {})
    reserve = (fields["reserve_space"]["parsed"] or {}).get("pct") if fields["reserve_space"]["value"] else None
    ctx = {
        "outer_dims": fields["outer_dims"]["parsed"] if isinstance(fields["outer_dims"]["parsed"], dict) else None,
        "plate_dims": fields["plate_dims"]["parsed"] if isinstance(fields["plate_dims"]["parsed"], dict) else None,
        "width_limit": (fields["width_limit"]["parsed"] or {}).get("mm") if isinstance(fields["width_limit"]["parsed"], dict) else None,
        "ambient_max": (fields["ambient"]["parsed"] or {}).get("max") if isinstance(fields["ambient"]["parsed"], dict) else None,
        "max_occupancy": round(1 - reserve / 100, 3) if reserve else rules["layout"]["max_occupancy"],
        "occupancy_rule": f"仕様書：予備スペース {reserve:g}% 確保" if reserve else "社内ルール：使用率上限",
    }
    fit = run_fit(comps, ctx, parts, encs, rules, settings.get("enclosure_id"))
    th = fit.get("thermal")
    if th and th["need_fan"] and th.get("fan") and settings.get("include_fan", True):
        fan = next(p for p in parts if p["model"] == th["fan"]["model"])
        comps.append({"key": "rec-fan", "no": None, "name": fan["name"], "raw_name": fan["name"], "name_note": "", "aliased": False,
                      "raw_model": fan["model"], "model": fan["model"], "spec": fan["spec"], "qty": 1, "qty_raw": "1",
                      "mount_raw": "扉面", "mount": "door", "confidence": 1.0, "sources": [], "origin": "recommended",
                      "doc_name": "放熱計算", "changes": [], "notes": [f"必要風量 {th['required_airflow']}m³/h に対し選定"],
                      "recommended": True, "in_master": True, "master_match": {"model": fan["model"], "name": fan["name"], "kind": "exact", "score": 1},
                      "w": fan["w"], "h": fan["h"], "d": fan["d"], "heat_w": 0, "price": fan["price"],
                      "price_valid_until": fan["price_valid_until"], "category": fan["category"], "layout_mount": "door",
                      "status": "recommended"})
        fit = run_fit(comps, ctx, parts, encs, rules, settings.get("enclosure_id"))
        fit["thermal"] = th
        # AI が仕様書の「換気ファン」記載を機器として拾った場合は、放熱計算の推奨品の裏付けとして統合する
        rec = comps[-1]
        for c in [c for c in comps if c.get("candidate") and c["origin"] == "ai"]:
            if label_key(c["name"]) and (label_key(c["name"]) in label_key(rec["name"]) or label_key(rec["name"]) in label_key(c["name"])):
                comps.remove(c)
                rec["ai_verified"] = True
                rec["notes"].append(f"AI も仕様書の記載から必要性を検出：{c['notes'][0].split('：', 1)[-1]}")
    lap("収容判定")

    qty = (fields["quantity"]["parsed"] or {}).get("n", 1) if isinstance(fields["quantity"]["parsed"], dict) else 1
    est = run_estimate(comps, fields, fit, settings, rules, parts, qty)
    lap("見積計算")

    drawings = drawing_checks(project, fields, use_ai)
    issues = collect_issues(fields, comps, fit, est, comp_issues, project["documents"], drawings)
    questions = build_questions(fields, fit, project.get("custom_questions"), drawings)
    conditions = build_conditions(fields, questions)

    risks, instructions = [], []
    for d in docs:
        risks.extend(per_doc[d["id"]]["risks"])
        instructions.extend(per_doc[d["id"]]["instructions"])

    # 変更一覧の行はルールで反映済みのため、AI の「訂正」からは除く（同じ内容を二重に出さない）
    change_ids = {i for ch in all_changes for i in ch["source"]["ids"]}
    ai_notes = [{**c, "doc_name": d["filename"]} for d in docs for c in (ai_by_doc.get(d["id"]) or {}).get("corrections", [])
                if not set(c["source"]["ids"]) & change_ids]
    ai_summary = {
        "used": bool(ai_by_doc),
        "docs": [{"doc_id": d["id"], "filename": d["filename"], "model": r.get("model"), "at": r.get("at"),
                  "stats": r.get("stats"), "usage": r.get("usage")} for d in docs if (r := ai_by_doc.get(d["id"]))],
        "verified": sum((r.get("stats") or {}).get("fields", 0) + (r.get("stats") or {}).get("components", 0) for r in ai_by_doc.values()),
        "rejected": sum((r.get("stats") or {}).get("rejected", 0) for r in ai_by_doc.values()),
        "agreed": sum(1 for f in fields.values() if "rule+ai" in f.get("methods", [])),
        "ai_only": sum(1 for f in fields.values() if f.get("methods") == ["ai"]),
    }

    total_fields = [f for f in fields.values() if f["status"] != "empty"]
    stats = {
        "fields_found": sum(1 for f in fields.values() if f["sources"]),
        "fields_total": len(fields),
        "components": sum(1 for c in comps if not c.get("deleted")),
        "auto_ok": sum(1 for f in total_fields if f["status"] in FIELD_OK),
        "blocking": sum(1 for i in issues if i.get("blocking")),
        "issues": len(issues),
        "documents": len(docs),
    }
    lap("要確認・質疑の生成")
    return {
        "fields": list(fields.values()), "components": comps, "fit": fit, "estimate": est,
        "issues": issues, "questions": questions, "conditions": conditions,
        "risks": risks, "instructions": instructions, "stats": stats, "timings": timings,
        "ai": ai_summary, "ai_notes": ai_notes, "drawings": drawings,
        "analyzed_at": storage.now_iso(),
    }
