"""判定ルール・マスタの変更の影響確認（C13）と回帰チェック（G3）。

- 影響確認：保存前のマスタで全案件を再解析し、現在のマスタでの結果と比べる（どの案件の判定・金額が変わるか）
- 回帰チェック：保存されている解析結果と、現在のマスタ・ルールで解析し直した結果を比べる
  （ルール・マスタ・プログラムを更新したあと、過去の案件の結果が意図せず変わっていないかを確かめる）
どちらも案件は保存しない（読むだけ）。
"""
from .analysis import analyze

VERDICT_JA = {"ok": "可", "ng": "不可", "insufficient": "判定不能（情報不足）"}


def _digest(a: dict) -> dict:
    fit, est = a.get("fit") or {}, a.get("estimate") or {}
    enc = fit.get("enclosure") or {}
    return {
        "verdict": fit.get("verdict"), "enclosure": enc.get("name"), "enclosure_id": enc.get("id") or enc.get("name"),
        "sale_total": est.get("sale_total"), "cost_total": est.get("cost_total"),
        "blocking": (a.get("stats") or {}).get("blocking", 0), "issues": (a.get("stats") or {}).get("issues", 0),
        "rfq": len(est.get("rfq") or []), "expired": len(est.get("expired") or []),
        "unmatched": sum(1 for c in a.get("components") or [] if not c.get("deleted") and c.get("status") == "no_master"),
        "fan": next((c["model"] for c in a.get("components") or [] if c.get("recommended")), None),
    }


def _changes(b: dict, x: dict) -> list[dict]:
    out = []
    if b["verdict"] != x["verdict"]:
        out.append({"kind": "verdict", "label": "収容判定", "a": VERDICT_JA.get(b["verdict"], b["verdict"]),
                    "b": VERDICT_JA.get(x["verdict"], x["verdict"]), "severity": "high"})
    if b["enclosure_id"] != x["enclosure_id"]:
        out.append({"kind": "enclosure", "label": "選定筐体", "a": b["enclosure"], "b": x["enclosure"], "severity": "high"})
    if b["fan"] != x["fan"]:
        out.append({"kind": "fan", "label": "換気ファン", "a": b["fan"] or "なし", "b": x["fan"] or "なし", "severity": "medium"})
    if b["sale_total"] != x["sale_total"]:
        out.append({"kind": "sale_total", "label": "見積金額（税抜）", "a": b["sale_total"], "b": x["sale_total"],
                    "delta": (x["sale_total"] or 0) - (b["sale_total"] or 0), "severity": "medium"})
    for k, label in (("blocking", "未解決の要確認"), ("unmatched", "マスタ未登録の機器"), ("rfq", "要見積の明細"), ("expired", "単価期限切れ")):
        if b[k] != x[k]:
            out.append({"kind": k, "label": label, "a": b[k], "b": x[k], "severity": "high" if k == "blocking" and x[k] > b[k] else "low"})
    return out


def _row(p: dict, before: dict, after: dict) -> dict:
    st = (p.get("approval") or {}).get("status")
    ch = _changes(before, after)
    return {"id": p["id"], "quote_no": p["quote_no"], "name": p["name"], "customer": p.get("customer", ""),
            "approval": st, "locked": st in ("approved", "requested"), "before": before, "after": after, "changes": ch,
            "changed": bool(ch)}


def _summary(rows: list[dict], skipped: int) -> dict:
    changed = [r for r in rows if r["changed"]]
    return {
        "total": len(rows), "changed": len(changed), "skipped": skipped,
        "verdict_changed": sum(1 for r in changed if any(c["kind"] in ("verdict", "enclosure") for c in r["changes"])),
        "locked_changed": sum(1 for r in changed if r["locked"]),
        "sale_delta": sum(c.get("delta", 0) for r in changed for c in r["changes"]),
        "rows": sorted(rows, key=lambda r: (not r["changed"], not r["locked"], r["quote_no"])),
    }


def preview(projects: list[dict], masters: dict) -> dict:
    """保存前のマスタ（masters：{"rules": {...}} など）で再解析した場合の変化。"""
    rows, skipped = [], 0
    for p in projects:
        if not p.get("analysis") or not p.get("documents"):
            skipped += 1
            continue
        rows.append(_row(p, _digest(analyze(p)), _digest(analyze(p, masters))))
    return _summary(rows, skipped)


def regression(projects: list[dict]) -> dict:
    """保存済みの解析結果と、現在のマスタ・ルールでの再解析結果の差。"""
    rows, skipped = [], 0
    for p in projects:
        if not p.get("analysis") or not p.get("documents") or p.get("analysis_stale"):
            skipped += 1
            continue
        r = _row(p, _digest(p["analysis"]), _digest(analyze(p)))
        r["analyzed_at"] = p["analysis"].get("analyzed_at")
        rows.append(r)
    return _summary(rows, skipped)


RULE_JA = {
    "layout": {"side_duct_w": "縦ダクト幅", "row_duct_h": "段間ダクト高さ", "h_gap": "機器間隔", "max_occupancy": "使用率上限",
               "depth_clearance": "奥行き余裕", "door_margin": "扉面余白", "door_gap": "扉面機器間隔"},
    "thermal": {"k": "熱通過率", "max_internal_temp": "盤内許容温度", "default_ambient": "既定の周囲温度", "airflow_factor": "風量係数"},
    "labor": {"rate": "工数単価", "design_base_h": "設計 基本", "design_per_type_h": "設計 機器1種", "assembly_base_h": "製作 基本",
              "assembly_per_unit_h": "製作 機器1点", "test_base_h": "試験 基本", "witness_h": "立会検査", "docs_h_per_kind": "図書 1種"},
    "cost": {"overhead_rate": "諸経費率", "transport": "運搬費", "default_margin": "標準利益率", "round_unit": "端数処理単位",
             "tax_rate": "消費税率", "duct_price_per_m": "ダクト単価", "din_price_per_m": "DINレール単価", "wire_per_unit": "電線・端子単価",
             "nameplate": "銘板単価"},
    "market": {"steel_index_base": "鋼材指数（基準）", "steel_index": "鋼材指数", "steel_share": "鋼材連動割合",
               "usd_jpy_base": "為替（基準）", "usd_jpy": "為替", "import_share": "為替連動割合"},
    "effect": {"baseline_hours": "導入前の作成時間", "idle_minutes": "作業時間に数えない空き"},
}


def _num(v):
    return f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else str(v)


def diff_master(name: str, a, b) -> str:
    """マスタの変更内容を 1 行で要約する（版の一覧に表示）。"""
    if name == "parts" and isinstance(a, list) and isinstance(b, list):
        ma, mb = {x["model"]: x for x in a}, {x["model"]: x for x in b}
        added = [m for m in mb if m not in ma]
        removed = [m for m in ma if m not in mb]
        changed = [m for m in mb if m in ma and ma[m] != mb[m]]
        price = [m for m in changed if ma[m].get("price") != mb[m].get("price")]
        parts = []
        if price:
            parts.append(f"単価変更 {len(price)}件（{'、'.join(price[:3])}{'ほか' if len(price) > 3 else ''}）")
        if len(changed) > len(price):
            others = [m for m in changed if m not in price]
            parts.append(f"内容変更 {len(others)}件（{'、'.join(others[:3])}{'ほか' if len(others) > 3 else ''}）")
        if added:
            parts.append(f"追加 {len(added)}件（{'、'.join(added[:3])}）")
        if removed:
            parts.append(f"削除 {len(removed)}件（{'、'.join(removed[:3])}）")
        return "・".join(parts) or "変更なし"
    if name == "enclosures" and isinstance(a, list) and isinstance(b, list):
        ea, eb = {x["id"]: x for x in a}, {x["id"]: x for x in b}
        n = sum(1 for k in eb if k not in ea or ea[k] != eb[k]) + sum(1 for k in ea if k not in eb)
        return f"筐体 {n}件の変更" if n else "変更なし"
    if isinstance(a, dict) and isinstance(b, dict):
        items = []
        for g in dict.fromkeys([*a, *b]):
            va, vb = a.get(g), b.get(g)
            if isinstance(va, dict) and isinstance(vb, dict):
                items += [f"{RULE_JA.get(g, {}).get(k, f'{g}.{k}')} {_num(va.get(k))}→{_num(vb.get(k))}"
                          for k in dict.fromkeys([*va, *vb]) if va.get(k) != vb.get(k)]
            elif va != vb:
                label = {"conflict_policy": "資料間の仮採用ルール"}.get(g, g)
                items.append(label if isinstance(vb, (list, dict)) else f"{label} {va}→{vb}")
        return "、".join(items[:4]) + (f" ほか{len(items) - 4}件" if len(items) > 4 else "") if items else "変更なし"
    return "変更"
