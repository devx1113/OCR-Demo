"""デモ用の「既存の Excel 見積書雛形」とセル対応表（cellmap.json）を生成する。

実案件ではクライアントの雛形をそのまま使い、cellmap.json だけを作成する想定。
実行: python scripts/make_template.py
"""
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "data" / "templates"
FONT = "游ゴシック"
NAVY = "1F3A5F"
thin = Side(style="thin", color="7F8A99")
medium = Side(style="medium", color=NAVY)
box = Border(left=thin, right=thin, top=thin, bottom=thin)


def f(size=10, bold=False, color="1B2430"):
    return Font(name=FONT, size=size, bold=bold, color=color)


def border_range(ws, rng, border=box):
    for row in ws[rng]:
        for c in row:
            c.border = border


def cover_sheet(wb):
    ws = wb.active
    ws.title = "御見積書"
    for col, w in zip("ABCDEFGHI", (2, 6, 24, 10, 10, 8, 6, 14, 16)):
        ws.column_dimensions[col].width = w
    ws.sheet_view.showGridLines = False

    ws.merge_cells("H1:I1")
    ws["H1"].font = f(9, True, "C0392B")
    ws["H1"].alignment = Alignment(horizontal="right")

    ws.merge_cells("B2:I2")
    ws["B2"] = "御　見　積　書"
    ws["B2"].font = f(20, True, NAVY)
    ws["B2"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 40
    for col in "BCDEFGHI":
        ws[f"{col}2"].border = Border(bottom=Side(style="double", color=NAVY))

    ws.merge_cells("B4:E4")
    ws["B4"].font = f(13, True)
    for col in "BCDE":
        ws[f"{col}4"].border = Border(bottom=thin)
    ws["F4"] = "御中"
    ws["F4"].font = f(12)
    for r, label in ((4, "見積番号"), (5, "見積日"), (6, "担当")):
        ws[f"G{r}"] = label
        ws[f"G{r}"].font = f(9, color="5B6675")
        ws.merge_cells(f"H{r}:I{r}")
        ws[f"H{r}"].font = f(10)
        ws[f"H{r}"].alignment = Alignment(horizontal="right")
    ws["H5"].number_format = 'yyyy"年"m"月"d"日"'

    ws.merge_cells("B7:E7")
    ws["B7"] = "下記のとおり御見積申し上げます。"
    ws["B7"].font = f(10)

    ws["B9"] = "御見積金額"
    ws["B9"].font = f(10, True, "FFFFFF")
    ws["B9"].fill = PatternFill("solid", fgColor=NAVY)
    ws["B9"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.merge_cells("C9:E9")
    ws["C9"] = "=I32"
    ws["C9"].number_format = '"¥"#,##0'
    ws["C9"].font = f(18, True, NAVY)
    ws["C9"].alignment = Alignment(horizontal="center", vertical="center")
    ws["F9"] = "（税込）"
    ws["F9"].font = f(9)
    ws.row_dimensions[9].height = 34
    border_range(ws, "B9:E9", Border(left=medium, right=medium, top=medium, bottom=medium))

    for r, label in ((11, "件名"), (12, "納期"), (13, "受渡場所"), (14, "有効期限")):
        ws[f"B{r}"] = label
        ws[f"B{r}"].font = f(9, color="5B6675")
        end = "I" if r == 11 else "E"
        ws.merge_cells(f"C{r}:{end}{r}")
        ws[f"C{r}"].font = f(10, r == 11)
        for col in "CDE" + ("FGHI" if r == 11 else ""):
            ws[f"{col}{r}"].border = Border(bottom=Side(style="hair", color="7F8A99"))

    for r, text, size, bold in ((12, "株式会社サンプル制御システム", 11, True), (13, "〒000-0000 東京都〇〇区〇〇1-2-3", 8, False),
                                (14, "TEL 03-0000-0000 / FAX 03-0000-0001", 8, False)):
        ws.merge_cells(f"G{r}:I{r}")
        ws[f"G{r}"] = text
        ws[f"G{r}"].font = f(size, bold)
        ws[f"G{r}"].alignment = Alignment(horizontal="right")

    for col, label in (("H", "承認"), ("I", "作成")):
        ws[f"{col}16"] = label
        ws[f"{col}16"].font = f(8, color="5B6675")
        ws[f"{col}16"].alignment = Alignment(horizontal="center")
        ws[f"{col}17"].font = f(9, True, "C0392B")
        ws[f"{col}17"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws[f"{col}16"].border = ws[f"{col}17"].border = box
    ws.row_dimensions[17].height = 36

    head = {"B": "No", "C": "品名・仕様", "F": "数量", "G": "単位", "H": "単価", "I": "金額"}
    ws.merge_cells("C19:E19")
    for col in "BCDEFGHI":
        c = ws[f"{col}19"]
        if col in head:
            c.value = head[col]
        c.font = f(9, True, "FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = box
    ws.row_dimensions[19].height = 20
    for r in range(20, 30):
        ws.merge_cells(f"C{r}:E{r}")
        ws[f"I{r}"] = f'=IF(F{r}="","",F{r}*H{r})'
        for col in "BCDEFGHI":
            ws[f"{col}{r}"].border = box
            ws[f"{col}{r}"].font = f(9)
        ws[f"B{r}"].alignment = ws[f"F{r}"].alignment = ws[f"G{r}"].alignment = Alignment(horizontal="center")
        ws[f"H{r}"].number_format = ws[f"I{r}"].number_format = "#,##0;[Red]-#,##0"
        ws.row_dimensions[r].height = 18

    for r, label, formula in ((30, "小計", "=SUM(I20:I29)"), (31, "消費税（10%）", "=ROUNDDOWN(I30*0.1,0)"), (32, "合計", "=I30+I31")):
        ws.merge_cells(f"G{r}:H{r}")
        ws[f"G{r}"] = label
        ws[f"G{r}"].font = f(9, r == 32)
        ws[f"G{r}"].alignment = Alignment(horizontal="center")
        ws[f"I{r}"] = formula
        ws[f"I{r}"].number_format = "#,##0"
        ws[f"I{r}"].font = f(10, r == 32)
        border_range(ws, f"G{r}:I{r}")
        if r == 32:
            for col in "GHI":
                ws[f"{col}{r}"].fill = PatternFill("solid", fgColor="E8EEF6")

    ws.merge_cells("B34:I34")
    ws["B34"] = "見積条件・前提条件"
    ws["B34"].font = f(9, True, "FFFFFF")
    ws["B34"].fill = PatternFill("solid", fgColor=NAVY)
    for r in range(35, 45):
        ws.merge_cells(f"B{r}:I{r}")
        ws[f"B{r}"].font = f(8.5)
        ws[f"B{r}"].alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 24
        for col in "BCDEFGHI":
            ws[f"{col}{r}"].border = Border(bottom=Side(style="hair", color="B8C0CC"),
                                            left=thin if col == "B" else None, right=thin if col == "I" else None)

    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=0.5, right=0.5, top=0.6, bottom=0.6)
    ws.print_area = "A1:I45"


def equipment_sheet(wb):
    ws = wb.create_sheet("主要機器構成")
    ws.sheet_view.showGridLines = False
    for col, w in zip("ABCDEFG", (6, 24, 16, 26, 7, 10, 22)):
        ws.column_dimensions[col].width = w
    ws.merge_cells("A1:G1")
    ws["A1"] = "主要機器構成表"
    ws["A1"].font = f(14, True, NAVY)
    ws.merge_cells("A2:G2")
    ws["A2"].font = f(10)
    for col, label in zip("ABCDEFG", ("No", "品名", "型式", "仕様", "数量", "取付位置", "備考")):
        c = ws[f"{col}4"]
        c.value = label
        c.font = f(9, True, "FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(horizontal="center")
        c.border = box
    for r in range(5, 45):
        for col in "ABCDEFG":
            ws[f"{col}{r}"].border = box
            ws[f"{col}{r}"].font = f(9)
        ws[f"A{r}"].alignment = ws[f"E{r}"].alignment = ws[f"F{r}"].alignment = Alignment(horizontal="center")
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


CELLMAP = {
    "cover": {"sheet": "御見積書", "cells": {
        "customer": "B4", "quote_no": "H4", "date": "H5", "owner": "H6", "subject": "C11", "delivery": "C12",
        "delivery_place": "C13", "validity": "C14", "draft_mark": "H1", "approver": "H17", "creator": "I17"}},
    "lines": {"sheet": "御見積書", "start_row": 20, "max_rows": 10,
              "cols": {"no": "B", "name": "C", "qty": "F", "unit": "G", "price": "H"}},
    "totals": {"sheet": "御見積書", "subtotal": "I30", "tax": "I31", "total": "I32"},
    "conditions": {"sheet": "御見積書", "start_row": 35, "max_rows": 10, "col": "B"},
    "equipment": {"sheet": "主要機器構成", "subject": "A2", "start_row": 5, "max_rows": 40,
                  "cols": {"no": "A", "name": "B", "model": "C", "spec": "D", "qty": "E", "mount": "F", "note": "G"}},
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    cover_sheet(wb)
    equipment_sheet(wb)
    wb.save(OUT / "estimate_template.xlsx")
    (OUT / "cellmap.json").write_text(json.dumps(CELLMAP, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written:", OUT / "estimate_template.xlsx")


if __name__ == "__main__":
    main()
