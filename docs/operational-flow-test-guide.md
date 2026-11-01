# 制御盤見積アシスタント — Hands-on Test Guide

Run this guide as the client's staff would. Create a new 見積案件, register the customer's files yourself, and take the project through every step to an approved Excel quote. One full pass takes about 40 minutes.

## Before you start

The app runs in Docker at http://localhost:8088, with data in PostgreSQL. Open it in Chrome, full screen, at 1280 px wide or more.

- **If it is not running:** run `docker compose up -d` in the project folder. Without Docker, run `./start.sh` (or `start.bat` on Windows) and open http://127.0.0.1:8000; that mode saves to JSON files instead.
- **AI connection:** the bottom-left of the sidebar should read 「AI 接続中 gpt-5.4-mini」. If it reads 「AI 未接続」 or 「AI 接続エラー」, open マスタ・設定 → AI 設定 and press 接続テスト.
- **Sample files:** use the four fictional customer files in the project's `samples/` folder. You can also download them from the 「デモ用サンプル資料」 panel on a project's 資料 tab.
    - 送水ポンプ制御盤_製作仕様書.pdf: the main specification
    - 仕様補足・変更連絡書_No1.docx: a change notice
    - 外形図_スキャン.pdf: a scanned drawing with no text layer
    - 顧客回答メール_仕様確認.pdf: the customer's reply email, kept back until step 3
- **Your data:** test projects are saved next to your existing project. Always create new projects for testing, and delete them from 案件一覧 when you finish.
- **Roles:** switch the person by clicking the name at the bottom-left. 山田 太郎 (設計担当) does steps 1–5, 佐藤 花子 (設計課長) approves in step 6, and 鈴木 一郎 (営業担当) is used in one edge case.
- **Cost:** AI reading of three files uses about 10,000–15,000 tokens. Results are cached per file, so re-analysing does not charge again. Only the AI design review and the email drafts make new calls each time.
- **Shortcut:** the dashboard's 「デモ案件で体験する」 button performs step 1 automatically. Use it for a quick rerun; use the manual path below for the real test.

## The flow at a glance

The client's process has five steps and one gate. A designer works through steps 1–4, and a manager approves only when no blocking issue is left. The tabs in each project's header follow the same order, and 履歴 records every action along the way.

```
                  ┌──────── No: correct values, adopt a candidate, or send to 質疑書 ────────┐
                  ▼                                                                          │
┌──────────┐   ┌──────────────┐   ┌────────────┐   ┌──────────┐                   ┌──────────────────┐
│ 1 資料    │──▶│ 2 抽出・確認  │──▶│ 3 収容判定  │──▶│ 4 見積    │──────────────────▶│  Blocking = 0 ?  │
│ Register │   │ Review values │   │ Fit check  │   │ Estimate │                   └──────────────────┘
└──────────┘   └──────────────┘   └────────────┘   └──────────┘                            │ yes
     ▲                ▲                                                                    ▼
     │ 追加して再解析   ┆                                                         ┌──────────────────┐
┌──────────┐          ┆          ┌──────────────┐   ┌──────────────────────┐    │ 5 承認            │
│ 顧客の回答 │          ┆          │ 送付メール     │◀──│ 出力                  │◀───│ 設計課長 approves │
│ Reply    │          ┆          │ AI drafts it │   │ Excel, 質疑書, 根拠書  │    └──────────────────┘
└──────────┘          ┆          └──────────────┘   └──────────────────────┘             ┆
                      └┄┄┄┄┄┄┄┄ Any edit after approval cancels it and sends you back ┄┄┄┄┘
```

The loops are what to test hardest. Open issues send you back to review, and any edit after approval cancels it. The customer's reply re-enters as a new file.

## Step-by-step walkthrough

Each step lists what to do, then what you should see. Tick a check when it behaves as described. Anything else is a finding to report (see the last section). The bracketed IDs refer to the client's requirement list.

### Step 1 — Create the project and register the files (A1–A3)

As 山田 太郎:

1. On 見積案件, press 新規案件. Enter 案件名 (for example 第二浄水場 送水ポンプ制御盤), 顧客名 and a 見積提出期限 about two weeks ahead. Press 作成して資料を登録.
2. Drag three files onto the drop area together: the main specification PDF, the change notice .docx and the scanned drawing. Keep the customer email for step 3.
3. Drop the main specification PDF a second time.
4. Press 解析を実行 and watch the full-screen analysis. It takes 15–40 seconds with AI on.

Check:

- [ ] The header shows the quote number, the status 確認中 and a deadline countdown such as 「あと 14 日」.
- [ ] Each file shows its type (主仕様書 / 補足資料 / 図面), version and received date, read from its cover page.
- [ ] The scanned drawing is read by AI-OCR: its analysis card shows 「文字 6行・寸法 3件」, and its 資料 card shows the dimensions H2000, W800 and D600.
- [ ] The second copy of the PDF is rejected as a duplicate.
- [ ] Changing a file's type, or unticking 解析対象に含める, marks the analysis as needing a rerun. Put it back afterwards.
- [ ] The analysis screen counts files read, matches between rules and AI, and AI values checked against the source text.

### Step 2 — Review the extracted values (B1–B7, F1)

This is the client's core concern: every value must be traceable to the document it came from. The 抽出・確認 step opens with three blocking issues, listed under 「承認前に解決」:

- 主回路電源：資料間で値が異なります (60 Hz in the specification, 50 Hz in the change notice)
- 保護等級：記載が見つかりません
- 収容判定：不可

Check on the 盤仕様 tab:

- [ ] Clicking a value's source chip opens the original document with the source line highlighted.
- [ ] 主回路電源 temporarily uses 50 Hz, because the change notice is newer, and shows both candidates.
- [ ] 外形寸法 reads 800 × 2000 × 700 mm. The change notice's "60 cm → 70 cm" depth has been converted to mm.
- [ ] 設置場所 shows 屋内 and is marked as inferred, not stated.
- [ ] Values read the same way by the rules and by AI carry a 「ルール×AI 一致」 badge.

Check on the 構成機器 tab:

- [ ] "MCCB" has been normalised to 配線用遮断器, and full-width model numbers are corrected.
- [ ] The inverter has changed from 7.5 kW to 11 kW (INV-11K) per the change notice, with the before value shown.
- [ ] 盤内照明 appears as added by the change notice. サージ防護デバイス has no unit price yet.

Check the scanned drawing (A4, A5):

- [ ] 要確認 lists 「外形図：仕様と寸法が異なります」 (depth 600 on the drawing, 700 in the spec).
- [ ] On 盤仕様 → 外形寸法, the box 「図面（AI-OCR）との照合」 shows 幅 800 ✓, 高さ 2000 ✓ and a red 奥行 600 ≠ 700. It says the drawing matches the value before the change notice.
- [ ] Clicking the red chip opens the scan with a frame around 「D600」.
- [ ] The 質疑書 gains a question asking the customer for the latest drawing.

Try these edits, then undo each one:

1. Correct a value with 修正, entering a reason. It becomes 修正済 and the reason appears in 履歴. Undo with 自動抽出に戻す.
2. Change a component quantity, for example 端子 from 10 to 12.
3. Use 機器を手動で追加 twice: once with a model that is in the parts master, once with an invented model. The invented one should turn the fit check to 情報不足, without errors. Delete both.
4. Open 「AIに質問」 and press 「主回路電源の周波数は結局どちらが正しい？」. The answer should cite the source lines. Then ask 「盤の重量は？」, which the documents do not answer. It should reply that there is no mention rather than guess.

### Step 3 — Add the customer's reply and resolve the issues (B5, B6)

In real work the customer answers questions by email. This step tests that the system reads plain prose.

1. On the 資料 tab, drop 顧客回答メール_仕様確認.pdf, then press 再解析. Only the new file is read by AI.
2. In 抽出・確認, open 保護等級 and press この値で確定.
3. Open 主回路電源 and press 採用 on the 60 Hz candidate.

Check:

- [ ] A 「AI が見つけた訂正・確定」 item at the top quotes the email saying 50 Hz was the customer's typo.
- [ ] 保護等級 changes from 記載なし to IP4X相当, marked as read by AI only, with the sentence it came from.
- [ ] After confirming both, only 収容判定：不可 remains blocking.

On a second project without the email, try 質疑書で確認 on 保護等級 instead. It should become 質疑回答待ち (not blocking), and a question should be added to the 質疑書.

### Step 4 — Check that everything fits in the panel (C1–C7)

The client separates two questions: can the program compare dimensions, and does that match the designer's judgment. This step tests the first and shows the reasoning a designer would need to check the second.

1. Open 収容判定. The verdict is stamped 「不可」.
2. Press 「AI レビューを実行」. It takes 20–40 seconds.
3. Under 代替筐体の候補, press この筐体で見積る on the W900 enclosure.
4. Toggle the recommended fan (FAN-250) out of the estimate and back in.

Check:

- [ ] 判定根拠 lists each check with its measured value, limit and the rule used. The plate-usage limit is 85%, because the specification asks for 15% spare space.
- [ ] 配置シミュレーション draws the devices dropping into rows and shows them overrunning the mounting plate by 285 mm.
- [ ] 温度上昇 shows total heat of 965 W, with the formula, and recommends FAN-250.
- [ ] The AI review raises points the rules cannot, for example breaker capacity for two 11 kW inverters. 該当箇所を見る jumps to the component.
- [ ] With W900 chosen, the stamp changes to 「可」 and the spec's own enclosure is shown for comparison. A 仕様変更のご提案 is added to the 質疑書, and a condition is added to the estimate.
- [ ] The header status changes to 確認完了 and no blocking issues remain. 仕様書指定に戻す would undo the change.
- [ ] 類似案件の最終盤サイズ lists the sizes used on similar past jobs, with the current one highlighted. The closest case, Q2025-0188, notes that W800 was changed to W900.
- [ ] In 設計者の最終判断, press 判定どおりで良い. The card shows the system's verdict and yours side by side. Try 異なる判断を記録 on another project: the reason is required.

### Step 5 — Build the estimate (D1–D4)

The client has not decided how far the amount should be calculated automatically. Check that every number can be explained and overridden.

- [ ] 御見積金額 counts up. Hovering the 原価構成 chart shows the amount for each category.
- [ ] Moving the 利益率 slider changes the selling price and gross profit at once. The selling price is rounded to the nearest ¥10,000, and tax is 10%.
- [ ] Clicking a quantity or unit price lets you edit it. The line is marked 修正済, and 元に戻す restores it.
- [ ] Labour lines show their basis. Test hours include the witnessed-inspection surcharge (16 h), and documentation is 2 types × 4 h.
- [ ] 見積依頼・単価確認 lists サージ防護デバイス and 予備品 ヒューズ as unpriced, and 制御用変圧器 as expired. リストをコピー pastes cleanly into Excel.
- [ ] Entering a price for an unpriced item removes it from that list.
- [ ] 類似過去案件 lists five past jobs. Each shows a similarity score, what matched (green) and what differed (amber). The top one is Q2025-0188, a two-pump panel for the same customer.
- [ ] The bar above the list shows where this quote sits within the range of the three closest jobs, and says whether it is inside that range.

### Step 6 — Approve and output the quote (E1–E3, F2, F5)

1. Open 出力・承認 as 山田 太郎. 出力前チェック should read 承認可能. There is no 承認する button for a designer.
2. Add a comment and press 承認を依頼. The flow shows 作成・確認 ✓ → 承認依頼 ✓, and the status becomes 承認待ち.
3. Switch the user to 佐藤 花子. The dashboard shows 「あなたの承認待ち」 with this project. Press 確認して承認.
4. Optional: type a reason and press 差戻し. The status becomes 差戻し, and 山田 太郎 sees it on the dashboard. Request again as 山田, then switch back to 佐藤.
5. Press 承認する. A stamp and petals appear, the status becomes 承認済, and the card shows 「第1版」.
6. Download 見積書（Excel） and open it in Excel.
7. Download the 質疑書 and 見積根拠書（Excel・社内用）.
8. Under 他システム連携（CSV）, download both CSV files.
9. Press 「送付メールを AI で作成」 and try both 見積提出メール and 質疑確認メール.
10. Go back to 抽出・確認 and change any quantity. Then return to 出力・承認.

Check:

- [ ] The Excel quote keeps the template's layout, merged cells and formulas. It contains the approver, conditions and question numbers. Its totals match the screen.
- [ ] After the download the status becomes 出力済.
- [ ] 見積書プレビュー shows a PDF of the quote. This needs LibreOffice; without it, a message says so and Excel output still works.
- [ ] The 質疑書 lists the open questions by category. The 見積根拠書 shows each value's source, the AI match, the fit reasoning, the cost breakdown and the history.
- [ ] The email draft uses the real amount, quote number and conditions in polite business Japanese. メールソフトで開く opens your mail client.
- [ ] Editing after approval cancels the approval automatically, and the history records it.
- [ ] Both CSV files open cleanly in Excel. The 見積明細 total matches the screen's 税込合計. The 手配リスト shows maker, model, quantity and cost, with unpriced items marked 要見積.

### Step 7 — Check versions, history, reports and master data (F2, F3, F7, F8, C13, D8, G)

- [ ] Approve again as 佐藤 花子 after the change in step 6. 履歴 → 見積の版 shows 第1版 and 第2版, with the amount, line, part and condition differences between them.
- [ ] 履歴 lists every action from steps 1–6 with who, when and the reason entered. It can be filtered by person.
- [ ] The sidebar's 精度レポート shows the share of extracted values used without correction, the fields people corrected, and counts of conflicts, changes, missing values and drawing mismatches.
- [ ] In マスタ・設定 → 部品マスタ, change one part's price and save as 佐藤 花子 (山田 太郎 is refused). After 再解析, the project's estimate reflects it.
- [ ] In 判定・算定ルール, switch 「資料間で値が異なる場合の仮採用ルール」 to 主仕様書を仮採用. On a fresh project, 主回路電源 should now provisionally show 60 Hz.
- [ ] In 判定・算定ルール → 市況係数, set 鋼材指数（現在） to 115 and 為替（現在） to 165, then press 影響を確認して保存. Before anything is saved, the dialog lists each affected project and its change in amount. An approved quote is marked 自動では再計算しません.
- [ ] After saving, open the project's 見積 tab. A 市況係数を反映中 card shows the added amount, and only the enclosure and imported parts (inverter, touch panel) carry the 市況係数 mark.
- [ ] 変更履歴 lists 第1版 (初期データ) and 第2版 with who changed what. この版に戻す restores the earlier values as a new version.
- [ ] On a separate project, add a component with model `INV11KW`, then correct its model to `INV-11K`. 改善候補 now suggests adding INV11KW as another notation for INV-11K. After 反映する, entering INV11KW on any project matches the master directly.
- [ ] 精度・効果レポート → 効果測定 shows the estimated working time per project against the 6-hour baseline. 判定一致率 shows your fit decisions. 回帰チェック → チェックを実行 lists projects whose saved results differ from the current rules.
- [ ] Restore every master value you changed before moving on (変更履歴 → この版に戻す).

## Edge cases worth trying

These are the situations the client's staff will hit in their first week. Use a separate project for each one, so the main run stays clean.

| Situation | How to set it up | What should happen |
| --- | --- | --- |
| Output before resolving issues | Right after step 2, open 出力・承認 | 出力前チェック lists the open items. 承認 is refused. 注意書き付きで出力 gives an Excel file marked ドラフト |
| Main specification only | Register only the main specification PDF and analyse it | No frequency conflict, and the fit check is 「可」 |
| Wrong file extension | Rename a .docx to .pdf and upload it | 取込エラー saying the content is actually Word |
| Empty Word file | Upload a blank .docx | A warning, the type set to その他, and nothing extracted |
| Formula typed as text | Set 顧客名 to `=1+1` with 修正, then export | The Excel cell shows the text `=1+1`, not 2 |
| AI switched off | マスタ・設定 → AI 設定, untick AI, reload the page | The full flow still works with rules only. AI buttons are disabled with an explanation |
| No network | Disconnect Wi-Fi, then analyse a new project | AI reading stops after about 20 seconds. The sidebar shows 「AI 接続エラー」, and the analysis still finishes |
| Projector screen | Set the browser window to 1024 × 768 | The sidebar shrinks to icons. Nothing scrolls sideways |
| Sales user | Switch to 鈴木 一郎 (営業担当) and open a project | A 閲覧モード banner appears. Edits and approval are refused with a message. Approved quotes and the 質疑書 can still be exported |
| Two people at once | Open the same project in two browsers as different users, and edit in one | Within about 8 seconds the other shows 「○○ さんがこの案件を更新しました」. Editing from the stale screen loads the latest content instead of overwriting |
| Edit while waiting for approval | Request approval, then change a quantity | The request is withdrawn automatically and must be sent again |

Turn AI back on and reconnect the network when you finish.

## Results by requirement

Record one result per requirement as you go: Pass, Fail, or **Discuss** for anything that works but differs from what the client would expect.

| ID | What to confirm | Step | Result |
| --- | --- | --- | --- |
| A1 | Several files register under one project | 1 | |
| A2 | Type, version and received date are recorded per file | 1 | |
| A3 | Duplicate, mislabelled and empty files are flagged | 1, edge cases | |
| A4–A5 | The scanned drawing's text and dimensions are read and checked against the spec | 1, 2 | |
| B1 | Panel specifications are extracted, with dimensions in mm | 2 | |
| B2 | Component name, model and quantity are extracted and normalised | 2 | |
| B3 | 見積条件 shows scope and exclusions (現地据付工事, 外部配線工事, 試運転調整) | 2 | |
| B4 | cm becomes mm, and aliases become standard names | 2 | |
| B5 | Missing values (保護等級) are flagged as needing confirmation | 2, 3 | |
| B6 | The 60 / 50 Hz conflict is flagged and resolved by a person | 2, 3 | |
| B7 | Every value opens its source with the line highlighted | 2 | |
| C1 | Model numbers are looked up in the parts master | 2 | |
| C2–C4 | Dimension checks and the row layout are correct and explained | 4 | |
| C5 | Heat rise and fan selection are shown with the formula | 4 | |
| C6 | The verdict is 可 / 不可 / 情報不足 with reasons | 4 | |
| C7 | An alternative enclosure fixes 不可 and adds a question | 4 | |
| D1–D2 | Lines are built from confirmed components, with price and expiry checks | 5 | |
| D3–D4 | Labour and expenses show their basis and can be overridden | 5 | |
| E1–E2 | The Excel template keeps its formulas and layout | 6 | |
| E3 | Output with open issues is marked as a draft | 6, edge cases | |
| F1 | Values, source and reasons sit side by side for correction | 2 | |
| F2 | Request → approve / send back, auto-cancel on change, versions and history work | 6, 7 | |
| F3 | Master and rule changes take effect after re-analysis | 7 | |
| F4 | Updates by another user are announced, and stale screens cannot overwrite | Edge cases | |
| F5 | Each role can do only what it is allowed | 6, edge cases | |
| C12 | Similar past jobs are listed with reasons, and the quote's position in their price range | 4, 5 | |
| C13 | A rule change shows its impact before saving, is versioned, and can be undone | 7 | |
| D8 | Steel and exchange-rate changes affect only the enclosure and imported parts | 7 | |
| F7 | Corrections become suggestions, applied only after a manager approves | 7 | |
| F8 | Working time per project is compared with the pre-system baseline | 7 | |
| F9 | Sales and purchasing CSV files match the quote | 6 | |
| G1–G2 | The accuracy report reflects your confirmations and corrections | 7 | |
| G3 | The regression check flags projects whose results changed | 7 | |
| G4 | The fit agreement rate reflects the designers' recorded decisions | 4, 7 | |

Real 20–30 user load and company sign-in (AD / Entra ID) cannot be judged on one machine. Note them as open points for the client meeting.

### How to report a problem

For each Fail or Discuss, note:

- the quote number and the step or tab
- the user you were signed in as
- what you did, what you expected, and what happened
- a screenshot, and the exported file if the problem is in the Excel output
