"""見積の版管理：承認のたびに内容を保存し、版どうし（または現在の作業中の内容）を比較する。"""
from . import storage


def snapshot(project: dict, analysis: dict, rev: int | str, **meta) -> dict:
    """承認時点の見積内容。比較と監査に必要な項目だけを残す（解析結果全体は保存しない）。"""
    e = analysis["estimate"]
    return {
        "rev": rev, "at": storage.now_iso(), **meta,
        "sale_total": e["sale_total"], "tax": e["tax"], "grand_total": e["grand_total"], "cost_total": e["cost_total"],
        "margin": e["margin"], "profit_rate": e["profit_rate"],
        "enclosure": (analysis["fit"].get("enclosure") or {}).get("name"), "verdict": analysis["fit"]["verdict"],
        "lines": [{"name": l["name"], "qty": l["qty"], "unit": l["unit"], "unit_price": l["unit_price"], "amount": l["amount"]}
                  for l in e["customer_lines"]],
        "fields": {f["label"]: f["value"] for f in analysis["fields"] if f["value"]},
        "components": [{"name": c["name"], "model": c.get("model") or "", "qty": c.get("qty")}
                       for c in analysis["components"] if not c.get("deleted")],
        "conditions": list(analysis["conditions"]),
        "questions": len(analysis["questions"]),
    }


def _by(items, key):
    out = {}
    for it in items:
        k = key(it)
        n = 2
        while k in out:  # 同名の行は「名称 (2)」として区別する
            k = f"{key(it)} ({n})"
            n += 1
        out[k] = it
    return out


def diff(a: dict, b: dict) -> dict:
    """版 a → 版 b の変化。金額・明細・抽出値・構成機器・前提条件ごとに、追加／削除／変更を返す。"""
    totals = {k: {"a": a[k], "b": b[k], "delta": b[k] - a[k]} for k in ("sale_total", "cost_total", "grand_total")}
    totals["margin"] = {"a": a["margin"], "b": b["margin"], "delta": round(b["margin"] - a["margin"], 4)}

    la, lb = _by(a["lines"], lambda x: x["name"]), _by(b["lines"], lambda x: x["name"])
    lines = [{"name": k, "kind": "added", "b": lb[k]} for k in lb if k not in la]
    lines += [{"name": k, "kind": "removed", "a": la[k]} for k in la if k not in lb]
    lines += [{"name": k, "kind": "changed", "a": la[k], "b": lb[k], "delta": lb[k]["amount"] - la[k]["amount"]}
              for k in la if k in lb and (la[k]["qty"], la[k]["unit_price"], la[k]["amount"]) != (lb[k]["qty"], lb[k]["unit_price"], lb[k]["amount"])]

    fa, fb = a["fields"], b["fields"]
    fields = [{"label": k, "a": fa.get(k), "b": fb.get(k)} for k in dict.fromkeys([*fa, *fb]) if fa.get(k) != fb.get(k)]

    ca, cb = _by(a["components"], lambda x: x["name"]), _by(b["components"], lambda x: x["name"])
    comps = [{"name": k, "kind": "added", "b": cb[k]} for k in cb if k not in ca]
    comps += [{"name": k, "kind": "removed", "a": ca[k]} for k in ca if k not in cb]
    comps += [{"name": k, "kind": "changed", "a": ca[k], "b": cb[k]} for k in ca if k in cb and ca[k] != cb[k]]

    sa, sb = set(a["conditions"]), set(b["conditions"])
    conditions = {"added": [c for c in b["conditions"] if c not in sa], "removed": [c for c in a["conditions"] if c not in sb]}

    other = []
    if a.get("enclosure") != b.get("enclosure"):
        other.append({"label": "筐体", "a": a.get("enclosure"), "b": b.get("enclosure")})
    changes = len(lines) + len(fields) + len(comps) + len(conditions["added"]) + len(conditions["removed"]) + len(other)
    return {"a": {k: a.get(k) for k in ("rev", "at", "approved_by")}, "b": {k: b.get(k) for k in ("rev", "at", "approved_by")},
            "totals": totals, "lines": lines, "fields": fields, "components": comps, "conditions": conditions, "other": other,
            "changes": changes}
