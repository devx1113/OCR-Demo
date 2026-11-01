"""Excel 出力（E1〜E6）。

- 見積書：既存雛形を開き、cellmap.json のセル対応に従って値だけを書き込む（数式・書式・結合セルは雛形のまま）
- 質疑書 / 見積根拠書：新規ブックとして生成
- PDF：LibreOffice があれば変換してプレビューに使う
"""
import json
import os
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .config import CELLMAP, ESTIMATE_TEMPLATE

FONT = "游ゴシック"
NAVY = "1F3A5F"
thin = Side(style="thin", color="9AA5B4")
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
MOUNT_LABEL = {"plate": "取付板", "terminal": "取付板（端子）", "door": "扉面"}


class ExportBlocked(Exception):
    def __init__(self, items):
        super().__init__("blocking issues")
        self.items = items


def _fv(analysis, key):
    return next((f["value"] for f in analysis["fields"] if f["key"] == key), "") or ""


def _set(ws, ref, value):
    """値を書き込む。資料由来の文字列が「=」で始まっても数式として解釈させない（Excel の数式インジェクション対策）。"""
    c = ws[ref]
    c.value = value
    if c.data_type == "f":
        c.data_type = "s"
    return c


def export_estimate(project: dict, analysis: dict, out_dir: Path, force: bool = False) -> Path:
    blocking = [i for i in analysis["issues"] if i.get("blocking")]
    if blocking and not force:
        raise ExportBlocked(blocking)
    cmap = json.loads(CELLMAP.read_text(encoding="utf-8"))
    wb = load_workbook(ESTIMATE_TEMPLATE)
    est = analysis["estimate"]

    cv = wb[cmap["cover"]["sheet"]]
    cells = cmap["cover"]["cells"]
    approval = project.get("approval") or {}
    subject = _fv(analysis, "subject")
    panel = " ".join(x for x in (_fv(analysis, "panel_name"), _fv(analysis, "panel_no")) if x)
    values = {
        "customer": _fv(analysis, "customer") or project.get("customer", ""),
        "quote_no": project["quote_no"],
        "date": date.today(),
        "owner": project.get("owner", ""),
        "subject": f"{subject}（{panel}）" if subject and panel else subject or panel,
        "delivery": _fv(analysis, "delivery"),
        "delivery_place": _fv(analysis, "delivery_place"),
        "validity": _fv(analysis, "validity"),
        "draft_mark": "" if approval.get("status") == "approved" else
                      ("【未承認ドラフト・要確認事項あり】" if blocking else "【未承認ドラフト】"),
        "approver": approval.get("by", "") if approval.get("status") == "approved" else "",
        "creator": project.get("owner", ""),
    }
    for k, ref in cells.items():
        _set(cv, ref, values.get(k, ""))

    L = cmap["lines"]
    ls = wb[L["sheet"]]
    lines = est["customer_lines"]
    if len(lines) > L["max_rows"]:
        raise ValueError(f"明細行数（{len(lines)}）が雛形の行数（{L['max_rows']}）を超えています")
    for i, ln in enumerate(lines):
        r = L["start_row"] + i
        for k in ("no", "name", "qty", "unit", "price"):
            _set(ls, f"{L['cols'][k]}{r}", {"no": i + 1, "name": ln["name"], "qty": ln["qty"], "unit": ln["unit"], "price": ln["unit_price"]}[k])

    C = cmap["conditions"]
    cs = wb[C["sheet"]]
    conds = analysis["conditions"][: C["max_rows"]]
    for i, text in enumerate(conds):
        _set(cs, f"{C['col']}{C['start_row'] + i}", text)

    E = cmap["equipment"]
    es = wb[E["sheet"]]
    _set(es, E["subject"], values["subject"])
    comps = [c for c in analysis["components"] if not c.get("deleted")]
    for i, c in enumerate(comps[: E["max_rows"]]):
        r = E["start_row"] + i
        note = "推奨追加品" if c.get("recommended") else ("変更連絡により変更" if c.get("changes") else
                                                     "追加機器" if c.get("origin") == "added" else "")
        row = {"no": i + 1, "name": c["name"], "model": c.get("model") or "", "spec": c.get("spec") or "",
               "qty": c.get("qty"), "mount": MOUNT_LABEL.get(c.get("layout_mount"), ""), "note": note}
        for k, col in E["cols"].items():
            _set(es, f"{col}{r}", row[k])

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"見積書_{project['quote_no']}.xlsx"
    wb.save(path)
    return path


def _sheet_header(ws, title, sub, headers, widths):
    ws.sheet_view.showGridLines = False
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, size=14, bold=True, color=NAVY)
    _set(ws, "A2", sub)
    ws["A2"].font = Font(name=FONT, size=9, color="5B6675")
    for i, (h, w) in enumerate(zip(headers, widths)):
        col = chr(65 + i)
        ws.column_dimensions[col].width = w
        c = ws[f"{col}4"]
        c.value = h
        c.font = Font(name=FONT, size=9, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = BOX
    ws.freeze_panes = "A5"


def _rows(ws, rows, start=5, wrap_cols=()):
    for r, row in enumerate(rows, start):
        for i, v in enumerate(row):
            c = _set(ws, ws.cell(row=r, column=i + 1).coordinate, v)
            c.font = Font(name=FONT, size=9)
            c.border = BOX
            c.alignment = Alignment(vertical="top", wrap_text=(i in wrap_cols))
            if isinstance(v, (int, float)):
                c.number_format = "#,##0.##"


def export_questions(project: dict, analysis: dict, out_dir: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "質疑書"
    subject = _fv(analysis, "subject")
    _sheet_header(ws, "質　疑　書", f"件名：{subject}　／　見積番号：{project['quote_no']}　／　作成日：{date.today():%Y年%m月%d日}",
                  ["No", "区分", "項目", "質疑内容", "参照資料", "ご回答"], [5, 14, 14, 60, 26, 36])
    rows = [[q["no"], q["category"], q["item"], q["question"], "\n".join(q["refs"]), ""] for q in analysis["questions"]]
    _rows(ws, rows, wrap_cols=(3, 4, 5))
    for r in range(5, 5 + len(rows)):
        ws.row_dimensions[r].height = 60
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"質疑書_{project['quote_no']}.xlsx"
    wb.save(path)
    return path


STATUS_JA = {"ok": "抽出済", "confirmed": "確定", "edited": "修正済", "resolved": "解決済", "changed": "変更反映",
             "review": "要確認", "inferred": "推定", "conflict": "矛盾", "missing": "記載なし", "asked": "質疑中", "empty": "—",
             "added": "追加", "no_master": "マスタ未登録", "recommended": "推奨追加", "deleted": "削除"}


def export_basis(project: dict, analysis: dict, out_dir: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "抽出項目"
    sub = f"見積番号：{project['quote_no']}　／　解析日時：{analysis['analyzed_at']}　／　社内資料（顧客提出不可）"
    _sheet_header(ws, "見積根拠書　抽出項目と出典", sub,
                  ["項目", "値", "状態", "信頼度", "出典資料", "ページ", "原文", "備考"], [18, 30, 10, 8, 30, 7, 46, 30])
    rows = []
    for f in analysis["fields"]:
        src = f["sources"][0] if f["sources"] else {}
        rows.append([f["label"], f["value"], STATUS_JA.get(f["status"], f["status"]), f["confidence"],
                     src.get("doc_name", ""), src.get("page") or "", src.get("text", ""),
                     (f["change"]["desc"] + " " if f.get("change") else "") + (f["note"] or "")])
    _rows(ws, rows, wrap_cols=(1, 6, 7))

    ws = wb.create_sheet("構成機器")
    _sheet_header(ws, "構成機器とマスタ照合", sub,
                  ["No", "品名", "型式", "数量", "状態", "W", "H", "D", "発熱W", "単価", "出典", "補正・変更内容"],
                  [5, 22, 14, 6, 12, 6, 6, 6, 7, 10, 28, 50])
    rows = []
    for c in analysis["components"]:
        notes = c["notes"] + [f"{ch['attr']}：{ch['from']} → {ch['to']}（{ch['reason']}）" for ch in c["changes"]]
        rows.append([c.get("no") or "", c["name"], c.get("model") or "", c.get("qty"), STATUS_JA.get(c["status"], c["status"]),
                     c.get("w"), c.get("h"), c.get("d"), c.get("heat_w"), c.get("price"), c.get("doc_name", ""), "\n".join(notes)])
    _rows(ws, rows, wrap_cols=(11,))

    fit = analysis["fit"]
    ws = wb.create_sheet("収容判定")
    verdict = {"ok": "可", "ng": "不可", "insufficient": "情報不足"}[fit["verdict"]]
    enc = fit.get("enclosure") or {}
    _sheet_header(ws, f"収容判定：{verdict}", f"判定対象：{enc.get('name', '—')}　／　{sub}",
                  ["チェック項目", "結果", "内容", "適用ルール"], [22, 8, 80, 36])
    mark = {"ok": "○", "ng": "×", "warn": "△", "na": "—"}
    _rows(ws, [[c["label"], mark[c["status"]], c["detail"], c.get("rule", "")] for c in fit["checks"]], wrap_cols=(2, 3))

    est = analysis["estimate"]
    ws = wb.create_sheet("原価内訳")
    _sheet_header(ws, "原価内訳", f"原価合計 {est['cost_total']:,}円　／　売価 {est['sale_total']:,}円　／　粗利率 {est['profit_rate'] * 100:.1f}%",
                  ["区分", "名称", "仕様・型式", "数量", "単位", "単価", "金額", "根拠", "備考"], [10, 26, 22, 7, 5, 11, 12, 12, 34])
    _rows(ws, [[est["groups"][l["group"]], l["name"], l["spec"], l["qty"], l["unit"], l["unit_cost"], l["cost"], l["source"],
                l["note"] + (" ［要見積依頼］" if "rfq" in l["flags"] else "") + (" ［単価期限切れ］" if "expired" in l["flags"] else "")]
               for l in est["lines"]], wrap_cols=(8,))

    ws = wb.create_sheet("変更履歴")
    _sheet_header(ws, "操作・変更履歴", sub, ["日時", "担当者", "操作", "内容"], [20, 14, 20, 80])
    _rows(ws, [[h["at"], h["user"], h["action"], h["detail"]] for h in project.get("history", [])], wrap_cols=(3,))

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"見積根拠書_{project['quote_no']}.xlsx"
    wb.save(path)
    return path


def _soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for cand in (r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                 "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(cand).exists():
            return cand
    return None


def soffice_available() -> bool:
    return _soffice() is not None


def to_pdf(xlsx: Path) -> Path:
    exe = _soffice()
    if not exe:
        raise RuntimeError("LibreOffice が見つからないため PDF プレビューを生成できません。")
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([exe, "--headless", "--calc", "--convert-to", "pdf", "--outdir", td, str(xlsx)],
                       check=True, capture_output=True, timeout=120,
                       env={**os.environ, "HOME": td})
        out = xlsx.with_suffix(".pdf")
        shutil.move(Path(td) / (xlsx.stem + ".pdf"), out)
    return out


# ---------- 他システム連携用 CSV（F9） ----------

def _csv_cell(v):
    """CSV を Excel で開いたときに「=」「+」「-」「@」で始まる文字列が数式として実行されないようにする。"""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return "" if v is None else v


def _write_csv(path: Path, header: list[str], rows: list[list]) -> Path:
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # BOM 付き UTF-8：Excel でもそのまま開ける
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(header)
        w.writerows([[_csv_cell(v) for v in r] for r in rows])
    return path


def export_sales_csv(project: dict, analysis: dict, out_dir: Path) -> Path:
    """販売管理・ERP への取込用：顧客提出の見積明細（1 行 = 1 明細、末尾に小計・消費税・合計）。"""
    est = analysis["estimate"]
    approval = project.get("approval") or {}
    st = "承認済" if approval.get("status") == "approved" else "未承認"
    head = [project["quote_no"], _fv(analysis, "subject") or project["name"], _fv(analysis, "customer") or project.get("customer", ""), st]
    rows = [[*head, i + 1, l["name"], l["qty"], l["unit"], l["unit_price"], l["amount"], "明細"]
            for i, l in enumerate(est["customer_lines"])]
    n = len(rows)
    rows += [[*head, n + 1, "小計（税抜）", 1, "式", est["sale_total"], est["sale_total"], "小計"],
             [*head, n + 2, f"消費税（{est['tax_rate'] * 100:g}%）", 1, "式", est["tax"], est["tax"], "税"],
             [*head, n + 3, "合計（税込）", 1, "式", est["grand_total"], est["grand_total"], "合計"]]
    return _write_csv(out_dir / f"見積明細_販売管理取込_{project['quote_no']}.csv",
                      ["見積番号", "件名", "顧客", "承認状態", "行番号", "品名", "数量", "単位", "単価", "金額", "行区分"], rows)


def export_purchase_csv(project: dict, analysis: dict, out_dir: Path) -> Path:
    """購買システムへの取込用：筐体・機器・予備品の手配リスト（原価・単価根拠・要見積の区別付き）。社内用。"""
    est = analysis["estimate"]
    comps = {f"eq-{c['key']}": c for c in analysis["components"]}
    flag_ja = {"rfq": "要見積", "expired": "単価期限切れ", "market": "市況係数反映", "edited": "単価修正"}
    rows = []
    for l in est["lines"]:
        if l["group"] not in ("enclosure", "equipment", "spares"):
            continue
        c = comps.get(l["id"]) or {}
        rows.append([project["quote_no"], {"enclosure": "筐体", "equipment": "機器", "spares": "予備品"}[l["group"]],
                     c.get("maker") or "", l["spec"] if l["group"] == "equipment" else "", l["name"], l["qty"], l["unit"],
                     l["unit_cost"], l["cost"], l["source"], "・".join(flag_ja[f] for f in l["flags"] if f in flag_ja),
                     l.get("note") or ""])
    return _write_csv(out_dir / f"手配リスト_購買取込_{project['quote_no']}.csv",
                      ["見積番号", "区分", "メーカー", "型式", "品名", "数量", "単位", "原価単価", "原価金額", "単価根拠", "注意", "備考"], rows)
