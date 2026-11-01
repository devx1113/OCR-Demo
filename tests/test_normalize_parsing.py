"""正規化・値のパース・資料の構造化（A1〜A3, B4, B9）。"""
import pymupdf
import pytest
from conftest import SAMPLES

from app import parsing, storage
from app.normalize import (clean_text, display_value, match_model, normalize_component_name, parse_date, parse_dims,
                           parse_length, parse_list, parse_power, parse_qty, parse_temp)


@pytest.mark.parametrize("text,expected", [
    ("W800 × H2000 × D600 mm", {"w": 800, "h": 2000, "d": 600}),
    ("取付板 W700 × H1600 mm", {"w": 700, "h": 1600}),
    ("幅80cm 高さ200cm 奥行60cm", {"w": 800, "h": 2000, "d": 600}),
    ("800x2000x600", {"w": 800, "h": 2000, "d": 600}),
    ("Ｗ８００×Ｈ２０００×Ｄ６００ｍｍ", {"w": 800, "h": 2000, "d": 600}),
])
def test_parse_dims(text, expected):
    assert parse_dims(text) == expected


def test_parse_values():
    assert parse_length("70cm") == {"mm": 700}
    assert parse_length("幅 900mm 以下") == {"mm": 900}
    assert parse_power("AC200V 3φ3W 60Hz") == {"kind": "AC", "v": 200, "phase": 3, "wire": 3, "hz": 60}
    assert display_value("power", parse_power("ＡＣ２００Ｖ　３Φ３Ｗ　５０Ｈｚ"), "") == "AC200V 3φ3W 50Hz"
    assert display_value("power", {"hz": 60}, "") == "60Hz"
    assert parse_temp("0～40℃") == {"min": 0, "max": 40}
    assert parse_qty("1面") == {"n": 1, "unit": "面"}
    assert parse_date("2026年10月6日") == "2026-10-06"
    assert parse_date("11月13日") is None
    assert parse_list("設計、製作、工場試験、運搬を含む。") == ["設計", "製作", "工場試験", "運搬"]
    assert parse_list("現地据付工事、外部配線工事は別途とする。") == ["現地据付工事", "外部配線工事"]
    assert clean_text("受注後5 ヶ月") == "受注後5ヶ月"


def test_model_matching():
    parts = storage.load_master("parts")
    assert match_model("MCB-3P100", parts)["kind"] == "exact"
    assert match_model("ＥＬＢ－３Ｐ５０", parts)["part"]["model"] == "ELB-3P50"   # 全角は半角化して一致
    m = match_model("ELB 3P50", parts)
    assert m["kind"] == "normalized" and m["part"]["model"] == "ELB-3P50"      # 区切り文字の揺れ
    assert match_model("PLC DI16", parts)["part"]["model"] == "PLC-DI16"
    fuzzy = match_model("INV-11KX", parts)
    assert fuzzy["kind"] == "fuzzy" and fuzzy["part"]["model"] == "INV-11K"
    assert match_model("ZZZ-999", parts) is None


def test_component_name_normalization():
    names = storage.load_master("dictionary")["component_names"]
    assert normalize_component_name("MCCB（主幹）", names) == ("配線用遮断器", True)
    assert normalize_component_name("ELCB", names) == ("漏電遮断器", True)
    assert normalize_component_name("インバータ", names) == ("インバータ", False)
    assert normalize_component_name("特殊機器", names) == ("特殊機器", False)


# ---------- 取込時の検査（A3） ----------

def test_inspect_ok_and_scanned():
    assert parsing.inspect(SAMPLES / "送水ポンプ制御盤_製作仕様書.pdf", ".pdf")["status"] == "ok"
    scan = parsing.inspect(SAMPLES / "外形図_スキャン.pdf", ".pdf")
    assert scan["status"] == "warning" and scan["text_layer"] is False
    assert parsing.inspect(SAMPLES / "仕様補足・変更連絡書_No1.docx", ".docx")["status"] == "ok"


def test_inspect_broken_encrypted_and_ole(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 garbage" * 10)
    assert parsing.inspect(broken, ".pdf")["status"] == "error"

    enc = tmp_path / "enc.pdf"
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "secret")
    d.save(enc, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    r = parsing.inspect(enc, ".pdf")
    assert r["status"] == "error" and "パスワード" in r["messages"][0]

    ole = tmp_path / "old.docx"
    ole.write_bytes(parsing.OLE_MAGIC + b"\x00" * 100)
    assert "パスワード" in parsing.inspect(ole, ".docx")["messages"][0]
    assert parsing.inspect(ole, ".txt")["status"] == "error"


# ---------- 構造化 ----------

def test_parse_pdf_tables_and_coordinates():
    parsed = parsing.parse(SAMPLES / "送水ポンプ制御盤_製作仕様書.pdf", "pdf")
    tables = [b for b in parsed["blocks"] if b["type"] == "table"]
    assert len(tables) == 3
    comp = tables[2]
    assert [c["text"] for c in comp["rows"][0]] == ["No", "品名", "型式", "仕様", "数量", "取付位置"]
    assert comp["rows"][2][2]["text"] == "ＥＬＢ－３Ｐ５０"          # 全角のまま（正規化は抽出側）
    assert comp["rows"][1][3]["text"] == "3P 100AF/75AT"             # 空白を保持
    assert all(c["bbox"] for row in comp["rows"] for c in row)       # すべてのセルに座標


def test_parse_pdf_merges_wrapped_lines():
    parsed = parsing.parse(SAMPLES / "顧客回答メール_仕様確認.pdf", "pdf")
    texts = [b["text"] for b in parsed["blocks"] if b["type"] == "para"]
    assert any("保護等級はIP4X相当で問題ございません。" in t for t in texts)
    assert any(t.startswith("次に主回路電源") and t.endswith("大変失礼いたしました。") for t in texts)


def test_guess_meta():
    meta_fields = storage.load_master("dictionary")["meta_fields"]
    main = parsing.guess_meta(parsing.parse(SAMPLES / "送水ポンプ制御盤_製作仕様書.pdf", "pdf"), meta_fields)
    assert main == {"doc_no": "SPEC-2026-0418", "version": "第1版", "issue_date": "2026-10-06",
                    "title": "送水ポンプ制御盤 製作仕様書", "role": "main"}
    sup = parsing.guess_meta(parsing.parse(SAMPLES / "仕様補足・変更連絡書_No1.docx", "docx"), meta_fields)
    assert sup["role"] == "supplement" and sup["issue_date"] == "2026-10-20"
    reply = parsing.guess_meta(parsing.parse(SAMPLES / "顧客回答メール_仕様確認.pdf", "pdf"), meta_fields)
    assert reply["role"] == "supplement" and reply["issue_date"] == "2026-10-24"


def test_parse_xlsx(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["品名", "型式", "数量"])
    ws.append(["補助リレー", "RY-4C", 4])
    path = tmp_path / "list.xlsx"
    wb.save(path)
    parsed = parsing.parse(path, "xlsx")
    table = [b for b in parsed["blocks"] if b["type"] == "table"][0]
    assert [c["text"] for c in table["rows"][1]] == ["補助リレー", "RY-4C", "4"]
