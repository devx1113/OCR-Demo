"""制御盤の収容判定（C2〜C4, C6, C7）と盤内温度上昇の概算（C8）。

取付板は「横ダクトで区切られた段」の構造としてモデル化し、各段に機器を左から詰める
（First-Fit Decreasing Height）。機器ごとの放熱クリアランス（インバータ上下など）は
マスタの値を外形に加えて扱う。
"""


def _units(components, mounts):
    items = []
    for c in components:
        if c.get("deleted") or c.get("candidate") or c.get("layout_mount") not in mounts or not (c.get("w") and c.get("h")):
            continue  # 寸法不明の機器は配置できない（判定は「情報不足」として別途報告する）
        for i in range(min(int(c.get("qty") or 0), 999)):  # 異常な数量で配置計算が止まらないよう上限を設ける
            items.append({"key": c["key"], "idx": i, "name": c["name"], "model": c.get("model") or "",
                          "category": c.get("category") or "", "w": c.get("w"), "h": c.get("h"), "d": c.get("d"),
                          "cl": c.get("clearance") or {}, "terminal": c.get("layout_mount") == "terminal",
                          "recommended": c.get("recommended", False)})
    return items


def _shelf_pack(items, usable_w, gap):
    shelves, oversized = [], []
    for it in sorted(items, key=lambda it: (-it["fh"], -it["fw"])):
        if it["fw"] > usable_w:
            oversized.append(it)
            continue
        for s in shelves:
            if s["used"] + gap + it["fw"] <= usable_w and it["fh"] <= s["h"]:
                it["sx"] = s["used"] + gap
                s["used"] += gap + it["fw"]
                s["items"].append(it)
                break
        else:
            it["sx"] = 0
            shelves.append({"h": it["fh"], "used": it["fw"], "items": [it]})
    return shelves, oversized


def layout_plate(components, plate_w, plate_h, L):
    items = _units(components, {"plate", "terminal"})
    for it in items:
        cl = it["cl"]
        it["fw"] = it["w"] + 2 * cl.get("side", 0)
        it["fh"] = it["h"] + cl.get("top", 0) + cl.get("bottom", 0)
    side, duct, gap = L["side_duct_w"], L["row_duct_h"], L["h_gap"]
    usable_w = plate_w - 2 * side
    main, over1 = _shelf_pack([i for i in items if not i["terminal"]], usable_w, gap)
    term, over2 = _shelf_pack([i for i in items if i["terminal"]], usable_w, gap)
    ducts = [{"x": 0, "y": 0, "w": side, "h": plate_h}, {"x": plate_w - side, "y": 0, "w": side, "h": plate_h},
             {"x": side, "y": 0, "w": usable_w, "h": duct}]
    placed, rows = [], []
    y = duct
    for kind, shelves in (("main", main), ("terminal", term)):
        for s in shelves:
            rows.append({"y": y, "h": s["h"], "used_w": s["used"], "kind": kind})
            for it in s["items"]:
                cl = it["cl"]
                fx = side + it["sx"]
                placed.append({"key": it["key"], "name": it["name"], "model": it["model"], "category": it["category"],
                               "terminal": it["terminal"],
                               "x": fx + cl.get("side", 0), "y": y + cl.get("top", 0), "w": it["w"], "h": it["h"],
                               "fx": fx, "fy": y, "fw": it["fw"], "fh": it["fh"], "clearance": bool(cl)})
            y += s["h"]
            ducts.append({"x": side, "y": y, "w": usable_w, "h": duct})
            y += duct
    area = sum(p["w"] * p["h"] for p in placed)
    return {
        "plate_w": plate_w, "plate_h": plate_h, "usable_w": usable_w, "used_h": y,
        "rows": rows, "items": placed, "ducts": ducts,
        "oversized": [{"name": o["name"], "model": o["model"], "fw": o["fw"], "fh": o["fh"]} for o in over1 + over2],
        "occupancy": round(y / plate_h, 3) if plate_h else None,
        "area_ratio": round(area / (plate_w * plate_h), 3) if plate_h else None,
        "n_horizontal_ducts": len(rows) + 1,
    }


def layout_door(components, door_w, door_h, L):
    items = _units(components, {"door"})
    for it in items:
        it["fw"], it["fh"] = it["w"], it["h"]
    margin, gap = L["door_margin"], L["door_gap"]
    usable_w = door_w - 2 * margin
    shelves, over = _shelf_pack(items, usable_w, gap)
    placed = []
    y = margin
    for s in shelves:
        x0 = margin + (usable_w - s["used"]) / 2
        for it in s["items"]:
            placed.append({"key": it["key"], "name": it["name"], "model": it["model"], "category": it["category"],
                           "recommended": it["recommended"],
                           "x": x0 + it["sx"], "y": y + (s["h"] - it["fh"]) / 2, "w": it["w"], "h": it["h"]})
        y += s["h"] + gap
    used = y - gap + margin if shelves else 0
    return {"door_w": door_w, "door_h": door_h, "used_h": used, "items": placed,
            "oversized": [o["name"] for o in over], "fits": used <= door_h and not over}


def thermal(components, enc, ambient_max, T):
    P = sum((c.get("heat_w") or 0) * (c.get("qty") or 0) for c in components
            if not c.get("deleted") and not c.get("recommended") and not c.get("candidate"))
    W, D = enc["w"] / 1000, enc["d"] / 1000
    H = (enc["h"] - enc.get("base_h", 0)) / 1000
    A = 1.4 * W * (H + D) + 1.8 * D * H
    k = T["k"]
    ambient = ambient_max if ambient_max is not None else T["default_ambient"]
    allow = T["max_internal_temp"] - ambient
    dT = P / (k * A) if A else 0
    need = dT > allow
    airflow = T["airflow_factor"] * (P - k * A * allow) / allow if need and allow > 0 else 0
    return {
        "heat_w": round(P, 1), "area_m2": round(A, 2), "k": k, "ambient": ambient,
        "ambient_from_spec": ambient_max is not None, "max_internal": T["max_internal_temp"],
        "allow_dt": allow, "dt": round(dT, 1), "internal_temp": round(ambient + dT, 1),
        "need_fan": need, "required_airflow": round(airflow) if need else 0,
        "formula_area": "A = 1.4·W·(H+D) + 1.8·D·H（壁面設置の自立形）",
        "formula_dt": "ΔT = P / (k·A)",
        "formula_airflow": "V = f·(P − k·A·ΔT許容) / ΔT許容",
    }


def pick_fan(parts, airflow):
    fans = sorted((p for p in parts if p.get("airflow")), key=lambda p: p["airflow"])
    return next((f for f in fans if f["airflow"] >= airflow), fans[-1] if fans else None)


def evaluate(components, enc, plate_w, plate_h, inner_d, ctx, L):
    """1つの筐体について全チェックを行い、判定と根拠を返す。"""
    checks = []
    components = [c for c in components if not c.get("candidate")]  # AI 検出の未確定候補は判定に含めない
    missing = [c for c in components if not c.get("deleted") and c.get("layout_mount") in ("plate", "terminal", "door")
               and not (c.get("w") and c.get("h"))]
    unknown_mount = [c for c in components if not c.get("deleted") and not c.get("layout_mount")]
    if missing or unknown_mount:
        names = "、".join(f"{c['name']}（{c.get('model') or '型式不明'}）" for c in missing + unknown_mount)
        checks.append({"id": "master", "label": "機器寸法データ", "status": "na",
                       "detail": f"寸法または取付位置が不明な機器があります：{names}", "rule": "部品マスタ"})
    else:
        checks.append({"id": "master", "label": "機器寸法データ", "status": "ok",
                       "detail": "全機器の寸法を部品マスタから取得しました。", "rule": "部品マスタ"})

    limit = ctx.get("width_limit")
    if limit:
        ok = enc["w"] <= limit
        checks.append({"id": "width_limit", "label": "設置スペース（幅）", "status": "ok" if ok else "ng",
                       "detail": f"盤幅 {enc['w']}mm {'≦' if ok else '＞'} 制限 {limit}mm", "rule": "仕様書：設置スペース制限",
                       "value": enc["w"], "limit": limit})

    plate = layout_plate(components, plate_w, plate_h, L)
    if plate["oversized"]:
        names = "、".join(f"{o['name']}（必要幅{o['fw']}mm）" for o in plate["oversized"])
        checks.append({"id": "size", "label": "機器単体の寸法", "status": "ng",
                       "detail": f"取付板の有効幅 {plate['usable_w']}mm に収まらない機器：{names}",
                       "rule": "放熱クリアランス・縦ダクト幅を含む"})
    else:
        checks.append({"id": "size", "label": "機器単体の寸法", "status": "ok",
                       "detail": f"全機器が取付板の有効幅 {plate['usable_w']}mm 以内です（クリアランス込み）。",
                       "rule": "放熱クリアランス・縦ダクト幅を含む"})

    fits = plate["used_h"] <= plate_h
    checks.append({"id": "plate", "label": "取付板への段配置", "status": "ok" if fits else "ng",
                   "detail": f"{len(plate['rows'])}段 + 横ダクト{plate['n_horizontal_ducts']}本で必要高さ {plate['used_h']}mm "
                             f"{'≦' if fits else '＞'} 取付板高さ {plate_h}mm",
                   "rule": f"段間ダクト {L['row_duct_h']}mm・機器間隔 {L['h_gap']}mm", "value": plate["used_h"], "limit": plate_h})

    max_occ = ctx["max_occupancy"]
    occ_ok = plate["occupancy"] <= max_occ
    checks.append({"id": "reserve", "label": "予備スペースの確保", "status": "ok" if occ_ok else ("ng" if fits else "na"),
                   "detail": f"取付板の使用率 {plate['occupancy'] * 100:.1f}% {'≦' if occ_ok else '＞'} 上限 {max_occ * 100:.0f}%",
                   "rule": ctx["occupancy_rule"], "value": plate["occupancy"], "limit": max_occ})

    plate_d = max((c.get("d") or 0) for c in components if c.get("layout_mount") in ("plate", "terminal") and not c.get("deleted")) if components else 0
    door_d = max([(c.get("d") or 0) for c in components if c.get("layout_mount") == "door" and not c.get("deleted")] or [0])
    need_d = plate_d + door_d + L["depth_clearance"]
    d_ok = need_d <= inner_d
    checks.append({"id": "depth", "label": "奥行き", "status": "ok" if d_ok else "ng",
                   "detail": f"取付板機器 {plate_d}mm + 扉面機器 {door_d}mm + 余裕 {L['depth_clearance']}mm = {need_d}mm "
                             f"{'≦' if d_ok else '＞'} 盤内奥行 {inner_d}mm", "rule": "扉面機器との干渉防止",
                   "value": need_d, "limit": inner_d})

    door = layout_door(components, enc["w"], enc["h"] - enc.get("base_h", 0), L)
    checks.append({"id": "door", "label": "扉面への配置", "status": "ok" if door["fits"] else "ng",
                   "detail": f"扉面機器の必要高さ {door['used_h']:.0f}mm {'≦' if door['fits'] else '＞'} 扉高さ {door['door_h']}mm",
                   "rule": f"扉周囲余白 {L['door_margin']}mm・間隔 {L['door_gap']}mm"})

    if any(c["status"] == "na" for c in checks if c["id"] == "master"):
        verdict = "insufficient"
    elif any(c["status"] == "ng" for c in checks):
        verdict = "ng"
    else:
        verdict = "ok"
    return {"verdict": verdict, "checks": checks, "plate": plate, "door": door}


def run_fit(components, ctx, parts, enclosures, rules, selected_id=None):
    L, T = rules["layout"], rules["thermal"]
    outer, plate_dims = ctx.get("outer_dims") or {}, ctx.get("plate_dims") or {}
    spec_enc = None
    if outer.get("w") and outer.get("h"):
        d = outer.get("d") or 600
        cat = next((e for e in enclosures if e["w"] == outer["w"] and e["h"] == outer["h"] and e["d"] == d), None)
        spec_enc = dict(cat) if cat else {"id": None, "name": f"指定寸法 W{outer['w']}×H{outer['h']}×D{d}",
                                           "w": outer["w"], "h": outer["h"], "d": d, "base_h": 100,
                                           "plate_w": outer["w"] - 100, "plate_h": outer["h"] - 400, "inner_d": d - 80, "price": None}
        if plate_dims.get("w") and plate_dims.get("h"):
            spec_enc["plate_w"], spec_enc["plate_h"] = plate_dims["w"], plate_dims["h"]
            spec_enc["plate_from_spec"] = True
        spec_enc["from_spec"] = True

    selected = next((dict(e) for e in enclosures if e["id"] == selected_id), None) if selected_id else None
    enc = selected or spec_enc
    if not enc:
        return {"verdict": "insufficient", "enclosure": None, "checks": [
            {"id": "outer", "label": "盤外形寸法", "status": "na", "detail": "外形寸法が未確定のため判定できません。", "rule": "仕様書"}],
            "plate": None, "door": None, "thermal": None, "alternatives": [], "spec_enclosure": None}

    result = evaluate(components, enc, enc["plate_w"], enc["plate_h"], enc["inner_d"], ctx, L)
    th = thermal(components, enc, ctx.get("ambient_max"), T)
    fan = pick_fan(parts, th["required_airflow"]) if th["need_fan"] else None
    th["fan"] = {"model": fan["model"], "name": fan["name"], "airflow": fan["airflow"], "w": fan["w"], "h": fan["h"]} if fan else None
    result["checks"].append({"id": "thermal", "label": "盤内温度上昇（概算）",
                             "status": "warn" if th["need_fan"] else "ok",
                             "detail": (f"発熱 {th['heat_w']}W → 温度上昇 {th['dt']}K（盤内 {th['internal_temp']}℃）"
                                        + (f"。許容 {th['allow_dt']}K を超えるため換気ファン（{th['fan']['model']}・{th['fan']['airflow']}m³/h）を推奨"
                                           if th["need_fan"] and th["fan"] else "。許容範囲内")),
                             "rule": f"盤内上限 {th['max_internal']}℃・k={th['k']}W/m²K"})

    alternatives = []
    base_d = (outer.get("d") or 0)
    for e in sorted(enclosures, key=lambda e: e["price"]):
        if e["h"] != enc["h"] or e["d"] < base_d:
            continue
        if ctx.get("width_limit") and e["w"] > ctx["width_limit"]:
            continue
        r = evaluate(components, e, e["plate_w"], e["plate_h"], e["inner_d"], ctx, L)
        if r["verdict"] == "ok":
            alternatives.append({"id": e["id"], "name": e["name"], "w": e["w"], "h": e["h"], "d": e["d"], "price": e["price"],
                                 "occupancy": r["plate"]["occupancy"], "is_current": e["id"] == enc.get("id")})
        if len(alternatives) >= 3:
            break

    spec_result = None
    if selected and spec_enc:
        r = evaluate(components, spec_enc, spec_enc["plate_w"], spec_enc["plate_h"], spec_enc["inner_d"], ctx, L)
        spec_result = {"verdict": r["verdict"], "occupancy": r["plate"]["occupancy"], "used_h": r["plate"]["used_h"],
                       "plate_h": spec_enc["plate_h"]}
    result.update(enclosure=enc, thermal=th, alternatives=alternatives, spec_enclosure=spec_enc,
                  spec_result=spec_result, selected_id=selected_id)
    return result
