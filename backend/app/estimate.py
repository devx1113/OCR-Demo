"""見積明細・原価・売価の計算（D1〜D9）。

原価明細（社内用）を作り、掛率（利益率）を掛けて顧客提出用の明細へ集約する。
"""
import math
import re
from datetime import date

from .normalize import label_key, nfkc

GROUPS = {
    "enclosure": "筐体", "equipment": "主要機器", "spares": "予備品", "materials": "付帯部材",
    "labor": "工数", "expenses": "経費",
}


def _line(id, group, name, spec, qty, unit, unit_cost, source, flags=None, note=""):
    return {"id": id, "group": group, "name": name, "spec": spec, "qty": qty, "unit": unit,
            "unit_cost": unit_cost, "source": source, "flags": flags or [], "note": note}


def _price_flags(part_price, valid_until, today):
    flags = []
    if part_price is None:
        flags.append("rfq")
    if valid_until and valid_until < today:
        flags.append("expired")
    return flags


MARKET_DEFAULT = {"steel_index_base": 100, "steel_index": 100, "steel_share": 0.45,
                  "usd_jpy_base": 150, "usd_jpy": 150, "import_share": 0.6}


def market_factors(rules) -> dict:
    """為替・鋼材市況の係数（D8）。マスタ単価を登録した時点の指数（base）からの変動を、価格のうち市況に連動する割合だけ反映する。
    例：鋼材指数 100→110、鋼材比率 45% → 筐体単価 ×1.045"""
    m = {**MARKET_DEFAULT, **(rules.get("market") or {})}
    steel = 1 + (m["steel_index"] / m["steel_index_base"] - 1) * m["steel_share"] if m["steel_index_base"] else 1
    fx = 1 + (m["usd_jpy"] / m["usd_jpy_base"] - 1) * m["import_share"] if m["usd_jpy_base"] else 1
    return {"steel": round(steel, 4), "fx": round(fx, 4), **m}


def _apply_market(ln, factor, label):
    if ln["unit_cost"] is None or abs(factor - 1) < 1e-9:
        return
    ln["base_unit_cost"] = ln["unit_cost"]
    ln["unit_cost"] = round(ln["unit_cost"] * factor)
    ln["flags"].append("market")
    ln["note"] = "　".join(x for x in (ln["note"], f"{label} ×{factor:.3f}") if x)


def run_estimate(components, fields, fit, settings, rules, parts, panel_count=1):
    today = date.today().isoformat()
    C, LB = rules["cost"], rules["labor"]
    mk = market_factors(rules)
    lines = []
    n = max(int(panel_count or 1), 1)
    active = [c for c in components if not c.get("deleted") and not c.get("candidate")]

    enc = (fit or {}).get("enclosure")
    if enc:
        paint = fields.get("paint", {}).get("value") or ""
        lines.append(_line("enc", "enclosure", f"筐体 {enc['name']}", f"塗装色 {paint}".strip() if paint else "",
                           n, "面", enc.get("price"), "盤マスタ" if enc.get("price") is not None else "要見積",
                           _price_flags(enc.get("price"), enc.get("price_valid_until"), today)))
        _apply_market(lines[-1], mk["steel"], "鋼材市況")

    for c in active:
        lines.append(_line(f"eq-{c['key']}", "equipment", c["name"], c.get("model") or "", (c.get("qty") or 0) * n,
                           "個", c.get("price"), "部品マスタ" if c.get("price") is not None else "要見積",
                           _price_flags(c.get("price"), c.get("price_valid_until"), today) if c.get("in_master") else ["rfq"],
                           "放熱計算による推奨品" if c.get("recommended") else ""))
        if c.get("imported"):
            _apply_market(lines[-1], mk["fx"], "為替（輸入品）")

    for i, item in enumerate(fields.get("spares", {}).get("parsed") or []):
        m = re.match(r"(.+?)\s*(\d+)\s*(個|式|本|組|台|枚)?$", nfkc(item))
        name, qty, unit = (m.group(1).strip(), int(m.group(2)), m.group(3) or "個") if m else (item, 1, "式")
        comp = next((c for c in active if label_key(c["name"]) == label_key(name)), None)
        lines.append(_line(f"sp-{i}", "spares", f"予備品 {name}", comp.get("model", "") if comp else "", qty, unit,
                           comp.get("price") if comp else None, "部品マスタ" if comp and comp.get("price") is not None else "要見積",
                           _price_flags(comp.get("price"), comp.get("price_valid_until"), today) if comp else ["rfq"]))
        if comp and comp.get("imported"):
            _apply_market(lines[-1], mk["fx"], "為替（輸入品）")

    plate = (fit or {}).get("plate")
    units = sum((c.get("qty") or 0) for c in active)
    if plate:
        duct_m = math.ceil(((plate["n_horizontal_ducts"]) * plate["usable_w"] + 2 * plate["plate_h"]) / 500) / 2
        din_m = math.ceil(sum(r["used_w"] for r in plate["rows"]) / 500) / 2
        lines.append(_line("duct", "materials", "配線ダクト", "60×60", duct_m * n, "m", C["duct_price_per_m"], "算出ルール",
                           note="段数とダクト配置から算出"))
        lines.append(_line("din", "materials", "DINレール", "35mm", din_m * n, "m", C["din_price_per_m"], "算出ルール",
                           note="各段の機器幅合計から算出"))
    lines.append(_line("wire", "materials", "電線・圧着端子・結束材", "", units * n, "点", C["wire_per_unit"], "算出ルール",
                       note="機器点数 × 単価"))
    door_units = sum((c.get("qty") or 0) for c in active if c.get("layout_mount") == "door")
    lines.append(_line("nameplate", "materials", "銘板", "アクリル製", (door_units + 1) * n, "枚", C["nameplate"], "算出ルール",
                       note="扉面機器数 + 盤名称板"))

    types = len({c.get("model") or c["name"] for c in active})
    witness = bool(fields.get("witness", {}).get("value"))
    doc_kinds = len(fields.get("documents", {}).get("parsed") or [])
    labor = [
        ("design", "設計工数", "図面作成・機器選定", LB["design_base_h"] + LB["design_per_type_h"] * types,
         f"基本{LB['design_base_h']}h + 機器種類{types}種 × {LB['design_per_type_h']}h"),
        ("assembly", "製作工数", "組立・配線", (LB["assembly_base_h"] + LB["assembly_per_unit_h"] * units) * n,
         f"(基本{LB['assembly_base_h']}h + 機器{units}点 × {LB['assembly_per_unit_h']}h) × {n}面"),
        ("test", "試験工数", "工場試験" + ("・立会検査" if witness else ""), LB["test_base_h"] * n + (LB["witness_h"] if witness else 0),
         f"基本{LB['test_base_h']}h" + (f" + 立会{LB['witness_h']}h" if witness else "")),
    ]
    if doc_kinds:
        labor.append(("docs", "図書作成工数", "承認図・完成図書", LB["docs_h_per_kind"] * doc_kinds,
                      f"図書{doc_kinds}種 × {LB['docs_h_per_kind']}h"))
    for id, name, spec, hours, note in labor:
        lines.append(_line(id, "labor", name, spec, round(hours, 1), "h", LB["rate"], "工数算定式", note=note))

    scope = " ".join(fields.get("scope", {}).get("parsed") or [])
    if "運搬" in scope or "輸送" in scope:
        place = fields.get("delivery_place", {}).get("value") or ""
        lines.append(_line("transport", "expenses", "運搬費", place, 1, "式", C["transport"], "経費ルール"))

    overrides = settings.get("line_overrides", {})
    for ln in lines:
        o = overrides.get(ln["id"])
        if o:
            if o.get("qty") is not None:
                ln["qty"] = o["qty"]
            if o.get("unit_cost") is not None:
                ln["unit_cost"] = o["unit_cost"]
                ln["flags"] = [f for f in ln["flags"] if f not in ("rfq", "expired", "market")]
                ln.pop("base_unit_cost", None)
            ln["flags"].append("edited")
        ln["cost"] = round((ln["unit_cost"] or 0) * (ln["qty"] or 0))

    subtotal = sum(l["cost"] for l in lines)
    oh = _line("overhead", "expenses", "諸経費", f"小計 × {C['overhead_rate'] * 100:g}%", 1, "式",
               round(subtotal * C["overhead_rate"]), "経費ルール")
    oh["cost"] = oh["unit_cost"]
    lines.append(oh)

    cost_total = sum(l["cost"] for l in lines)
    margin = settings.get("margin", C["default_margin"])
    factor = 1 / (1 - margin) if margin < 1 else 1
    panel_name = " ".join(x for x in (fields.get("panel_name", {}).get("value"), fields.get("panel_no", {}).get("value")) if x)
    groups = [
        ("body", f"制御盤本体 製作費（{panel_name}）" if panel_name else "制御盤本体 製作費", n, "面",
         lambda l: l["group"] in ("enclosure", "equipment", "materials") or l["id"] == "assembly"),
        ("design", "設計費", 1, "式", lambda l: l["id"] == "design"),
        ("test", "工場試験費" + ("（立会検査含む）" if witness else ""), 1, "式", lambda l: l["id"] == "test"),
        ("docs", "提出図書作成費", 1, "式", lambda l: l["id"] == "docs"),
        ("spares", "予備品", 1, "式", lambda l: l["group"] == "spares"),
        ("transport", "運搬費", 1, "式", lambda l: l["id"] == "transport"),
        ("overhead", "諸経費", 1, "式", lambda l: l["id"] == "overhead"),
    ]
    customer = []
    for gid, name, qty, unit, pred in groups:
        cost = sum(l["cost"] for l in lines if pred(l))
        if cost <= 0:
            continue
        sale = int(round(cost * factor, -2))
        customer.append({"id": gid, "name": name, "qty": qty, "unit": unit, "unit_price": round(sale / qty), "amount": sale, "cost": cost})
    sale_sum = sum(c["amount"] for c in customer)
    unit = C["round_unit"] if C.get("round_unit", 0) > 0 else 1
    rounded = int(math.floor(sale_sum / unit) * unit)
    discount = rounded - sale_sum
    if discount:
        customer.append({"id": "discount", "name": "出精値引", "qty": 1, "unit": "式", "unit_price": discount, "amount": discount, "cost": 0})
    tax = math.floor(rounded * C["tax_rate"])

    return {
        "lines": lines, "groups": GROUPS, "customer_lines": customer,
        "cost_total": cost_total, "margin": margin, "sale_total": rounded, "discount": discount,
        "tax": tax, "grand_total": rounded + tax, "profit": rounded - cost_total,
        "profit_rate": round((rounded - cost_total) / rounded, 4) if rounded else 0,
        "rfq": [l for l in lines if "rfq" in l["flags"]],
        "expired": [l for l in lines if "expired" in l["flags"]],
        "tax_rate": C["tax_rate"],
        "market": {"steel": mk["steel"], "fx": mk["fx"], "steel_index": mk["steel_index"], "steel_index_base": mk["steel_index_base"],
                   "usd_jpy": mk["usd_jpy"], "usd_jpy_base": mk["usd_jpy_base"],
                   "delta": sum(round((l["unit_cost"] - l["base_unit_cost"]) * (l["qty"] or 0)) for l in lines if "base_unit_cost" in l),
                   "lines": sum(1 for l in lines if "base_unit_cost" in l)},
    }
