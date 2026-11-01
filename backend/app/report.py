"""精度レポート：担当者がどの自動抽出値を修正したかを集計し、抽出精度を実績で示す。

正解データを別に用意しなくても、日々の確認作業（確定・修正）がそのまま評価データになる。
PoC では実案件の資料 10〜20 件をこの集計で評価する想定。
"""
from collections import defaultdict

METHOD_JA = {"both": "ルール×AI 一致", "rule": "ルールのみ", "ai": "AI のみ"}


def _method(f: dict) -> str | None:
    m = f.get("methods") or []
    if "rule+ai" in m:
        return "both"
    if any(x in ("ai", "ai-support") for x in m):
        return "ai"
    if "rule" in m:
        return "rule"
    return None


def _outcome(f: dict) -> str:
    st = f["status"]
    if st in ("ok", "changed"):
        return "auto"            # 自動抽出のまま使用中（担当者は未修正）
    if st == "confirmed":
        return "confirmed"       # 担当者が「この値で確定」
    if st == "edited":
        return "corrected" if f.get("original") else "filled"  # 抽出値を修正 ／ 記載なしを担当者が補完
    if st == "resolved":
        return "resolved"        # 資料間の矛盾を担当者が判断
    return "open"                # 要確認・矛盾・記載なし・質疑中


def _rate(ok: int, ng: int) -> float | None:
    return round(ok / (ok + ng), 4) if ok + ng else None


def accuracy(projects: list[dict]) -> dict:
    total = defaultdict(int)
    by_method = {k: defaultdict(int) for k in METHOD_JA}
    by_field: dict[str, dict] = {}
    comps = defaultdict(int)
    ai = defaultdict(int)
    detect = defaultdict(int)
    rows = []

    for p in projects:
        a = p.get("analysis")
        if not a:
            continue
        pc = defaultdict(int)
        for f in a["fields"]:
            if f["status"] == "empty":
                continue
            out = _outcome(f)
            if out == "filled" or (out == "open" and not f["sources"]):
                detect["missing"] += 1
                if out == "filled":
                    total["filled"] += 1
                continue
            m = _method(f)
            if f["status"] == "conflict" or f["status"] == "resolved" or len(f.get("candidates") or []) > 1:
                detect["conflicts"] += 1
            if f.get("change"):
                detect["changes"] += 1
            total[out] += 1
            pc[out] += 1
            if m:
                by_method[m][out] += 1
            row = by_field.setdefault(f["key"], {"key": f["key"], "label": f["label"], "auto": 0, "confirmed": 0, "corrected": 0,
                                                 "resolved": 0, "open": 0, "projects": 0})
            row[out] += 1
            row["projects"] += 1

        overrides = p.get("component_overrides") or {}
        for c in a["components"]:
            if c.get("origin") == "manual":
                comps["manual"] += 1
                continue
            if c.get("origin") == "recommended":
                continue
            o = overrides.get(c["key"]) or {}
            if o.get("deleted"):
                comps["deleted"] += 1
            elif "qty" in o or "model" in o:
                comps["corrected"] += 1
            elif o.get("confirmed"):
                comps["confirmed"] += 1
            else:
                comps["auto"] += 1

        st = a.get("ai") or {}
        ai["verified"] += st.get("verified", 0)
        ai["rejected"] += st.get("rejected", 0)
        ai["agreed"] += st.get("agreed", 0)
        ai["ai_only"] += st.get("ai_only", 0)
        for g in a.get("drawings") or []:
            ai["ocr_docs"] += 1
            ai["ocr_dims"] += len(g["items"])
            detect["drawing_mismatch"] += len(g["mismatch"])

        ok = pc["auto"] + pc["confirmed"]
        rows.append({"id": p["id"], "quote_no": p["quote_no"], "name": p["name"], "documents": len(p["documents"]),
                     "extracted": ok + pc["corrected"] + pc["resolved"] + pc["open"], "confirmed": pc["confirmed"],
                     "corrected": pc["corrected"], "open": pc["open"], "rate": _rate(ok, pc["corrected"]),
                     "analyzed_at": a.get("analyzed_at")})

    ok = total["auto"] + total["confirmed"]
    fields = sorted(by_field.values(), key=lambda r: (-(r["corrected"]), r["label"]))
    for r in fields:
        r["rate"] = _rate(r["auto"] + r["confirmed"], r["corrected"])
    return {
        "projects": len(rows),
        "fields": {**{k: total[k] for k in ("auto", "confirmed", "corrected", "resolved", "open", "filled")},
                   "rate": _rate(ok, total["corrected"]),
                   "reviewed_rate": _rate(total["confirmed"] + total["corrected"] + total["resolved"], total["auto"] + total["open"])},
        "by_method": [{"method": k, "label": METHOD_JA[k], "n": sum(v[x] for x in ("auto", "confirmed", "corrected", "resolved", "open")),
                       "ok": v["auto"] + v["confirmed"], "corrected": v["corrected"],
                       "rate": _rate(v["auto"] + v["confirmed"], v["corrected"])} for k, v in by_method.items()],
        "by_field": fields,
        "components": {**dict(comps), "rate": _rate(comps["auto"] + comps["confirmed"], comps["corrected"] + comps["deleted"])},
        "ai": dict(ai), "detect": dict(detect), "rows": rows,
    }


# ---------- 判定一致率（G4） ----------

def fit_agreement(projects: list[dict]) -> dict:
    """収容判定（システム）と設計者の最終判断の一致率。C3・C4 の実用性を評価する指標。"""
    rows = []
    for p in projects:
        r = p.get("fit_review")
        if not r:
            continue
        sysv = r.get("system") or {}
        rows.append({"id": p["id"], "quote_no": p["quote_no"], "name": p["name"], "decision": r["decision"],
                     "system_verdict": sysv.get("verdict"), "system_enclosure": sysv.get("enclosure"),
                     "final_verdict": r.get("final_verdict"), "final_enclosure": r.get("final_enclosure"),
                     "reason": r.get("reason", ""), "by": r.get("by"), "at": r.get("at")})
    agree = sum(1 for r in rows if r["decision"] == "agree")
    return {"recorded": len(rows), "agree": agree, "disagree": len(rows) - agree, "rate": _rate(agree, len(rows) - agree),
            "verdict_diff": sum(1 for r in rows if r["decision"] != "agree" and r["final_verdict"] != r["system_verdict"]),
            "enclosure_diff": sum(1 for r in rows if r["decision"] != "agree" and r["final_verdict"] == r["system_verdict"]),
            "rows": sorted(rows, key=lambda r: r["at"] or "", reverse=True)}


# ---------- 効果測定（F8） ----------

def _ts(s: str | None):
    from datetime import datetime
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def _active_minutes(events: list[str], idle: float) -> float:
    """操作履歴の時刻から作業時間を推定する（操作の間隔が idle 分を超える空き時間は数えない）。"""
    ts = sorted(t for t in (_ts(e) for e in events) if t)
    total = 0.0
    for a, b in zip(ts, ts[1:]):
        gap = (b - a).total_seconds() / 60
        if gap <= idle:
            total += gap
    return round(total + (2 if ts else 0), 1)  # 最初の操作の分として 2 分を加える


def effect(projects: list[dict], rules: dict) -> dict:
    cfg = {"baseline_hours": 6.0, "idle_minutes": 20, **(rules.get("effect") or {})}
    rows = []
    for p in projects:
        a = p.get("analysis")
        revs = p.get("revisions") or []
        if not a:
            continue
        hist = p.get("history") or []
        done_at = (revs[0].get("requested_at") or revs[0].get("at")) if revs else None
        events = [h["at"] for h in hist if not done_at or h["at"] <= done_at]
        active = _active_minutes(events, cfg["idle_minutes"])
        created = _ts(p.get("created_at"))
        lead = round(((_ts(done_at) - created).total_seconds() / 3600), 1) if done_at and created and _ts(done_at) else None
        timings = sum(t["ms"] for t in a.get("timings") or [])
        acc = accuracy([p])
        rows.append({"id": p["id"], "quote_no": p["quote_no"], "name": p["name"], "completed": bool(revs),
                     "active_min": active, "lead_hours": lead, "events": len(events), "analysis_ms": round(timings),
                     "corrected": acc["fields"]["corrected"], "fields": sum(acc["fields"][k] for k in ("auto", "confirmed", "corrected", "resolved", "open")),
                     "saved_hours": round(cfg["baseline_hours"] - active / 60, 1) if revs else None})
    done = [r for r in rows if r["completed"]]
    avg = round(sum(r["active_min"] for r in done) / len(done), 1) if done else None
    fields = sum(r["fields"] for r in rows)
    return {
        "baseline_hours": cfg["baseline_hours"], "idle_minutes": cfg["idle_minutes"],
        "completed": len(done), "projects": len(rows), "avg_active_min": avg,
        "saved_hours_total": round(sum(r["saved_hours"] for r in done), 1) if done else None,
        "reduction_rate": round(1 - (avg / 60) / cfg["baseline_hours"], 4) if avg is not None and cfg["baseline_hours"] else None,
        "correction_rate": round(sum(r["corrected"] for r in rows) / fields, 4) if fields else None,
        "avg_analysis_sec": round(sum(r["analysis_ms"] for r in rows) / len(rows) / 1000, 2) if rows else None,
        "rows": sorted(rows, key=lambda r: r["quote_no"], reverse=True),
    }
