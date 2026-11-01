"""類似過去案件の検索（C12）。

過去案件（受注・失注の実績、および本システムで承認した見積）の仕様・構成機器・最終的な盤サイズ・金額を、
今回の案件と項目ごとに比べて類似度を出す。ルール化が難しい判断（盤サイズの決め方・金額の妥当性）を、
実績で裏付けるための参考情報として示す（見積の値は変えない）。

類似度は項目ごとの一致度の加重平均（0〜100）。どちらかに情報がない項目は計算から除き、重みを按分する。
"""
import re

from . import storage
from .normalize import label_key, nfkc

WEIGHTS = {"purpose": 20, "type": 10, "location": 5, "voltage": 10, "protection": 5, "components": 30, "drive": 10, "size": 10}
LABELS = {"purpose": "用途", "type": "盤形式", "location": "設置場所", "voltage": "主回路電圧", "protection": "保護等級",
          "components": "構成機器", "drive": "インバータ容量", "size": "盤サイズ"}
PURPOSE_WORDS = ["送水", "配水", "給水", "加圧", "揚水", "排水", "汚水", "下水", "浄水", "ろ過", "洗浄", "薬品", "注入", "ポンプ",
                 "ブロワ", "曝気", "空調", "ファン", "換気", "コンベア", "搬送", "監視", "動力", "照明"]


def _kw(spec: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*kW", nfkc(spec or ""), re.I)
    return float(m.group(1)) if m else 0.0


def _voltage(s: str):
    m = re.search(r"(\d{3})\s*V", nfkc(s or ""))
    return int(m.group(1)) if m else None


def _ptype(s: str):
    s = nfkc(s or "")
    return "自立形" if "自立" in s else "壁掛形" if "壁掛" in s else "据置形" if "据置" in s else None


def _ip(s: str):
    m = re.search(r"IP\s*([0-9X]{2})", nfkc(s or "").upper())
    return f"IP{m.group(1)}" if m else None


def _dims(s: str):
    m = re.search(r"W\s*(\d+)\D+H\s*(\d+)\D+D\s*(\d+)", nfkc(s or ""))
    return {"w": int(m.group(1)), "h": int(m.group(2)), "d": int(m.group(3))} if m else None


def _profile(*, title, panel_type, location, main_power, protection, dims, components, parts_by_model):
    comps = []
    for c in components:
        p = parts_by_model.get(c.get("model") or "") or {}
        comps.append({"model": c.get("model") or "", "name": c.get("name") or p.get("name") or c.get("model") or "",
                      "category": c.get("category") or p.get("category") or "", "qty": int(c.get("qty") or 0),
                      "kw": _kw(c.get("spec") or p.get("spec") or "")})
    return {
        "purpose": {w for w in PURPOSE_WORDS if w in nfkc(title or "")},
        "type": _ptype(panel_type), "location": location or None, "voltage": _voltage(main_power), "protection": _ip(protection),
        "dims": dims, "components": comps,
        "drive_kw": round(sum(c["kw"] * c["qty"] for c in comps if c["category"] == "駆動機器"), 1),
        "drives": sum(c["qty"] for c in comps if c["category"] == "駆動機器"),
    }


def current_profile(project: dict, parts_by_model: dict) -> dict:
    a = project["analysis"]
    f = {x["key"]: x for x in a["fields"]}
    v = lambda k: (f.get(k) or {}).get("value") or ""  # noqa: E731
    enc = (a.get("fit") or {}).get("enclosure") or {}
    od = (f.get("outer_dims") or {}).get("parsed")
    dims = {k: enc[k] for k in ("w", "h", "d")} if enc.get("w") else (od if isinstance(od, dict) and od.get("w") else None)
    comps = [c for c in a["components"] if not c.get("deleted") and not c.get("candidate") and not c.get("recommended")]
    return _profile(title=f"{v('subject')} {v('panel_name')} {project.get('name', '')}", panel_type=v("panel_type"),
                    location=v("location"), main_power=v("main_power"), protection=v("protection"), dims=dims,
                    components=comps, parts_by_model=parts_by_model)


def _past_cases(projects: list[dict], exclude_id: str, parts_by_model: dict) -> list[dict]:
    try:
        archive = storage.load_master("past_projects")
    except (OSError, ValueError):
        archive = []
    out = []
    for c in archive:
        prof = _profile(title=c["name"], panel_type=c.get("panel_type"), location=c.get("location"), main_power=c.get("main_power"),
                        protection=c.get("protection"), dims=c.get("dims"),
                        components=[x for x in c.get("components", []) if not str(x.get("model", "")).startswith("FAN-")],
                        parts_by_model=parts_by_model)
        out.append({"source": "archive", "quote_no": c["quote_no"], "name": c["name"], "customer": c.get("customer", ""),
                    "date": c.get("date"), "result": c.get("result"), "designer": c.get("designer"), "note": c.get("note", ""),
                    "enclosure": c.get("enclosure"), "sale_total": c.get("sale_total"), "cost_total": c.get("cost_total"),
                    "profile": prof})
    # 本システムで承認した見積も過去案件として蓄積される（最新の版を使う）
    for p in projects:
        revs = p.get("revisions") or []
        if p["id"] == exclude_id or not revs:
            continue
        r = revs[-1]
        fl = r.get("fields") or {}
        prof = _profile(title=f"{fl.get('件名', '')} {fl.get('盤名称', '')} {p['name']}", panel_type=fl.get("形式"),
                        location=fl.get("設置場所"), main_power=fl.get("主回路電源"), protection=fl.get("保護等級"),
                        dims=_dims(r.get("enclosure") or ""),
                        components=[x for x in r.get("components", []) if not str(x.get("model", "")).startswith("FAN-")],
                        parts_by_model=parts_by_model)
        out.append({"source": "system", "project_id": p["id"], "quote_no": p["quote_no"], "name": p["name"],
                    "customer": p.get("customer", ""), "date": (r.get("at") or "")[:10], "result": f"承認 第{r['rev']}版",
                    "designer": r.get("approved_by"), "note": "", "enclosure": r.get("enclosure"),
                    "sale_total": r.get("sale_total"), "cost_total": r.get("cost_total"), "profile": prof})
    return out


def _bag(comps, key):
    b = {}
    for c in comps:
        if c[key]:
            b[c[key]] = b.get(c[key], 0) + c["qty"]
    return b


def _wjaccard(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    den = sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)
    return sum(min(a.get(k, 0), b.get(k, 0)) for k in keys) / den if den else 0.0


def score(cur: dict, past: dict) -> dict:
    parts, match, diff = {}, [], []

    if cur["purpose"] and past["purpose"]:
        common = cur["purpose"] & past["purpose"]
        parts["purpose"] = len(common) / len(cur["purpose"] | past["purpose"])
        if common:
            match.append(f"用途：{'・'.join(sorted(common, key=PURPOSE_WORDS.index))}")
    for k in ("type", "location", "voltage", "protection"):
        a, b = cur[k], past[k]
        if a is None or b is None:
            continue
        parts[k] = 1.0 if a == b else 0.0
        fmt = (lambda x: f"AC{x}V") if k == "voltage" else str
        (match if a == b else diff).append(f"{LABELS[k]}：{fmt(b)}" + ("" if a == b else f"（今回 {fmt(a)}）"))

    if cur["components"] and past["components"]:
        by_model = _wjaccard(_bag(cur["components"], "model"), _bag(past["components"], "model"))
        by_cat = _wjaccard(_bag(cur["components"], "category"), _bag(past["components"], "category"))
        parts["components"] = 0.6 * by_model + 0.4 * by_cat
        match.append(f"構成機器の一致 {round(parts['components'] * 100)}%")
        mine = {label_key(c["name"]): c["name"] for c in cur["components"]}
        theirs = {label_key(c["name"]): c["name"] for c in past["components"]}
        if missing := sorted(mine[k] for k in mine.keys() - theirs.keys())[:2]:
            diff.append(f"過去案件になし：{'・'.join(missing)}")
        if extra := sorted(theirs[k] for k in theirs.keys() - mine.keys())[:2]:
            diff.append(f"過去案件のみ：{'・'.join(extra)}")

    a, b = cur["drive_kw"], past["drive_kw"]
    if a or b:
        parts["drive"] = 1 - abs(a - b) / max(a, b)
        txt = f"インバータ {b:g}kW（{past['drives']}台）"
        (match if parts["drive"] >= 0.8 else diff).append(txt + ("" if a == b else f"／今回 {a:g}kW"))

    if cur["dims"] and past["dims"]:
        rel = [abs(cur["dims"][k] - past["dims"][k]) / max(cur["dims"][k], past["dims"][k]) for k in ("w", "h", "d")]
        parts["size"] = max(0.0, 1 - sum(rel) / len(rel) * 3)
        same = all(cur["dims"][k] == past["dims"][k] for k in ("w", "h", "d"))
        (match if same else diff).append(f"盤サイズ W{past['dims']['w']}×H{past['dims']['h']}×D{past['dims']['d']}"
                                         + ("（同じ）" if same else ""))

    wsum = sum(WEIGHTS[k] for k in parts)
    total = sum(WEIGHTS[k] * v for k, v in parts.items()) / wsum * 100 if wsum else 0
    return {"score": round(total), "breakdown": [{"key": k, "label": LABELS[k], "weight": WEIGHTS[k], "value": round(v, 3)}
                                                 for k, v in parts.items()],
            "match": match, "diff": diff}


def search(project: dict, projects: list[dict], parts: list[dict], limit: int = 5) -> dict:
    by_model = {p["model"]: p for p in parts}
    cur = current_profile(project, by_model)
    found = []
    for c in _past_cases(projects, project["id"], by_model):
        s = score(cur, c.pop("profile"))
        found.append({**c, **s})
    found.sort(key=lambda x: x.get("date") or "", reverse=True)  # 同じ類似度なら新しい案件を先に
    found.sort(key=lambda x: -x["score"])
    top = found[:limit]

    sale = (project["analysis"].get("estimate") or {}).get("sale_total")
    near = [x for x in top[:3] if x["score"] >= 60 and x.get("sale_total")]  # 金額・盤サイズの比較は上位 3 件まで
    price = None
    if near and sale:
        amounts = [x["sale_total"] for x in near]
        avg = round(sum(amounts) / len(amounts))
        price = {"n": len(near), "min": min(amounts), "max": max(amounts), "avg": avg, "current": sale,
                 "delta_rate": round((sale - avg) / avg, 4),
                 "position": "low" if sale < min(amounts) else "high" if sale > max(amounts) else "within"}
    sizes = {}
    for x in near:
        if x.get("enclosure"):
            sizes[x["enclosure"]] = sizes.get(x["enclosure"], 0) + 1
    won = [x for x in near if x.get("result") == "受注"]
    return {
        "items": top, "searched": len(found), "price": price,
        "sizes": [{"enclosure": k, "n": v} for k, v in sorted(sizes.items(), key=lambda kv: -kv[1])],
        "won": len(won), "lost": sum(1 for x in near if x.get("result") == "失注"),
        "current": {"enclosure": ((project["analysis"].get("fit") or {}).get("enclosure") or {}).get("name"), "sale_total": sale,
                    "drive_kw": cur["drive_kw"], "components": len(cur["components"])},
    }
