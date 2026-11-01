"""OpenAI 連携（AI 読解・仕様書 Q&A・設計レビュー・メール文案）。

設計方針
- AI には資料を「[ID] 本文」の形で渡し、値は原文どおり・根拠 ID と引用を必ず返させる
- 返ってきた値は、引用が該当 ID の原文に実在し、数値が原文と一致するかをプログラムで検証する
  （検証できない値は採用しない＝AI のもっともらしい作り話を見積に入れない）
- 結果は資料のハッシュ・モデル・プロンプト版でキャッシュし、再解析で何度も課金しない
"""
import base64
import hashlib
import json
import os
import re
import time
from difflib import SequenceMatcher

from . import storage
from .normalize import nfkc

PROMPT_VERSION = "2026-10-30.5"
MOUNT_MAP = {"取付板": "plate", "扉面": "door", "不明": None}


class AIUnavailable(Exception):
    pass


class AIError(Exception):
    pass


# ---------- 設定 ----------

def settings() -> dict:
    try:
        s = storage.load_master("ai")
    except (FileNotFoundError, ValueError):
        s = {}
    return {"enabled": s.get("enabled", True), "model": s.get("model", "gpt-5.4-mini"),
            "review_model": s.get("review_model", "gpt-5.5")}


def save_settings(data: dict) -> dict:
    cur = settings()
    for k in ("enabled", "model", "review_model"):
        if k in data:
            cur[k] = data[k]
    storage.save_master("ai", cur)
    return cur


def has_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def status() -> dict:
    s = settings()
    return {"configured": has_key(), "enabled": has_key() and s["enabled"], "model": s["model"], "review_model": s["review_model"]}


def _client():
    if not has_key():
        raise AIUnavailable("OpenAI API キーが設定されていません（.env の OPENAI_API_KEY）")
    import httpx
    from openai import OpenAI
    # 接続できない環境（会場のネットワーク不調など）で画面が長く止まらないよう、接続待ちは短く・再試行は 1 回まで
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=httpx.Timeout(150, connect=8), max_retries=1)


def _explain(e: Exception) -> str:
    """OpenAI SDK の例外を、担当者が対処できる日本語の文言にする。"""
    import openai
    if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError)):
        return "OpenAI に接続できませんでした。ネットワーク接続を確認してください（AI 以外の機能はそのまま使えます）。"
    if isinstance(e, openai.AuthenticationError):
        return "OpenAI API キーが無効です。.env の OPENAI_API_KEY を確認してください。"
    if isinstance(e, openai.RateLimitError):
        return "OpenAI の利用上限に達しました（短時間の呼び出し過多、または残高不足）。しばらく待ってから再実行してください。"
    if isinstance(e, openai.NotFoundError):
        return "指定のモデルを利用できません。マスタ・設定 → AI 設定でモデルを変更してください。"
    if isinstance(e, openai.APIStatusError):
        return f"OpenAI API がエラーを返しました（HTTP {e.status_code}）。時間をおいて再実行してください。"
    return f"OpenAI API の呼び出しに失敗しました：{str(e)[:200]}"


def call_json(model: str, system: str, user: str, schema: dict, name: str, effort: str = "low",
              images: list[bytes] | None = None) -> tuple[dict, dict]:
    """構造化出力（JSON Schema strict）で呼び出す。images を渡すと画像（PNG）も一緒に読ませる。"""
    kw = {"reasoning_effort": effort} if model.startswith(("gpt-5", "o3", "o4")) else {"temperature": 0}
    content: str | list = user
    if images:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(b).decode(), "detail": "high"}}
            for b in images]
    t = time.perf_counter()
    try:
        r = _client().chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
            **kw,
        )
    except AIUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 — SDK の例外種別は多いため、画面に出せる文言へまとめる
        raise AIError(_explain(e)) from e
    msg = r.choices[0].message
    if getattr(msg, "refusal", None):
        raise AIError(f"AI が応答を拒否しました：{msg.refusal}")
    try:
        data = json.loads(msg.content)
    except (TypeError, json.JSONDecodeError) as e:
        raise AIError("AI の応答を解釈できませんでした") from e
    usage = {"model": model, "seconds": round(time.perf_counter() - t, 2),
             "input_tokens": r.usage.prompt_tokens if r.usage else 0,
             "output_tokens": r.usage.completion_tokens if r.usage else 0}
    return data, usage


# ---------- 資料 → プロンプト ----------

def doc_index(parsed: dict, prefix: str = "") -> tuple[str, dict]:
    """資料を「[ID] 本文」の行に変換し、ID → 原文・位置 の索引を返す。表は行単位の ID にする。"""
    lines, index, page = [], {}, None
    for b in parsed.get("blocks", []):
        if b.get("page") and b["page"] != page:
            page = b["page"]
            lines.append(f"--- p.{page} ---")
        if b["type"] == "para":
            i = f"{prefix}{b['id']}"
            lines.append(f"[{i}] {b['text']}")
            index[i] = {"text": b["text"], "page": b.get("page"), "bbox": b.get("bbox"), "ids": [b["id"]]}
        else:
            for ri, row in enumerate(b["rows"]):
                text = " | ".join(c["text"] for c in row)
                if not text.strip(" |"):
                    continue
                i = f"{prefix}{b['id']}r{ri}"
                lines.append(f"[{i}] {text}")
                boxes = [c["bbox"] for c in row if c.get("bbox")]
                bbox = [min(x[0] for x in boxes), min(x[1] for x in boxes), max(x[2] for x in boxes), max(x[3] for x in boxes)] if boxes else None
                index[i] = {"text": text, "page": b.get("page"), "bbox": bbox, "ids": [c["id"] for c in row]}
    return "\n".join(lines), index


_STRIP = re.compile(r"[\s「」『』“”\"'‘’\[\]（）()【】、。，．,.:：;；|・…]")
_IDTAG = re.compile(r"\[[^\]\n]{1,24}\]|\bD\d+:[a-z0-9]+")


def _norm(s: str) -> str:
    s = nfkc(s or "")
    s = _IDTAG.sub("", s)
    return _STRIP.sub("", s).lower()


def _numbers(s: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", nfkc(s or ""))


def verify(value: str, evidence_id: str, quote: str, index: dict) -> tuple[str | None, bool]:
    """引用が原文に実在し、値の数値がすべて原文に含まれるかを検証する。根拠の ID（補正後）と結果を返す。"""
    eid = (evidence_id or "").strip().strip("[]")
    q = _norm(quote)
    v = _norm(value)

    def ok(entry) -> bool:
        t = _norm(entry["text"])
        if not t:
            return False
        quote_ok = bool(q) and (q in t or (len(t) >= 6 and t in q) or
                                (len(q) >= 8 and SequenceMatcher(None, q, t).find_longest_match(0, len(q), 0, len(t)).size >= len(q) * 0.85))
        value_ok = bool(v) and v in t
        nums_ok = all(n in nfkc(entry["text"]).replace(" ", "") for n in _numbers(value))
        return (quote_ok or value_ok) and nums_ok

    if eid in index and ok(index[eid]):
        return eid, True
    for k, entry in index.items():  # ID の取り違えは、引用が一致する別の行で補正する
        if q and q in _norm(entry["text"]) and ok(entry):
            return k, True
    return (eid if eid in index else None), False


def _source(doc: dict, index: dict, eid: str) -> dict:
    e = index[eid]
    return {"doc_id": doc["id"], "doc_name": doc["filename"], "page": e["page"], "bbox": e["bbox"],
            "ids": e["ids"], "text": e["text"]}


# ---------- 1. AI 読解（項目・構成機器の抽出） ----------

EXTRACT_SYSTEM = """あなたは配電盤・制御盤メーカーの見積担当者を支援するアシスタントです。
仕様書・補足資料・メールなどの資料から、見積に必要な情報を抽出します。

厳守事項：
- 資料に明記されていることだけを抽出する。推測・一般論・補完はしない。
- value は資料の記載を原文どおりに書く（単位・表記を変えない。要約しない）。
- evidence_id には根拠の行の [ID] をそのまま入れる。evidence_quote にはその行から根拠部分をそのまま引用する。
- 1つの項目に該当する記載が複数あれば、それぞれ別の要素として出力する。
- components には、機器表・機器一覧に列挙された機器、または本文で新たな追加が指示された機器だけを入れる。
  変更一覧（変更前／変更後）の行や、他資料の機器への言及、「必要に応じて」等の条件付きの記載は入れない。
- corrections には、他の資料の記載を訂正・確定・撤回する文（例：「〇〇は誤記」「〇〇が正」）を入れる。
- subject は工事・案件の件名、customer は見積を依頼している発注者の会社名。メールや連絡書の表題・差出人・宛先・送付先・署名は、
  subject や customer として抽出しない。
- location は盤の設置場所が屋内か屋外かが分かる記載だけを対象にする（受渡場所や地名は対象外）。
- 日付は年が書かれている場合だけ抽出する。"""


def _extract_schema(field_keys: list[str]) -> dict:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["fields", "components", "corrections"],
        "properties": {
            "fields": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["key", "value", "evidence_id", "evidence_quote"],
                "properties": {"key": {"type": "string", "enum": field_keys}, "value": {"type": "string"},
                               "evidence_id": {"type": "string"}, "evidence_quote": {"type": "string"}}}},
            "components": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "model", "spec", "qty", "mount", "evidence_id", "evidence_quote"],
                "properties": {"name": {"type": "string"}, "model": {"type": "string"}, "spec": {"type": "string"},
                               "qty": {"type": ["number", "null"]}, "mount": {"type": "string", "enum": ["取付板", "扉面", "不明"]},
                               "evidence_id": {"type": "string"}, "evidence_quote": {"type": "string"}}}},
            "corrections": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["summary", "evidence_id", "evidence_quote"],
                "properties": {"summary": {"type": "string"}, "evidence_id": {"type": "string"}, "evidence_quote": {"type": "string"}}}},
        },
    }


def _cache_key(doc: dict, model: str) -> str:
    return hashlib.sha256(f"{doc.get('sha256')}|{model}|{PROMPT_VERSION}".encode()).hexdigest()[:16]


def extract_document(project: dict, doc: dict, parsed: dict, dictionary: dict, force: bool = False) -> dict:
    s = settings()
    model = s["model"]
    key = _cache_key(doc, model)
    cached = storage.load_ai(project["id"], doc["id"])
    if cached and cached.get("cache_key") == key and not force:
        return {**cached, "cached": True}

    text, index = doc_index(parsed)
    fields_desc = "\n".join(f"- {f['key']}: {f['label']}（表記例：{'、'.join(f['aliases'][:4])}）" for f in dictionary["fields"])
    user = (f"# 抽出対象の項目\n{fields_desc}\n\n# 資料：{doc['filename']}\n{text}")
    data, usage = call_json(model, EXTRACT_SYSTEM, user, _extract_schema([f["key"] for f in dictionary["fields"]]), "extraction")

    # 取りこぼし防止：項目名が本文に現れるのに抽出されなかった項目だけを、もう一度確認させる
    got = {f["key"] for f in data.get("fields", [])}
    plain = nfkc(text)
    recheck = [f for f in dictionary["fields"] if f["key"] not in got
               and any(len(a) >= 3 and nfkc(a) in plain for a in f["aliases"])]
    usage["recheck"] = [f["key"] for f in recheck]
    if recheck:
        desc = "\n".join(f"- {f['key']}: {f['label']}" for f in recheck)
        extra, u2 = call_json(model, EXTRACT_SYSTEM, f"# 再確認する項目（本文全体を確認し、記載があれば抽出）\n{desc}\n\n# 資料：{doc['filename']}\n{text}",
                              _extract_schema([f["key"] for f in recheck]), "recheck")
        data["fields"] = data.get("fields", []) + extra.get("fields", [])
        usage["seconds"] = round(usage["seconds"] + u2["seconds"], 2)
        usage["input_tokens"] += u2["input_tokens"]
        usage["output_tokens"] += u2["output_tokens"]

    fields, comps, corrections = [], [], []
    rejected = []
    for f in data.get("fields", []):
        eid, ok = verify(f["value"], f["evidence_id"], f["evidence_quote"], index)
        item = {"key": f["key"], "value": f["value"], "quote": f["evidence_quote"], "verified": ok,
                "source": _source(doc, index, eid) if eid else None}
        (fields if ok else rejected).append(item)
    for c in data.get("components", []):
        probe = " ".join(x for x in (c["model"], c["name"]) if x)
        eid, ok = verify(probe, c["evidence_id"], c["evidence_quote"], index)
        item = {"name": c["name"], "model": c["model"], "spec": c["spec"], "qty": c["qty"], "mount": MOUNT_MAP.get(c["mount"]),
                "quote": c["evidence_quote"], "verified": ok, "source": _source(doc, index, eid) if eid else None}
        (comps if ok else rejected).append(item)
    for c in data.get("corrections", []):
        eid, ok = verify("", c["evidence_id"], c["evidence_quote"], index)
        if ok:
            corrections.append({"summary": c["summary"], "source": _source(doc, index, eid)})
        else:
            rejected.append({"summary": c["summary"], "quote": c["evidence_quote"]})

    result = {
        "cache_key": key, "doc_id": doc["id"], "model": model, "prompt_version": PROMPT_VERSION, "at": storage.now_iso(),
        "fields": fields, "components": comps, "corrections": corrections, "rejected": rejected,
        "stats": {"fields": len(fields), "components": len(comps), "corrections": len(corrections), "rejected": len(rejected)},
        "usage": usage,
    }
    storage.save_ai(project["id"], doc["id"], result)
    return {**result, "cached": False}


# ---------- 1b. 画像PDF・スキャン図面の AI-OCR ----------

OCR_VERSION = "2026-10-31.1"
OCR_MAX_PAGES = 3

OCR_SYSTEM = """あなたは制御盤の図面・スキャン資料を読み取る OCR 担当です。画像に写っている文字を、見えたとおりに書き起こします。
- lines には、読み取れた文字列を上から下・左から右の順にすべて入れる。推測で補わない。読めない文字は「?」にする。
- dimensions には寸法の注記を入れる。axis は盤外形の幅=W・高さ=H・奥行=D、それ以外の寸法は「その他」。
  value_mm は注記の数値（mm）。text は注記の文字列そのもの（lines のいずれかに含まれる文字列）。
- bbox はその注記の位置を、ページ画像全体に対する比率 [左, 上, 右, 下]（0〜1）で示す。
- title には表題欄の図面名、drawing_no には図番または盤番号、scale には尺度を入れる（なければ空文字）。
- page は 1 から数えたページ番号。"""

OCR_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["doc_kind", "title", "drawing_no", "scale", "lines", "dimensions"],
    "properties": {
        "doc_kind": {"type": "string", "enum": ["外形図", "配置図", "結線図", "文書", "その他"]},
        "title": {"type": "string"}, "drawing_no": {"type": "string"}, "scale": {"type": "string"},
        "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["text", "page"],
                                             "properties": {"text": {"type": "string"}, "page": {"type": "integer"}}}},
        "dimensions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["axis", "value_mm", "text", "page", "bbox"],
            "properties": {"axis": {"type": "string", "enum": ["W", "H", "D", "その他"]}, "value_mm": {"type": ["number", "null"]},
                           "text": {"type": "string"}, "page": {"type": "integer"},
                           "bbox": {"type": "array", "items": {"type": "number"}}}}},
    },
}


def render_pages(path, max_pages: int = OCR_MAX_PAGES, dpi: int = 144) -> list[dict]:
    """PDF の各ページを PNG にする（画像と、座標換算用のページ寸法）。"""
    import pymupdf
    out = []
    with pymupdf.open(path, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            out.append({"png": page.get_pixmap(dpi=dpi).tobytes("png"), "w": page.rect.width, "h": page.rect.height})
    return out


def ocr_blocks(res: dict | None) -> dict:
    """AI-OCR の書き起こしを、通常の資料と同じ「段落」の形にする（Q&A の根拠に使う）。"""
    if not res or res.get("kind") != "ocr":
        return {"blocks": []}
    return {"blocks": [{"type": "para", "id": ln["id"], "text": ln["text"], "page": ln["page"]} for ln in res["lines"]]}


def ocr_document(project: dict, doc: dict, path, force: bool = False) -> dict:
    """テキスト層のない PDF を画像として AI に読ませ、文字と寸法注記を取り出す。
    寸法は「注記の文字列が書き起こした行に実在し、数値が一致するか」を照合し、照合できないものは採用しない。"""
    s = settings()
    model = s["model"]
    key = hashlib.sha256(f"{doc.get('sha256')}|{model}|ocr|{OCR_VERSION}".encode()).hexdigest()[:16]
    cached = storage.load_ai(project["id"], doc["id"])
    if cached and cached.get("cache_key") == key and not force:
        return {**cached, "cached": True}

    pages = render_pages(path)
    if not pages:
        raise AIError("ページを画像にできませんでした")
    data, usage = call_json(model, OCR_SYSTEM, f"# 資料：{doc['filename']}（{len(pages)}ページ）\nこの資料の画像を読み取ってください。",
                            OCR_SCHEMA, "ocr", images=[pg["png"] for pg in pages])

    lines = [{"id": f"ocr{i}", "text": ln["text"], "page": ln["page"]} for i, ln in enumerate(data.get("lines", [])) if ln["text"].strip()]
    plain = [_norm(ln["text"]) for ln in lines]
    dims, rejected = [], []
    for d in data.get("dimensions", []):
        t = _norm(d["text"])
        nums_ok = d["value_mm"] is None or any(n in nfkc(d["text"]).replace(",", "") for n in {f"{d['value_mm']:g}"})
        ok = bool(t) and any(t in p for p in plain) and nums_ok
        page = d["page"] if 1 <= d["page"] <= len(pages) else 1
        pg = pages[page - 1]
        bbox = None
        b = d.get("bbox") or []
        if len(b) == 4 and all(0 <= v <= 1 for v in b) and b[2] > b[0] and b[3] > b[1]:
            pad = 6
            bbox = [round(b[0] * pg["w"] - pad, 1), round(b[1] * pg["h"] - pad, 1), round(b[2] * pg["w"] + pad, 1), round(b[3] * pg["h"] + pad, 1)]
        item = {"axis": d["axis"], "value_mm": d["value_mm"], "text": d["text"], "verified": ok,
                "source": {"doc_id": doc["id"], "doc_name": doc["filename"], "page": page, "bbox": bbox,
                           "ids": [ln["id"] for ln in lines if t and t in _norm(ln["text"])][:1], "text": d["text"]}}
        (dims if ok else rejected).append(item)
    joined = "".join(plain)
    meta = {k: (data.get(k) or "") for k in ("title", "drawing_no", "scale")}
    meta = {k: v for k, v in meta.items() if v and _norm(v) in joined}  # 書き起こしにない表題は採用しない

    result = {
        "kind": "ocr", "cache_key": key, "doc_id": doc["id"], "model": model, "prompt_version": OCR_VERSION, "at": storage.now_iso(),
        "doc_kind": data.get("doc_kind"), **meta, "lines": lines, "dimensions": dims, "rejected": rejected,
        "fields": [], "components": [], "corrections": [],
        "stats": {"lines": len(lines), "dimensions": len(dims), "rejected": len(rejected), "pages": len(pages),
                  "fields": 0, "components": 0, "corrections": 0},
        "usage": usage,
    }
    storage.save_ai(project["id"], doc["id"], result)
    return {**result, "cached": False}


# ---------- 2. 仕様書 Q&A（出典付き） ----------

ASK_SYSTEM = """あなたは制御盤の見積案件の資料に精通したアシスタントです。
与えられた資料と解析結果だけを根拠に、日本語で簡潔に回答してください（です・ます調、3〜6文程度）。
- 資料に根拠がある内容は、citations に根拠行の [ID] とその行からの引用を入れる。
- 資料に記載がない場合は「資料には記載がありません」と明言し、推測で補わない。
- 資料間で記載が食い違う場合は、両方を示して指摘する。
- 回答本文には [ID] や資料記号（D1 など）を書かない。資料は「主仕様書」「変更連絡書」などの名称で言及する。"""

ASK_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["answer", "citations"],
    "properties": {
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                 "required": ["evidence_id", "quote"],
                                                 "properties": {"evidence_id": {"type": "string"}, "quote": {"type": "string"}}}},
    },
}


def _project_corpus(project: dict, docs: list[dict]) -> tuple[str, dict, dict]:
    parts, index, owner = [], {}, {}
    for i, d in enumerate(docs, 1):
        parsed = storage.load_parsed(project["id"], d["id"]) or ocr_blocks(storage.load_ai(project["id"], d["id"]))
        text, idx = doc_index(parsed, prefix=f"D{i}:")
        parts.append(f"## 資料D{i}：{d['filename']}（{ {'main': '主仕様書', 'supplement': '補足資料', 'drawing': '図面（AI-OCR の書き起こし）'}.get(d['role'], 'その他') }・受領日 {d.get('received_date') or '不明'}）\n{text}")
        index.update(idx)
        owner.update({k: d for k in idx})
    return "\n\n".join(parts), index, owner


def _analysis_digest(a: dict) -> str:
    if not a:
        return "（未解析）"
    f = {x["label"]: x["value"] for x in a["fields"] if x["value"]}
    comps = [f"{c['name']} {c.get('model') or ''} ×{c.get('qty')}" for c in a["components"] if not c.get("deleted")]
    fit = a["fit"]
    est = a["estimate"]
    return json.dumps({
        "抽出項目": f, "構成機器": comps,
        "収容判定": {"結果": {"ok": "可", "ng": "不可", "insufficient": "情報不足"}[fit["verdict"]],
                 "筐体": (fit.get("enclosure") or {}).get("name"),
                 "取付板使用率": (fit.get("plate") or {}).get("occupancy"),
                 "盤内温度": (fit.get("thermal") or {}).get("internal_temp")},
        "見積": {"原価": est["cost_total"], "売価税抜": est["sale_total"], "税込": est["grand_total"]},
        "要確認": [i["title"] for i in a["issues"]],
    }, ensure_ascii=False)


def ask(project: dict, docs: list[dict], question: str, history: list[dict]) -> dict:
    s = settings()
    corpus, index, owner = _project_corpus(project, docs)
    hist = "\n".join(f"{'担当者' if h['role'] == 'user' else 'AI'}：{h['content']}" for h in history[-6:])
    user = (f"# 資料\n{corpus}\n\n# システムの解析結果（参考）\n{_analysis_digest(project.get('analysis'))}\n\n"
            f"# これまでの会話\n{hist or '（なし）'}\n\n# 質問\n{question}")
    data, usage = call_json(s["model"], ASK_SYSTEM, user, ASK_SCHEMA, "answer")
    cites, unverified = [], 0
    seen = set()
    for c in data.get("citations", []):
        eid, ok = verify("", c["evidence_id"], c["quote"], index)
        if ok and eid not in seen:
            seen.add(eid)
            cites.append(_source(owner[eid], index, eid))
        elif not ok:
            unverified += 1
    answer = re.sub(r"\s*[\[［]\s*D\d+:[^\]］]*[\]］]", "", data.get("answer", ""))
    return {"answer": answer, "citations": cites, "unverified": unverified, "usage": usage}


# ---------- 3. AI 設計レビュー ----------

REVIEW_SYSTEM = """あなたは制御盤の設計・見積を20年以上担当してきたベテラン技術者です。
見積前の設計レビューとして、与えられた案件情報（抽出済みの仕様・構成機器・収容判定・温度計算・見積）を確認し、
設計者が見落としやすい技術的リスクや見積漏れを指摘してください。

- 機器容量と保護協調（主幹遮断器の容量、インバータ容量変更の波及など）、放熱、配置・保守性、仕様の不整合、見積漏れの観点で確認する。
- 指摘は具体的に、根拠となる数値（定格・台数・温度など）を示す。一般論だけの指摘はしない。
- 断定できないことは「確認を推奨」と表現する。最大6件、重要度の高い順に並べる。
- target_key には関連する構成機器の key（例：no1）または項目 key（例：main_power）を入れる。該当がなければ空文字。"""

REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "findings"],
    "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["severity", "category", "title", "detail", "target_key"],
            "properties": {"severity": {"type": "string", "enum": ["high", "medium", "low"]},
                           "category": {"type": "string", "enum": ["容量・保護協調", "放熱", "配置・保守", "仕様整合", "見積漏れ", "その他"]},
                           "title": {"type": "string"}, "detail": {"type": "string"}, "target_key": {"type": "string"}}}},
    },
}


def review(project: dict) -> dict:
    s = settings()
    a = project["analysis"]
    comps = [{"key": c["key"], "品名": c["name"], "型式": c.get("model"), "仕様": c.get("spec"), "数量": c.get("qty"),
              "発熱W": c.get("heat_w"), "取付": c.get("layout_mount"), "変更": [f"{ch['attr']} {ch['from']}→{ch['to']}" for ch in c["changes"]]}
             for c in a["components"] if not c.get("deleted")]
    fields = {f["key"]: {"項目": f["label"], "値": f["value"], "状態": f["status"]} for f in a["fields"] if f["value"]}
    fit = a["fit"]
    info = {
        "仕様": fields, "構成機器": comps,
        "収容判定": {"結果": fit["verdict"], "筐体": (fit.get("enclosure") or {}).get("name"),
                 "チェック": [{"項目": c["label"], "結果": c["status"], "内容": c["detail"]} for c in fit["checks"]]},
        "見積条件": a["conditions"], "要確認": [i["title"] for i in a["issues"]],
        "特記事項": [r["text"] for r in a["risks"]],
    }
    data, usage = call_json(s["review_model"], REVIEW_SYSTEM, json.dumps(info, ensure_ascii=False), REVIEW_SCHEMA, "review", effort="medium")
    return {"summary": data["summary"], "findings": data["findings"], "usage": usage,
            "at": storage.now_iso(), "analyzed_at": a["analyzed_at"]}


# ---------- 4. メール文案 ----------

EMAIL_SYSTEM = """あなたは日本の制御盤メーカーの営業担当者です。取引先に送るビジネスメールの文案を作成します。
- 丁寧なビジネス敬語（です・ます調、尊敬語・謙譲語）で、日本の商習慣に沿った構成（宛名→挨拶→本題→結び→署名）にする。
- 与えられた事実だけを使い、金額・日付・番号を変えない。存在しない添付や約束を書かない。
- 宛名は「会社名 ご担当者様」とし、署名は「株式会社サンプル制御システム 営業部 {担当者名}」とする。"""

EMAIL_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["subject", "body"],
                "properties": {"subject": {"type": "string"}, "body": {"type": "string"}}}


def draft_email(project: dict, kind: str, sender: str) -> dict:
    s = settings()
    a = project["analysis"]
    f = {x["key"]: x["value"] for x in a["fields"]}
    facts = {
        "宛先会社": f.get("customer") or project.get("customer"), "件名": f.get("subject"), "盤名称": f.get("panel_name"),
        "見積番号": project["quote_no"], "担当者名": sender,
        "見積金額（税抜）": f"{a['estimate']['sale_total']:,}円", "見積金額（税込）": f"{a['estimate']['grand_total']:,}円",
        "納期": f.get("delivery"), "見積有効期限": f.get("validity"), "前提条件": a["conditions"],
        "質疑事項": [q["question"] for q in a["questions"]],
    }
    purpose = {
        "quote": "見積書（Excel）と質疑書を添付して、見積を提出するメール。前提条件の要点と、質疑への回答のお願いを含める。",
        "questions": "見積作成にあたっての質疑事項を確認するメール。質疑書（Excel）を添付し、各質疑を箇条書きで記載して回答期限のお願いを含める。",
    }[kind]
    data, usage = call_json(s["model"], EMAIL_SYSTEM.replace("{担当者名}", sender),
                            f"# 目的\n{purpose}\n\n# 事実\n{json.dumps(facts, ensure_ascii=False)}", EMAIL_SCHEMA, "email")
    return {**data, "usage": usage}
