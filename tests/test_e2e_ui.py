"""ブラウザで画面を操作し、デモシナリオ全体が動くことを確認する（E2E）。

    pytest -m e2e                       # AI が設定されていれば AI 機能も含めて検証
    CHROME_PATH=/usr/bin/google-chrome pytest -m e2e   # 既存の Chrome を使う場合

案件データは一時ディレクトリに保存するため、実際の案件には影響しない。
"""
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[1]
AI = bool(os.environ.get("OPENAI_API_KEY")) or (ROOT / ".env").exists()


@pytest.fixture(autouse=True)
def isolated_data():
    """conftest の同名フィクスチャを無効化（サーバーは別プロセスで、専用ディレクトリを使う）。"""


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    # E2E_BASE_URL を指定すると、起動済みの環境（例：docker compose の http://localhost:8088、空のデータベース）を検証する
    if os.environ.get("E2E_BASE_URL"):
        yield os.environ["E2E_BASE_URL"].rstrip("/")
        return
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        pytest.skip("フロントエンド未ビルド（cd frontend && npm run build）")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    master = tmp_path_factory.mktemp("e2e") / "master"
    shutil.copytree(ROOT / "backend" / "data" / "master", master, ignore=shutil.ignore_patterns("_versions"))
    env = {**os.environ, "PANEL_PROJECTS_DIR": str(tmp_path_factory.mktemp("e2e_projects")), "PANEL_MASTER_DIR": str(master)}
    proc = subprocess.Popen([sys.executable, str(ROOT / "run.py"), "--port", str(port), "--no-browser"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1)
            break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("サーバーが起動しませんでした")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def page(server):
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        kw = {"executable_path": os.environ["CHROME_PATH"]} if os.environ.get("CHROME_PATH") else {}
        browser = p.chromium.launch(**kw)
        ctx = browser.new_context(viewport={"width": 1600, "height": 960}, accept_downloads=True)
        pg = ctx.new_page()
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        yield pg
        browser.close()


def test_full_demo_scenario(server, page):
    from playwright.sync_api import expect
    from openpyxl import load_workbook

    pg = page
    pg.goto(server + "/#/")
    expect(pg.get_by_text("仕様書から見積書まで")).to_be_visible()
    ai_on = json.load(urllib.request.urlopen(server + "/api/health"))["ai"]["enabled"]
    if AI:
        assert ai_on, ".env に API キーがあるのに AI が無効になっています"
        expect(pg.locator(".ai-pill:not(.off)")).to_be_visible()
    print(f"AI 機能の検証: {'あり' if ai_on else 'なし（ルール抽出のみ）'}")

    # 1. デモ案件 → 解析演出 → 抽出・確認
    pg.get_by_test_id("demo-button").click()
    # AI が有効ならスキャン図面も AI-OCR の対象になる
    expect(pg.get_by_test_id("doc-sheet")).to_have_count(3 if ai_on else 2, timeout=15000)
    pg.get_by_role("button", name="抽出結果を確認する").click(timeout=180000)
    expect(pg).to_have_url(re.compile(r"/review$"))
    expect(pg.locator(".rv-issue", has_text="主回路電源")).to_be_visible()
    if ai_on:
        expect(pg.locator(".badge-ai", has_text="AI 読解済み")).to_be_visible()

    # 2. 矛盾をクリック → 候補と原文ハイライト
    pg.locator(".rv-issue", has_text="主回路電源").first.click()
    expect(pg.locator('[data-field="main_power"] .cand')).to_have_count(2)
    expect(pg.locator(".hl-block, .hl").first).to_be_visible()

    # 3. AI に質問（出典付き）→ 別のステップへ移動できること（画面切替が止まらない）
    if ai_on:
        pg.get_by_role("tab", name="AIに質問").click()
        pg.locator(".suggest").first.click()
        expect(pg.locator(".bubble.assistant")).to_have_count(1, timeout=90000)
        expect(pg.locator(".bubble.assistant .chip").first).to_be_visible()
        pg.locator(".bubble.assistant .chip").first.click()
    pg.locator(".step", has_text="資料").first.click()
    expect(pg.locator(".dropzone")).to_be_visible(timeout=5000)

    # 4. 文章だけの回答メールを追加 → 再解析 → AI が保護等級を読み取る
    if ai_on:
        pg.get_by_role("button", name="顧客回答メールを追加").click()
        expect(pg.locator(".doc-card")).to_have_count(4, timeout=20000)
        pg.locator(".card-foot").get_by_role("button", name="再解析").click()
        pg.get_by_role("button", name="抽出結果を確認する").click(timeout=180000)
        pg.get_by_role("tab", name="盤仕様").click()
        row = pg.locator('[data-field="protection"]')
        expect(row.locator(".frow-value")).to_contain_text("IP4X")
        expect(row.locator(".method.ai")).to_be_visible()
    else:
        pg.locator(".step", has_text="抽出・確認").click()
        pg.get_by_role("tab", name="盤仕様").click()
        pg.locator('[data-field="protection"]').click()
        pg.locator('[data-field="protection"]').get_by_role("button", name="値を入力").click()
        pg.get_by_label("保護等級の値").fill("IP4X")
        pg.locator('[data-field="protection"]').get_by_role("button", name="保存").click()

    # 5. 矛盾の解決（主仕様書の 60Hz を採用）
    pg.locator('[data-field="main_power"]').click()
    pg.locator('[data-field="main_power"] .cand', has_text="60Hz").first.get_by_role("button", name="採用").click()
    expect(pg.locator('[data-field="main_power"]').get_by_text("解決済")).to_be_visible()

    # 6. 収容判定：不可 → AI 設計レビュー → 代替筐体で可
    pg.locator(".step", has_text="収容判定").click()
    expect(pg.get_by_test_id("verdict")).to_contain_text("収容不可")
    expect(pg.get_by_test_id("layout-svg")).to_be_visible()
    if ai_on:
        pg.get_by_role("button", name="AI レビューを実行").click()
        expect(pg.locator(".finding").first).to_be_visible(timeout=180000)
    pg.get_by_role("button", name="この筐体で見積る").first.click()
    expect(pg.get_by_test_id("verdict")).to_contain_text("収容可", timeout=10000)
    expect(pg.get_by_text("採用中の代替案")).to_be_visible()

    # 7. 見積：利益率を変えると金額が変わる
    pg.locator(".step", has_text="見積").first.click()
    hero = pg.get_by_test_id("price-hero")
    expect(hero).to_contain_text("¥")
    pg.wait_for_timeout(1500)
    before = hero.locator(".v").inner_text()
    slider = pg.get_by_label("利益率")
    slider.focus()
    for _ in range(10):
        slider.press("ArrowRight")
    pg.wait_for_timeout(2500)
    assert hero.locator(".v").inner_text() != before
    # 類似過去案件：同じ顧客・用途の送水ポンプ盤が最上位、金額の範囲内での位置
    expect(pg.get_by_test_id("similar-case").first).to_contain_text("Q2025-0188")
    expect(pg.get_by_test_id("similar-card")).to_contain_text("類似上位 3 件の範囲")

    # 8. 出力・承認：判子演出 → Excel 出力
    pg.locator(".step", has_text="出力・承認").click()
    # 設計担当が承認を依頼 → 設計課長に切り替えて承認
    pg.get_by_role("button", name="承認を依頼").click()
    expect(pg.locator(".ap-note.requested")).to_be_visible()
    pg.locator(".user-box").click()
    pg.locator(".user-menu button", has_text="佐藤 花子").click()
    pg.get_by_role("button", name="承認する").click()
    expect(pg.locator(".stamp-stage")).to_be_visible()
    expect(pg.get_by_test_id("approved")).to_be_visible()
    with pg.expect_download() as dl:
        pg.get_by_role("button", name="見積書（Excel）を出力").click()
    wb = load_workbook(io.BytesIO(Path(dl.value.path()).read_bytes()))
    assert wb["御見積書"]["B4"].value == "湊川水道設備株式会社"
    assert wb["御見積書"]["H1"].value in ("", None)                 # 承認済みのためドラフト表示なし
    with pg.expect_download() as dl2:
        pg.get_by_role("button", name="質疑書（Excel・", exact=False).click()
    assert dl2.value.suggested_filename.startswith("質疑書_")
    with pg.expect_download() as dl3:
        pg.get_by_role("button", name="見積明細（販売管理・ERP）を出力").click()
    assert dl3.value.suggested_filename.startswith("見積明細_") and dl3.value.suggested_filename.endswith(".csv")
    expect(pg.get_by_test_id("pdf-preview").locator("canvas").first).to_be_visible(timeout=60000)

    # 9. AI メール文案
    if ai_on:
        pg.get_by_role("button", name="送付メールを AI で作成").click()
        pg.get_by_role("button", name="見積提出メール").click()
        body = pg.get_by_label("本文")
        expect(body).to_be_visible(timeout=90000)
        assert "湊川水道設備" in body.input_value()
        pg.keyboard.press("Escape")

    # 10. 収容判定に対する設計者の最終判断（判定一致率）
    pg.locator(".step", has_text="収容判定").click()
    pg.get_by_test_id("fit-agree").click()
    expect(pg.get_by_test_id("fit-decision")).to_contain_text("判定どおり")

    # 11. 履歴・マスタ（ルール変更の影響確認と版）
    pg.locator(".step", has_text="履歴").click()
    expect(pg.locator(".tl-item", has_text="承認").first).to_be_visible()
    pg.goto(server + "/#/master/rules")
    pg.get_by_label("鋼材指数（現在）").fill("110")
    pg.get_by_test_id("rules-save").click()
    expect(pg.locator(".imp-kpis")).to_contain_text("結果が変わる案件")
    expect(pg.locator(".imp-table")).to_contain_text("自動では再計算しません")      # 承認済みの見積は守る
    pg.get_by_test_id("impact-save").click()
    pg.get_by_test_id("versions-rules").click()
    expect(pg.locator(".ver").first).to_contain_text("鋼材指数 100→110")
    pg.keyboard.press("Escape")
    pg.goto(server + "/#/master/learning")
    expect(pg.get_by_text("未判断", exact=False)).to_be_visible()
    pg.goto(server + "/#/master/parts")
    expect(pg.get_by_text("INV-11K")).to_be_visible()
    pg.goto(server + "/#/master/ai")
    expect(pg.get_by_text("使用するモデル")).to_be_visible()
    if ai_on:
        pg.get_by_role("button", name="接続テスト").click()
        expect(pg.get_by_text("接続OK", exact=False)).to_be_visible(timeout=60000)
    pg.goto(server + "/#/report")
    expect(pg.get_by_text("自動抽出値の採用率")).to_be_visible()
    pg.goto(server + "/#/report/effect")
    expect(pg.get_by_text("見積作成時間の削減率")).to_be_visible()
    pg.goto(server + "/#/report/fit")
    expect(pg.locator(".kpi", has_text="判定一致率")).to_contain_text("100.0")
    pg.goto(server + "/#/report/regression")
    pg.get_by_role("button", name="チェックを実行").click()
    expect(pg.get_by_text("結果が変わる案件", exact=False)).to_be_visible()
    pg.goto(server + "/#/")
    expect(pg.locator("tbody tr")).to_have_count(1)
    expect(pg.locator("tbody tr")).to_contain_text("出力済")
    assert pg.errors == []


def test_upload_errors_and_manual_project(server, page):
    from playwright.sync_api import expect

    pg = page
    pg.goto(server + "/#/")
    pg.get_by_role("button", name="新規案件").first.click()
    pg.get_by_placeholder("例：〇〇工場 動力制御盤").fill("取込テスト")
    pg.get_by_role("button", name="作成して資料を登録").click()
    expect(pg.locator(".dropzone")).to_be_visible()
    samples = ROOT / "samples"
    pg.locator("input[type=file]").set_input_files([str(samples / "送水ポンプ制御盤_製作仕様書.pdf"), str(samples / "外形図_スキャン.pdf")])
    expect(pg.locator(".doc-card")).to_have_count(2, timeout=20000)
    expect(pg.locator(".ocr-cta, .ocr-panel").first).to_contain_text("AI-OCR")          # 画像PDF は AI-OCR の対象
    pg.locator("input[type=file]").set_input_files(str(samples / "送水ポンプ制御盤_製作仕様書.pdf"))
    expect(pg.locator(".toast.error")).to_contain_text("既に登録")
    pg.locator(".card-foot").get_by_role("button", name="解析を実行").click()
    pg.get_by_role("button", name="抽出結果を確認する").click(timeout=180000)
    pg.locator(".step", has_text="収容判定").click()
    expect(pg.get_by_test_id("verdict")).to_contain_text("収容可")      # 変更連絡がなければ W800 に収まる


def test_layout_at_projector_width_and_missing_project(server, page):
    """1024×768（会議室のプロジェクターで多い解像度）でも、横スクロールや列のつぶれが起きないこと。"""
    from playwright.sync_api import expect

    pg = page
    pid = json.load(urllib.request.urlopen(urllib.request.Request(server + "/api/projects/demo", method="POST")))["id"]
    pg.set_viewport_size({"width": 1024, "height": 768})
    try:
        for tab in ("review", "fit", "estimate", "output"):
            pg.goto(server + f"/#/projects/{pid}/{tab}")
            pg.wait_for_timeout(1200)
            assert pg.evaluate("document.documentElement.scrollWidth") <= 1024, tab
        card = pg.locator(".card", has_text="出力前チェック").first
        assert card.bounding_box()["width"] > 600                      # 以前は約 150px につぶれて縦書き状になっていた
        pg.goto(server + f"/#/projects/{pid}/review")
        expect(pg.get_by_role("tab", name="AIに質問")).to_be_in_viewport()
        # 存在しない案件へ移動すると、サイドバーに前の案件が残らない
        pg.goto(server + "/#/projects/000000000000/review")
        expect(pg.get_by_text("案件が見つかりません")).to_be_visible()
        expect(pg.locator(".project-chip")).to_have_count(0)
    finally:
        pg.set_viewport_size({"width": 1600, "height": 960})
