"""資料の検査（A3）と構造化（PDF / Word / Excel → 段落・表ブロック + 座標）。"""
import hashlib
import re
from pathlib import Path

import pymupdf
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook

from .normalize import clean_text, parse_date

OLE_MAGIC = b"\xd0\xcf\x11\xe0"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect(path: Path, ext: str) -> dict:
    """破損・パスワード・テキスト層の有無を検査する。"""
    info = {"kind": ext.lstrip("."), "pages": None, "text_layer": True, "status": "ok", "messages": []}

    def fail(msg):
        info["status"] = "error"
        info["messages"].append(msg)
        return info

    with open(path, "rb") as f:
        head = f.read(8)
    if ext == ".pdf" and head.startswith(b"PK"):
        return fail("拡張子は .pdf ですが、中身は Word / Excel ファイルです。正しい拡張子で登録してください。")
    if ext in (".docx", ".xlsx") and head.startswith(b"%PDF"):
        return fail(f"拡張子は {ext} ですが、中身は PDF ファイルです。正しい拡張子で登録してください。")
    if ext == ".pdf":
        try:
            doc = pymupdf.open(path, filetype="pdf")
        except Exception:
            return fail("PDFを開けません。ファイルが破損している可能性があります。")
        if doc.needs_pass:
            return fail("パスワードで保護されています。解除済みのファイルを登録してください。")
        info["pages"] = doc.page_count
        empty = [i + 1 for i, p in enumerate(doc) if len(p.get_text().strip()) < 10]
        if len(empty) == doc.page_count:
            info["text_layer"] = False
            info["status"] = "warning"
            info["messages"].append("テキスト層のない画像PDFです。AI-OCR で文字と寸法注記を読み取ります（AI を使わない場合は抽出対象外）。")
        elif empty:
            info["status"] = "warning"
            info["messages"].append(f"p.{', '.join(map(str, empty))} はテキスト層がありません（画像のみ）。")
    elif ext in (".docx", ".xlsx"):
        if head.startswith(OLE_MAGIC):
            return fail("パスワード保護された Office ファイル、または旧形式です。保護を解除して再登録してください。")
        try:
            if ext == ".docx":
                Document(path)
            else:
                load_workbook(path, read_only=True).close()
        except Exception:
            return fail("ファイルを開けません。破損している可能性があります。")
    else:
        return fail("未対応の形式です（PDF / Word(.docx) / Excel(.xlsx) に対応）。")
    return info


# ---------- PDF ----------

def _cell_text(chars: list[dict], bbox) -> str:
    """セル内の文字を基線ごとに行へまとめ、折返しを考慮して連結する。"""
    x0, y0, x1, y1 = bbox
    inside = [c for c in chars if x0 <= c["cx"] <= x1 and y0 <= c["cy"] <= y1]
    return _join_chars(inside)


def _join_chars(chars: list[dict]) -> str:
    if not chars:
        return ""
    lines: list[list[dict]] = []
    for c in sorted(chars, key=lambda c: (round(c["oy"], 0), c["x0"])):
        if lines and abs(lines[-1][0]["oy"] - c["oy"]) <= 2.5:
            lines[-1].append(c)
        else:
            lines.append([c])
    out = ""
    for i, line in enumerate(lines):
        line.sort(key=lambda c: c["x0"])
        text = "".join(c["c"] for c in line).strip()
        # 和文の折返しは詰めて連結し、英数字どうしの折返しだけ空白を挟む
        if i > 0 and out and out[-1].isascii() and text[:1].isascii():
            out += " "
        out += text
    return clean_text(out)


_NEW_PARA = re.compile(r"^([・●○■□◆◇※\-\*]|\d+[\.．、)）]|[①-⑳]|第\d+)")


def _merge_wrapped(page_blocks: list[dict]) -> list[dict]:
    """右端まで達して折り返された行を、次の行と1つの段落にまとめる。"""
    paras = [b for b in page_blocks if b["type"] == "para"]
    if not paras:
        return page_blocks
    right = max(b["bbox"][2] for b in paras)
    out: list[dict] = []
    for b in page_blocks:
        prev = out[-1] if out else None
        if (prev and b["type"] == "para" and prev["type"] == "para" and abs(prev["size"] - b["size"]) < 0.5
                and prev["bbox"][2] >= right - prev["size"] * 2.5
                and 0 <= b["bbox"][1] - prev["bbox"][3] < b["size"] * 1.2
                and b["bbox"][0] <= prev["bbox"][0] + b["size"] * 1.5
                and not _NEW_PARA.match(b["text"])):
            joiner = " " if prev["text"][-1:].isascii() and b["text"][:1].isascii() else ""
            prev["text"] = clean_text(prev["text"] + joiner + b["text"])
            prev["bbox"] = [min(prev["bbox"][0], b["bbox"][0]), prev["bbox"][1], max(prev["bbox"][2], b["bbox"][2]), b["bbox"][3]]
            continue
        out.append(dict(b))
    return out


def parse_pdf(path: Path) -> dict:
    doc = pymupdf.open(path)
    pages, blocks = [], []
    for pno, page in enumerate(doc, start=1):
        pages.append({"w": page.rect.width, "h": page.rect.height})
        chars = []
        raw = page.get_text("rawdict")
        for b in raw["blocks"]:
            for line in b.get("lines", []):
                for span in line["spans"]:
                    for ch in span["chars"]:
                        x0, y0, x1, y1 = ch["bbox"]
                        chars.append({"c": ch["c"], "x0": x0, "x1": x1, "cx": (x0 + x1) / 2,
                                      "cy": (y0 + y1) / 2, "oy": ch["origin"][1], "size": span["size"]})
        try:
            tables = list(page.find_tables().tables)
        except Exception:
            tables = []
        tboxes = []
        page_blocks = []
        for ti, t in enumerate(tables):
            rows = []
            for ri, row in enumerate(t.rows):
                cells = []
                for ci, cb in enumerate(row.cells):
                    if cb is None:
                        continue
                    cells.append({"id": f"p{pno}t{ti}r{ri}c{ci}", "text": _cell_text(chars, cb), "bbox": list(cb)})
                rows.append(cells)
            tboxes.append(t.bbox)
            page_blocks.append({"id": f"p{pno}t{ti}", "type": "table", "page": pno, "bbox": list(t.bbox), "rows": rows})
        free = [c for c in chars if not any(b[0] <= c["cx"] <= b[2] and b[1] <= c["cy"] <= b[3] for b in tboxes)]
        lines: list[list[dict]] = []
        for c in sorted(free, key=lambda c: (c["oy"], c["x0"])):
            if lines and abs(lines[-1][0]["oy"] - c["oy"]) <= 2.5:
                lines[-1].append(c)
            else:
                lines.append([c])
        for li, line in enumerate(lines):
            text = _join_chars(line)
            if not text:
                continue
            x0 = min(c["x0"] for c in line)
            x1 = max(c["x1"] for c in line)
            size = max(c["size"] for c in line)
            oy = line[0]["oy"]
            page_blocks.append({"id": f"p{pno}l{li}", "type": "para", "page": pno,
                                "bbox": [x0, oy - size * 0.95, x1, oy + size * 0.25], "text": text, "size": round(size, 1)})
        page_blocks.sort(key=lambda b: b["bbox"][1])
        blocks.extend(_merge_wrapped(page_blocks))
    return {"format": "pdf", "pages": pages, "blocks": blocks}


# ---------- Word ----------

def parse_docx(path: Path) -> dict:
    doc = Document(path)
    blocks = []
    n = 0
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, doc)
            text = clean_text(p.text)
            if not text:
                continue
            style = p.style.name if p.style is not None else ""
            blocks.append({"id": f"b{n}", "type": "para", "page": None, "bbox": None, "text": text,
                           "style": "title" if style == "Title" else "heading" if style.startswith("Heading") else "body"})
            n += 1
        elif child.tag == qn("w:tbl"):
            t = Table(child, doc)
            rows = []
            for ri, row in enumerate(t.rows):
                cells, seen = [], set()
                for ci, cell in enumerate(row.cells):
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cells.append({"id": f"b{n}r{ri}c{ci}", "text": clean_text(cell.text), "bbox": None})
                rows.append(cells)
            blocks.append({"id": f"b{n}", "type": "table", "page": None, "bbox": None, "rows": rows})
            n += 1
    return {"format": "docx", "pages": [], "blocks": blocks}


# ---------- Excel ----------

def parse_xlsx(path: Path) -> dict:
    wb = load_workbook(path, data_only=True)
    blocks = []
    for si, ws in enumerate(wb.worksheets):
        rows = []
        for ri, row in enumerate(ws.iter_rows()):
            cells = [{"id": f"s{si}r{ri}c{ci}", "text": clean_text(str(c.value)) if c.value is not None else "",
                      "bbox": None, "ref": c.coordinate} for ci, c in enumerate(row)]
            if any(c["text"] for c in cells):
                while cells and not cells[-1]["text"]:
                    cells.pop()
                rows.append(cells)
        if rows:
            blocks.append({"id": f"s{si}", "type": "para", "page": None, "bbox": None, "text": f"シート：{ws.title}", "style": "heading"})
            blocks.append({"id": f"s{si}t", "type": "table", "page": None, "bbox": None, "rows": rows})
    return {"format": "xlsx", "pages": [], "blocks": blocks}


def parse(path: Path, kind: str) -> dict:
    return {"pdf": parse_pdf, "docx": parse_docx, "xlsx": parse_xlsx}[kind](path)


# ---------- 資料メタ情報の推定（A2） ----------

def guess_meta(parsed: dict, meta_fields: list[dict]) -> dict:
    from .normalize import label_key

    alias = {label_key(a): f["key"] for f in meta_fields for a in f["aliases"]}
    meta: dict = {}
    title = None
    for b in parsed["blocks"]:
        if b["type"] == "para" and title is None:
            if b.get("style") == "title" or (b.get("size") or 0) >= 16:
                title = b["text"]
        if b["type"] == "table":
            for row in b["rows"]:
                if len(row) >= 2:
                    k = alias.get(label_key(row[0]["text"]))
                    if k and k not in meta:
                        meta[k] = row[1]["text"]
    if title is None:
        title = next((b["text"] for b in parsed["blocks"] if b["type"] == "para"), None)
    meta["title"] = title
    if "issue_date" in meta:
        meta["issue_date"] = parse_date(meta["issue_date"])
    if "version" in meta:
        m = re.search(r"第?\s*(\d+)\s*版|Rev\.?\s*(\w+)", meta["version"])
        meta["version"] = meta["version"] if not m else (f"第{m.group(1)}版" if m.group(1) else f"Rev.{m.group(2)}")
    t = (title or "") + " " + (meta.get("doc_no") or "")
    meta["role"] = "supplement" if re.search(r"補足|変更|追加|質疑|回答|-S\d", t) else "main"
    return meta
