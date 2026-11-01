"""1資料からの情報抽出（B1〜B3, B7, B10, B11）。

辞書（dictionary.json）に定義した項目名・別名・ヘッダ語で、表とテキスト行から候補値を取り出す。
すべての候補に出典（資料・ページ・座標/セルID・原文）を付ける。
本番ではこの層に LLM による構造化抽出を併用し、出典が原文に実在するかをここで検証する設計とする。
"""
import re

from .normalize import clean_text, compare_key, display_value, label_key, nfkc, parse_qty, parse_value

BULLET = re.compile(r"^[\s・●○■□◆◇\-\*※]+")
LABEL_VALUE = re.compile(r"^(?P<label>[^：:]{1,20}?)\s*[：:]\s*(?P<value>.+)$")
SECTION = re.compile(r"^(\d+)[\.．]\s*(\S.*)$")


def _union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


class Extractor:
    def __init__(self, dictionary: dict):
        self.fields = {f["key"]: f for f in dictionary["fields"]}
        self.exact = {}
        self.prefix = []
        for f in dictionary["fields"]:
            for a in f["aliases"]:
                self.exact.setdefault(label_key(a), f)
                self.prefix.append((label_key(a), f))
        self.prefix.sort(key=lambda x: -len(x[0]))
        self.meta_keys = {label_key(a) for m in dictionary["meta_fields"] for a in m["aliases"]}
        self.headers = {k: {label_key(a) for a in v} for k, v in dictionary["component_headers"].items()}
        self.mount_words = dictionary["mount_words"]
        self.risks = [(re.compile(r["pattern"]), r) for r in dictionary["risk_keywords"]]

    # ---------- 共通 ----------

    def match_label(self, label: str):
        k = label_key(label)
        if not k or len(k) > 24 or k in self.meta_keys:
            return None, 0.0
        if k in self.exact:
            return self.exact[k], 0.97
        for ak, f in self.prefix:
            if len(ak) >= 2 and k.startswith(ak):
                return f, 0.85
        return None, 0.0

    def source(self, doc, block, cells=None, text=None):
        cells = cells or []
        return {
            "doc_id": doc["id"], "doc_name": doc["filename"], "page": block.get("page"),
            "bbox": _union([c.get("bbox") for c in cells]) if cells else block.get("bbox"),
            "ids": [c["id"] for c in cells] if cells else [block["id"]],
            "text": text if text is not None else (" | ".join(c["text"] for c in cells) if cells else block.get("text", "")),
        }

    def field_candidate(self, f, raw, conf, src):
        if f["type"] == "enum":
            parsed = next((o for o in f.get("options") or [] if o in nfkc(raw)), None)
            return {"key": f["key"], "raw": clean_text(raw), "parsed": parsed, "display": parsed or clean_text(raw),
                    "cmp": parsed or compare_key("text", None, raw), "confidence": round(conf if parsed else min(conf, 0.6), 2),
                    "source": src}
        parsed = parse_value(f["type"], raw)
        ok = parsed not in (None, "", [])
        if not ok and f["type"] not in ("text", "enum"):
            conf = min(conf, 0.6)
        return {
            "key": f["key"], "raw": clean_text(raw), "parsed": parsed,
            "display": display_value(f["type"], parsed, raw),
            "cmp": compare_key(f["type"], parsed, raw),
            "confidence": round(conf, 2), "source": src,
        }

    # ---------- 表 ----------

    def _header_map(self, row):
        m = {}
        for i, c in enumerate(row):
            k = label_key(c["text"])
            for col, keys in self.headers.items():
                if k in keys and col not in m:
                    m[col] = i
                    break
        return m

    def _mount(self, text):
        for mount, words in self.mount_words.items():
            if any(w in text for w in words):
                return mount
        return None

    def component_rows(self, doc, block, hmap):
        out = []
        for row in block["rows"][1:]:
            get = lambda col: row[hmap[col]]["text"] if col in hmap and hmap[col] < len(row) else ""
            name_raw = get("name")
            if not name_raw.strip():
                continue
            qty = parse_qty(get("qty")) if get("qty") else None
            no_raw = nfkc(get("no"))
            out.append({
                "no": int(no_raw) if no_raw.isdigit() else None,
                "raw_name": name_raw, "raw_model": get("model"), "spec": get("spec"),
                "qty": qty["n"] if qty else None, "qty_raw": get("qty"),
                "mount_raw": get("mount"), "mount": self._mount(get("mount")),
                "confidence": 0.95 if qty else 0.6,
                "source": self.source(doc, block, row),
            })
        return out

    def change_rows(self, doc, block, header):
        idx = {label_key(c["text"]): i for i, c in enumerate(header)}
        col = lambda *names: next((idx[label_key(n)] for n in names if label_key(n) in idx), None)
        ti, bi, ai, ri = col("対象", "項目", "変更箇所"), col("変更前"), col("変更後"), col("理由", "備考")
        out = []
        for row in block["rows"][1:]:
            cell = lambda i: row[i]["text"] if i is not None and i < len(row) else ""
            target = cell(ti)
            if not target:
                continue
            t = nfkc(target)
            ch = {"target": target, "before": cell(bi), "after": cell(ai), "reason": cell(ri),
                  "source": self.source(doc, block, row)}
            m = re.search(r"No\.?\s*(\d+)", t, re.I)
            attr = "model" if re.search("型式|形式|型番", t) else "qty" if re.search("数量|員数", t) else "spec" if "仕様" in t else None
            if m and ("構成機器" in t or attr):
                ch.update(kind="component", no=int(m.group(1)), attr=attr or "spec")
            else:
                f = next((f for ak, f in self.prefix if ak in label_key(t)), None)
                sub = "d" if "奥行" in t else "w" if "幅" in t else "h" if "高さ" in t else None
                ch.update(kind="field", key=f["key"] if f else None, sub=sub)
            out.append(ch)
        return out

    # ---------- 本体 ----------

    def run(self, doc: dict, parsed: dict) -> dict:
        res = {"fields": [], "components": [], "changes": [], "risks": [], "instructions": [], "sections": []}
        section = ""
        seen_risk = set()
        for block in parsed["blocks"]:
            if block["type"] == "table":
                rows = block["rows"]
                if not rows:
                    continue
                header = rows[0]
                hkeys = {label_key(c["text"]) for c in header}
                hmap = self._header_map(header)
                if "name" in hmap and "qty" in hmap:
                    res["components"].extend(self.component_rows(doc, block, hmap))
                    continue
                if "変更前" in hkeys and "変更後" in hkeys:
                    res["changes"].extend(self.change_rows(doc, block, header))
                    continue
                for row in rows:
                    if len(row) < 2:
                        continue
                    f, conf = self.match_label(row[0]["text"])
                    value = " ".join(c["text"] for c in row[1:] if c["text"])
                    if f and value:
                        res["fields"].append(self.field_candidate(f, value, conf, self.source(doc, block, row)))
                continue

            text = block["text"]
            m = SECTION.match(nfkc(text))
            if m and len(text) < 30:
                section = m.group(2).strip()
                res["sections"].append(section)
                continue
            body = BULLET.sub("", text)
            lv = LABEL_VALUE.match(body)
            matched = False
            if lv:
                f, conf = self.match_label(lv.group("label"))
                if f:
                    res["fields"].append(self.field_candidate(f, lv.group("value"), conf, self.source(doc, block)))
                    matched = True
            pm = re.search(r"(\d+(?:\.\d+)?)\s*[%％]\s*(?:程度)?の?予備スペース", nfkc(body))
            if pm:
                f = self.fields["reserve_space"]
                res["fields"].append(self.field_candidate(f, pm.group(1) + "%", 0.92, self.source(doc, block)))
            for pat, r in self.risks:
                if pat.search(body) and (r["label"], block["id"]) not in seen_risk:
                    seen_risk.add((r["label"], block["id"]))
                    res["risks"].append({"label": r["label"], "impact": r["impact"], "text": body,
                                         "source": self.source(doc, block)})
            if not matched and BULLET.match(text) and section:
                res["instructions"].append({"section": section, "text": body, "source": self.source(doc, block)})
        return res
