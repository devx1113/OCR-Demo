"""表記の正規化と値のパース（単位換算・全角半角・型式の表記揺れなど）。"""
import difflib
import re
import unicodedata

CJK = r"ぁ-ゖァ-ヺー一-鿿々〆"
_PAREN = re.compile(r"[（(][^）)]*[）)]")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def clean_text(s: str) -> str:
    """PDF 抽出時に入る不要な空白（数字と和文の間など）を除去する。"""
    s = (s or "").replace("　", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(rf"(?<=[0-9A-Za-z%])\s+(?=[{CJK}])", "", s)
    return s.strip()


def label_key(s: str) -> str:
    s = _PAREN.sub("", nfkc(s))
    return re.sub(r"[\s・:：\-]", "", s).upper()


def strip_paren(s: str) -> tuple[str, str]:
    """'MCCB（主幹）' → ('MCCB', '主幹')"""
    s = clean_text(s)
    notes = [m.strip("（）() ") for m in _PAREN.findall(s)]
    return _PAREN.sub("", s).strip(), "、".join(n for n in notes if n)


# ---------- 型式 ----------

def model_key(s: str) -> str:
    return re.sub(r"[^A-Z0-9.]", "", nfkc(s).upper())


def normalize_model(s: str) -> str:
    s = nfkc(s).upper().strip()
    s = re.sub(r"[‐‑‒–—―−ｰ]", "-", s)
    return re.sub(r"\s+", " ", s)


def match_model(raw: str, parts: list[dict]) -> dict | None:
    """マスタ照合。完全一致→表記揺れ一致→近似候補 の順で探す。"""
    if not raw:
        return None
    norm = normalize_model(raw)
    key = model_key(raw)
    for p in parts:
        if norm == p["model"]:
            return {"part": p, "score": 1.0, "kind": "exact"}
    for p in parts:
        keys = [model_key(p["model"])] + [model_key(a) for a in p.get("aliases", [])]
        if key in keys:
            return {"part": p, "score": 0.95, "kind": "normalized"}
    best, best_score = None, 0.0
    for p in parts:
        r = difflib.SequenceMatcher(None, key, model_key(p["model"])).ratio()
        if r > best_score:
            best, best_score = p, r
    if best and best_score >= 0.8:
        return {"part": best, "score": round(best_score * 0.8, 2), "kind": "fuzzy"}
    return None


# ---------- 部品名 ----------

def normalize_component_name(raw: str, names: dict[str, list[str]]) -> tuple[str, bool]:
    base, _ = strip_paren(raw)
    k = label_key(base)
    for canonical, aliases in names.items():
        if k == label_key(canonical):
            return canonical, False
        if any(k == label_key(a) for a in aliases):
            return canonical, True
    return base, False


# ---------- 値のパース ----------

_UNIT = {"mm": 1, "cm": 10, "m": 1000}
_NUM = r"(\d+(?:\.\d+)?)"


def _to_mm(num: str, unit: str | None, default="mm") -> float:
    return float(num) * _UNIT.get((unit or default).lower(), 1)


def _unit_of(s: str) -> str | None:
    m = re.search(r"(mm|cm|m)(?![a-z])", s, re.I)
    return m.group(1).lower() if m else None


def parse_length(s: str) -> dict | None:
    t = nfkc(s)
    m = re.search(_NUM + r"\s*(mm|cm|m)?(?![a-z])", t, re.I)
    if not m:
        return None
    mm = _to_mm(m.group(1), m.group(2))
    return {"mm": round(mm)}


def parse_dims(s: str) -> dict | None:
    t = nfkc(s).replace("x", "×").replace("X", "×").replace("*", "×")
    default_unit = _unit_of(t) or "mm"
    out = {}
    for key, pats in (("w", ["W", "幅"]), ("h", ["H", "高さ", "高"]), ("d", ["D", "奥行き", "奥行"])):
        for p in pats:
            m = re.search(rf"{p}\s*[=:：]?\s*{_NUM}\s*(mm|cm|m)?(?![a-z])", t, re.I if p.isascii() else 0)
            if m:
                out[key] = round(_to_mm(m.group(1), m.group(2), default_unit))
                break
    if len(out) < 2:
        m = re.search(rf"{_NUM}\s*×\s*{_NUM}(?:\s*×\s*{_NUM})?", t)
        if m:
            vals = [g for g in m.groups() if g]
            for key, v in zip(("w", "h", "d"), vals):
                out.setdefault(key, round(_to_mm(v, None, default_unit)))
    return out or None


def parse_qty(s: str) -> dict | None:
    m = re.search(_NUM + r"\s*(面|個|台|式|組|本|枚|セット|set)?", nfkc(s))
    if not m:
        return None
    n = float(m.group(1))
    return {"n": int(n) if n.is_integer() else n, "unit": m.group(2) or ""}


def parse_power(s: str) -> dict | None:
    t = nfkc(s).replace("Φ", "φ")
    out = {}
    m = re.search(r"(AC|DC)\s*(\d+)\s*V", t, re.I)
    if m:
        out["kind"], out["v"] = m.group(1).upper(), int(m.group(2))
    m = re.search(r"(\d)\s*(?:φ|相)\s*(\d)\s*W", t)
    if m:
        out["phase"], out["wire"] = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(\d)\s*(?:φ|相)", t)
        if m:
            out["phase"] = int(m.group(1))
    m = re.search(r"(50|60)\s*Hz", t, re.I)
    if m:
        out["hz"] = int(m.group(1))
    return out or None


def parse_temp(s: str) -> dict | None:
    t = nfkc(s)
    m = re.search(r"(-?\d+)\s*[~〜\-]\s*(-?\d+)\s*(?:°C|℃|度)", t)
    if m:
        return {"min": int(m.group(1)), "max": int(m.group(2))}
    m = re.search(r"(-?\d+)\s*(?:°C|℃|度)", t)
    return {"max": int(m.group(1))} if m else None


def parse_percent(s: str) -> dict | None:
    m = re.search(_NUM + r"\s*%", nfkc(s))
    return {"pct": float(m.group(1))} if m else None


def parse_date(s: str) -> str | None:
    m = re.search(r"(\d{4})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})", nfkc(s))
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


_LIST_TAIL = re.compile(r"(を含む|は別途とする|は別途|を除く|とする|含む)?[。.]?$")


def parse_list(s: str) -> list[str]:
    t = _LIST_TAIL.sub("", clean_text(s).strip())
    return [x.strip() for x in re.split(r"[、,，]", t) if x.strip()]


def parse_value(ftype: str, raw: str):
    raw = clean_text(raw)
    if ftype == "dims":
        return parse_dims(raw)
    if ftype == "length":
        return parse_length(raw)
    if ftype == "qty":
        return parse_qty(raw)
    if ftype == "power":
        return parse_power(raw)
    if ftype == "temp":
        return parse_temp(raw)
    if ftype == "percent":
        return parse_percent(raw)
    if ftype == "date":
        return parse_date(raw)
    if ftype == "list":
        return parse_list(raw)
    return raw


def display_value(ftype: str, parsed, raw: str) -> str:
    if parsed in (None, "", []):
        return clean_text(raw)
    if ftype == "dims":
        parts = [f"{k.upper()}{parsed[k]}" for k in ("w", "h", "d") if k in parsed]
        return " × ".join(parts) + " mm"
    if ftype == "length":
        return f"{parsed['mm']} mm"
    if ftype == "qty":
        return f"{parsed['n']}{parsed['unit']}"
    if ftype == "power":
        s = f"{parsed.get('kind', '')}{parsed['v']}V" if "v" in parsed else parsed.get("kind", "")
        if "phase" in parsed:
            s += f" {parsed['phase']}φ" + (f"{parsed['wire']}W" if "wire" in parsed else "")
        if "hz" in parsed:
            s += f" {parsed['hz']}Hz"
        return s.strip()
    if ftype == "temp":
        return f"{parsed['min']}〜{parsed['max']}℃" if "min" in parsed else f"{parsed['max']}℃以下"
    if ftype == "percent":
        return f"{parsed['pct']:g}%"
    if ftype == "list":
        return "、".join(parsed)
    if ftype == "date":
        return parsed
    return clean_text(raw)


def compare_key(ftype: str, parsed, raw: str) -> str:
    if isinstance(parsed, dict):
        return "|".join(f"{k}={parsed[k]}" for k in sorted(parsed))
    if isinstance(parsed, list):
        return "|".join(nfkc(x) for x in parsed)
    return re.sub(r"\s", "", nfkc(str(parsed if parsed is not None else raw)))
