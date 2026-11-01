"""デモ用の架空仕様書を生成する。

- samples/送水ポンプ制御盤_製作仕様書.pdf   … 主仕様書（Word で作成し LibreOffice で PDF 化）
- samples/仕様補足・変更連絡書_No1.docx     … 補足資料（変更一覧・追加機器・矛盾を含む）
- samples/外形図_スキャン.pdf               … テキスト層のない画像 PDF（取込エラー検知のデモ用）
- samples/顧客回答メール_仕様確認.pdf       … 文章だけの回答メール（AI 読解のデモ用）

実行: python scripts/make_samples.py
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"
FONT = "Noto Sans CJK JP"


def new_document() -> Document:
    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Mm(297), Mm(210)
    sec.left_margin = sec.right_margin = Mm(20)
    sec.top_margin = sec.bottom_margin = Mm(18)
    for style_name in ("Normal", "Heading 1", "Heading 2", "Title"):
        st = doc.styles[style_name]
        st.font.name = FONT
        st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    doc.styles["Normal"].font.size = Pt(10)
    for name, size in (("Heading 1", 13), ("Title", 20)):
        doc.styles[name].font.size = Pt(size)
        doc.styles[name].font.bold = True
    return doc


def heading(doc, text):
    p = doc.add_paragraph(text, style="Heading 1")
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(6)


def bullet(doc, text):
    p = doc.add_paragraph("・" + text)
    p.paragraph_format.space_after = Pt(3)


def table(doc, rows, widths, header=True):
    t = doc.add_table(rows=len(rows), cols=len(rows[0]))
    t.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = t.cell(r, c)
            cell.width = Mm(widths[c])
            cell.text = str(val)
            for run in cell.paragraphs[0].runs:
                run.font.size = Pt(9)
                if header and r == 0:
                    run.font.bold = True
    doc.add_paragraph()
    return t


def cover(doc, title, rows):
    for _ in range(4):
        doc.add_paragraph()
    p = doc.add_paragraph(title, style="Title")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()
    table(doc, rows, [40, 120], header=False)


def make_main_spec(tmp: Path) -> Path:
    doc = new_document()
    cover(doc, "送水ポンプ制御盤 製作仕様書", [
        ["件名", "第二浄水場 送水ポンプ設備更新工事"],
        ["発注者", "湊川水道設備株式会社"],
        ["文書番号", "SPEC-2026-0418"],
        ["版", "第1版"],
        ["発行日", "2026年10月6日"],
    ])
    doc.add_page_break()

    heading(doc, "1. 適用範囲")
    doc.add_paragraph("本仕様書は、第二浄水場 送水ポンプ設備更新工事に使用する送水ポンプ制御盤（以下「本盤」という）"
                      "の設計・製作に適用する。本仕様書に記載のない事項は、発注者と協議のうえ決定する。")

    heading(doc, "2. 盤仕様")
    table(doc, [
        ["項目", "仕様"],
        ["盤名称", "送水ポンプ制御盤"],
        ["盤番号", "CP-101"],
        ["数量", "1面"],
        ["形式", "屋内自立形（前面扉 片開き）"],
        ["外形寸法", "W800 × H2000 × D600 mm"],
        ["設置スペース制限", "幅 900mm 以下"],
        ["盤内有効寸法", "取付板 W700 × H1600 mm"],
        ["主回路電源", "AC200V 3φ3W 60Hz"],
        ["制御電源", "AC100V / DC24V"],
        ["塗装色", "マンセル 5Y7/1（内外面とも）"],
        ["周囲温度", "0～40℃"],
        ["準拠規格", "電気設備技術基準、JEM規格"],
    ], [45, 125])

    heading(doc, "3. 構成機器")
    table(doc, [
        ["No", "品名", "型式", "仕様", "数量", "取付位置"],
        ["1", "MCCB（主幹）", "MCB-3P100", "3P 100AF/75AT", "1", "取付板"],
        ["2", "ELCB", "ＥＬＢ－３Ｐ５０", "3P 50AF/30AT 30mA", "2", "取付板"],
        ["3", "インバータ", "INV-7R5", "7.5kW 200V級", "2", "取付板"],
        ["4", "電磁接触器", "MC-25", "AC200V 25A バイパス用", "2", "取付板"],
        ["5", "サーマルリレー", "TH-25", "設定 22A", "2", "取付板"],
        ["6", "PLC CPUユニット", "PLC-CPU32", "32kステップ", "1", "取付板"],
        ["7", "PLC 入力ユニット", "PLC DI16", "DC24V 16点", "2", "取付板"],
        ["8", "PLC 出力ユニット", "PLC-DO16", "リレー出力 16点", "1", "取付板"],
        ["9", "スイッチング電源", "PSU-24V5A", "DC24V 5A", "1", "取付板"],
        ["10", "制御トランス", "TR-1K", "1kVA 200V/100V", "1", "取付板"],
        ["11", "補助リレー", "RY-4C", "DC24V 4c ソケット付", "8", "取付板"],
        ["12", "端子台", "TB-20P", "600V 20A 20P", "6", "取付板"],
        ["13", "表示灯", "PL-22", "φ22 LED 赤/緑", "6", "扉面"],
        ["14", "押しボタンスイッチ", "PB-22", "φ22", "4", "扉面"],
        ["15", "切替スイッチ", "SS-22", "φ22 2ノッチ", "2", "扉面"],
        ["16", "電流計", "AM-80", "80角 0-50A", "2", "扉面"],
        ["17", "タッチパネル", "HMI-7W", "7インチ ワイド", "1", "扉面"],
    ], [10, 36, 38, 46, 12, 22])

    heading(doc, "4. 試験・検査")
    bullet(doc, "工場試験：外観構造検査、絶縁抵抗試験、耐電圧試験、シーケンス動作試験")
    bullet(doc, "立会検査：1回（発注者立会）")

    heading(doc, "5. 見積条件")
    bullet(doc, "見積範囲：設計、製作、工場試験、運搬を含む。")
    bullet(doc, "除外事項：現地据付工事、外部配線工事、試運転調整は別途とする。")
    bullet(doc, "受渡場所：第二浄水場 車上渡し")
    bullet(doc, "納期：受注後5ヶ月")
    bullet(doc, "提出図書：承認図 3部、完成図書 3部")
    bullet(doc, "予備品：補助リレー 2個、ヒューズ 1式")
    bullet(doc, "見積有効期限：提出日より3ヶ月")

    heading(doc, "6. 特記事項")
    bullet(doc, "盤内温度上昇を考慮し、必要に応じて換気ファンを設けること。")
    bullet(doc, "塗装は焼付塗装とする。")
    bullet(doc, "銘板はアクリル製（白地黒文字）とする。")
    bullet(doc, "将来増設用として、取付板に15%程度の予備スペースを確保すること。")

    path = tmp / "送水ポンプ制御盤_製作仕様書.docx"
    doc.save(path)
    return path


def make_supplement() -> Path:
    doc = new_document()
    p = doc.add_paragraph("仕様補足・変更連絡書 No.1", style="Title")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    table(doc, [
        ["件名", "第二浄水場 送水ポンプ設備更新工事"],
        ["文書番号", "SPEC-2026-0418-S1"],
        ["版", "第1版"],
        ["発行日", "2026年10月20日"],
    ], [40, 120], header=False)
    doc.add_paragraph("製作仕様書（SPEC-2026-0418 第1版）について、下記のとおり変更・追加する。")

    heading(doc, "1. 変更一覧")
    table(doc, [
        ["No", "対象", "変更前", "変更後", "理由"],
        ["1", "構成機器 No.3 インバータ 型式", "INV-7R5（7.5kW）", "INV-11K（11kW）", "ポンプ容量見直しのため"],
        ["2", "構成機器 No.11 補助リレー 数量", "8個", "10個", "監視信号追加のため"],
        ["3", "盤仕様 外形寸法 奥行", "60cm", "70cm", "搬入経路確認の結果"],
    ], [10, 52, 32, 32, 44])

    heading(doc, "2. 追加機器")
    table(doc, [
        ["No", "品名", "型式", "仕様", "数量", "取付位置"],
        ["18", "盤内灯", "LED-10W", "LED 10W ドアスイッチ連動", "1", "取付板"],
        ["19", "コンセント", "OUT-2P", "AC100V 2P15A", "1", "取付板"],
        ["20", "SPD", "SPD-3P", "AC200V 3相用", "1", "取付板"],
    ], [10, 36, 38, 46, 12, 22])

    heading(doc, "3. その他")
    bullet(doc, "主回路電源：AC200V 3φ3W 50Hz")
    bullet(doc, "見積提出期限：2026年11月13日")

    path = OUT / "仕様補足・変更連絡書_No1.docx"
    doc.save(path)
    return path


def make_customer_reply(tmp: Path) -> Path:
    """顧客からの回答メール（文章のみ・表なし）。ルールでは拾えず、AI 読解で値を取り出せることを示す。"""
    doc = new_document()
    p = doc.add_paragraph("仕様確認のご回答", style="Title")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    table(doc, [
        ["差出人", "湊川水道設備株式会社 工務部 設備課 高橋"],
        ["送付先", "株式会社サンプル制御システム 営業部 山田様"],
        ["日付", "2026年10月24日"],
        ["表題", "Re: 送水ポンプ制御盤 製作仕様に関するお問い合わせ"],
    ], [30, 130], header=False)
    for text in (
        "株式会社サンプル制御システム 山田様",
        "いつも大変お世話になっております。湊川水道設備の高橋でございます。",
        "先日お問い合わせいただいた送水ポンプ制御盤（CP-101）の仕様につきまして、下記のとおりご回答いたします。",
        "まず盤の保護構造についてですが、本盤は屋内の電気室に設置いたしますので、保護等級はIP4X相当で問題ございません。",
        "次に主回路電源につきましては、AC200V 3φ3W 60Hzが正となります。先日お送りした変更連絡書No.1に記載の50Hzは"
        "弊社の誤記でございました。大変失礼いたしました。",
        "なお、立会検査は1回の予定で変更ございません。日程は製作工程が固まり次第、別途ご相談させてください。",
        "お見積書は11月13日までにご提出いただけますと幸いです。",
        "以上、何卒よろしくお願い申し上げます。",
    ):
        para = doc.add_paragraph(text)
        para.paragraph_format.space_after = Pt(8)
    path = tmp / "顧客回答メール_仕様確認.docx"
    doc.save(path)
    return path


def to_pdf(src: Path, dest: Path):
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", td, str(src)],
                       check=True, capture_output=True)
        shutil.move(Path(td) / (src.stem + ".pdf"), dest)


def make_scanned_drawing() -> Path:
    """外形図を描いてラスタ化し、テキスト層のない画像PDFにする。"""
    src = pymupdf.open()
    page = src.new_page(width=842, height=595)
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(40, 40, 802, 555))
    shape.draw_rect(pymupdf.Rect(300, 90, 500, 500))
    shape.draw_rect(pymupdf.Rect(300, 480, 500, 500))
    shape.draw_rect(pymupdf.Rect(560, 90, 640, 500))
    shape.draw_line((300, 520), (500, 520))
    shape.draw_line((280, 90), (280, 500))
    shape.finish(color=(0, 0, 0), width=1.2)
    shape.commit()
    page.insert_text((380, 535), "W800", fontsize=12)
    page.insert_text((235, 300), "H2000", fontsize=12)
    page.insert_text((585, 520), "D600", fontsize=12)
    page.insert_text((620, 545), "OUTLINE DRAWING  CP-101  SCALE 1:20", fontsize=9)
    pix = page.get_pixmap(dpi=110)
    out = pymupdf.open()
    img_page = out.new_page(width=842, height=595)
    img_page.insert_image(img_page.rect, stream=pix.tobytes("jpg", jpg_quality=70))
    path = OUT / "外形図_スキャン.pdf"
    out.save(path)
    return path


def main():
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        src = make_main_spec(Path(td))
        to_pdf(src, OUT / "送水ポンプ制御盤_製作仕様書.pdf")
        to_pdf(make_customer_reply(Path(td)), OUT / "顧客回答メール_仕様確認.pdf")
    make_supplement()
    make_scanned_drawing()
    for f in sorted(OUT.iterdir()):
        print(f.name, f.stat().st_size)


if __name__ == "__main__":
    main()
