# 🔎 2026-09-15 接手盤點（五專案同步存檔：financialreport／scraper／notion-hub／postgresql-db／capital-api）

> **本段只做了「讀文件 ＋ 實查驗證」，沒有動任何程式碼、沒有連群益、沒有寫任何資料庫。**
> 方法：11 個代理（5 位讀者逐 repo 讀文件、5 位獨立查證者用不可編造的操作重建 ground truth、
> 1 位跨專案彙整）＋ 主 session 自己實查。本 repo 工作樹乾淨、main 與 origin 同步、無未併分支。

## 🔴 本 repo 的定位已經變了，但 CLAUDE.md／README.md 完全沒跟上

這個 repo 已經從「群益 COM API 封裝」變成**有生產線在跑**的專案：
`scripts/dump_bfw_price_changes.py` 每天 06:32 被排程叫起，供應 scraper 商品日報
**全部 42 檔**商品的漲跌幅。

- `CLAUDE.md`（142 行）與 `README.md`（180 行）**停在 2026-01-18，落後 8 個月**，
  完全沒提這個 repo 有生產排程在跑
- `TODO.md` 停在 2026-08-28；真正的現況只在 `next_session_prompt.md`（09-15，含 Part A/B/C 三份交接）
- ⇒ 接手的人照 CLAUDE.md／README.md 讀，會完全不知道改這支腳本會直接影響每天發出去的日報

## 🔴 P0-1 `_feed_chain()` 的假日缺陷 —— 行事曆的真實缺口與交接寫的不一樣

缺陷本身（user 09-15 同意留到下一輪）：`_feed_chain()` 回推「昨結算日」時只有
`while settle_date.weekday() >= 5` 跳週末，**對非交易日毫無概念** ⇒ 用 nRef 在鏈上
`setdefault` 憑空補節點 ⇒ 隔日算出 0.00%。2026-09-08（美國勞動節隔天）造成 **28/41 檔假 0.00%**、全部發佈。

交接寫「`ref_market.trading_calendar_holidays` 2026 年對 CME／ICE 不完整
（只標 01-01／04-03／12-25），拿它當判準會誤刪真實資料」。實查後**只對了一半**：

| calendar_key | 2026 天數 | kind | 涵蓋到 | 判讀 |
|---|---|---|---|---|
| `NYSE` | 10 | `scheduled` | 2035-12-25 | ✅ 完整（含 09-07／11-26）|
| `CME_Globex_Agriculture` | 10 | `scheduled` | 2035-12-25 | ✅ 完整 |
| `CME_Globex_Livestock` | 9 | `scheduled` | 2035-12-25 | 缺 06-19 |
| `CME_Globex_Energy_Metals` | **3** | `scheduled` | 2035-12-25 | ❌ 原油／天然氣／貴金屬走這本 |
| `ICE_US_Softs`／`ICE_US_Currencies`／`ICE_LIFFE` | **3** | `scheduled` | 2035-12-25 | ❌ 可可咖啡糖棉花走這本 |
| **`TAIFEX`** | 14 | **441 列全部 `derived_no_tick_file`** | **2026-07-10（過去）** | 🔴 **未來零覆蓋** |

🔴 **交接完全沒提 TAIFEX 這一項，而它正好打中剛上線的台指期**：
TAIFEX 是唯一一列 `scheduled` 都沒有的主要期貨行事曆，它是從「該平日沒有逐筆來源檔」
**反推**出來的，結構上只看得到過去。證據：2025 年 TAIFEX vs TWSE 差異為 **0**（全年已過去），
2026 年差 6 天，其中 5 天是 TWSE 有而 TAIFEX 沒有的**未來**假日：

- **2026-09-25 中秋節（10 天後，台指期第一次踩雷）**
- 09-28 教師節／10-09 國慶（10-10 週六順延）／10-26 光復節（10-25 週日順延）／12-25 行憲紀念日

（TAIFEX 獨有的 2026-07-10 反而是真的——排定行事曆看不到的臨時休市。兩種來源互補，不是誰取代誰。）

**所以修 `_feed_chain` 的前置比交接想的窄也比它急**：穀物與美股那半的行事曆本來就完整、不必補；
真正要補的是 `CME_Globex_Energy_Metals` ＋ 三本 ICE ＋ **TAIFEX 的未來排定假日**。
判準仍照 user 的話寫成「**該日有沒有官方結算價**」而不是「交易所有沒有休市」——
09-07 那天 NYMEX/COMEX/CME 股指走縮短時段且真的有成交（CL=F 10.3 萬口），只是不產生 09-07 的結算價。

> ⚠️ `ref_market` 維度資料由 ref-market 專案負責，不在本次指派範圍；此處只記錄查證結果。
> ⚠️ `_feed_chain` 餵的是**全部 33 檔**商品的鏈，改它的風險量級與加一檔商品完全不同。

## ⏰ P0-2 09-16 早班驗收（有時間窗）

實查 `data/bfw_settle_state.json`（09-15 10:22 更新、33 檔）：
`taiex` 的鏈只有 **1 格**——`TX10AM` 2026-09-14 = 45903、`TX11AM` 2026-09-14 = 46032。
冷啟動完全如預期：

- **09-16**：日漲跌第一次有值 ← 下一棒要驗的就是這個，順便看 `taiex` 是否多一格
- **約 09-22**：週漲跌第一次有值（鏈要養滿 7 天）
- 在那之前台指期欄留空，user 09-15 已知情同意

## 其他本 repo 待辦（讀者盤點，共 19 條）

| 優先 | 項目 | 備註 |
|---|---|---|
| P1 | 台指期那 223 行新程式碼零測試覆蓋 | 它已在生產線供應日報一檔商品。至少釘住三件：商品清單那行的解析（**查詢用代碼 `TX09AM` 與下單用代碼 `TXFI6` 是不同欄**）、連續代碼 `TX00` 必須被排除、換月判定 |
| P1 | `CLAUDE.md` 與 `README.md` 全面重寫 | 停在 2026-01-18，見上 |
| P1 | `TODO.md` 整理：補上 2026-08-28 之後的落差、刪掉已完成卻仍標未完成的條目 | |
| P1 | Phase A1 前置：06:30 補跑穀物 spike，實測兩盤之間的 `nTradingDay`／`nRef` 狀態 | |
| P1 | Phase A1：`src/capitalapi/` 新增海期報價封裝（純 library）| |
| P2 | Phase A2：pgdb 純新增 `raw_quotes.overseas_future_daily` ＋ macrodata collector 06:00 job | 純新增＝回滾就是 DROP，免針對性備份 |
| P2 | Phase A3：群益 vs 既有源雙源並跑 ≥5 交易日，彭博信件當異源 oracle 後才切主 | |
| P2 | 查明 2026-09-11 快照整批失敗的根因，並補失敗告警 | 那次失敗直接造成 scraper 那 12 列「換基準」 |
| P2 | 海外選擇權 collector 斷線重連未實作（MVP 缺口）| |
| P2 | excel-builder `feat/overseas-options-greeks` 已 commit 但未 push（且該 repo 無 remote）| 待 user 拍板 |
| P2 | macrodata `feat/overseas-options-agency` cherry-pick 進 main | |
| P2 | 🔴 `next_session_prompt.md:274` 仍留著**已作廢**的備份鐵律 | 那句寫「備份落點走 D/E 固態硬碟、勿用 H/G」，已於 2026-08-22 被推翻。現行落點是 `H:\PostgreSQL`（主）＋ `G:\PostgreSQL`（鏡像）。照著做會寫爆 D 槽或被守衛擋住 |
| P3 | 刪掉 dump 腳本裡已被推翻的 taiex 註解 | 那句「台股加權群益無可用源」對的是加權指數現貨與 SGX 富時台指期，**台指期不在那兩個排除理由裡** |
| P3 | 海外選擇權多 root 擴充 ＋ 美債 32 分數制（denominator≠1）ODS 解碼分支 | |
| P3 | 單帳號訂閱上限壓測 | |
| P3 | `TODO.md` 2026-01 遺留的願望清單需重新評估或刪除；刪除「整合 twmarket 套件」條目（該專案不存在）| |

## 這兩天踩到、下一棒別再踩的坑（原樣保留，已複驗仍有效）

1. **群益國內線一定要用 `EnterMonitorLONG`**。非 LONG 版送得出去（rc=0）但連線永遠不完成，
   之後每個查詢回 `1095 SK_ERROR_QUOTE_CONNECT_FIRST`。曾據此誤判成「這個帳號沒有國內報價權限」。
2. **查詢代碼 ≠ 下單代碼**。商品清單每筆是 `TX09AM,台指09,20260916,TXFI6,100000| 1 | ,NTD`
   ——要用第一欄 `TX09AM`；`TXFI6` 丟進任何查詢一律 rc=9999。
3. **先讀 `docs/overseas_futures_spike_a0.md`**：那份早就寫著「日報日漲跌＝快照 nClose/nRef；
   週漲跌＝映射合約 KLine（絕不用 HOT KLine 跨換月）」。日漲跌根本不走 K 線。
4. **Notion 的百分比欄存的是比值不是百分點**（`round(pct/100, 6)`）。繞過
   `build_daily_report_properties()` 做局部 PATCH 會連換算一起繞過（曾把 47 頁寫成 100 倍），
   而**用同一套錯假設寫的驗證會替它背書**。
5. **comtypes 的 out 參數回的是 `list` 不是 `tuple`** ⇒ 只判 tuple 會讓 rc 永遠不等於 0。
   單獨寫探針時直接讀傳進去的 struct 剛好繞過這個判斷 ⇒ **探針成功、整合後失敗**。
6. **判斷「有沒有班正在跑」不可以查 scheduler 的 runs 表**——它跑完才寫列。
   要看 daemon 的子行程，而且工作量在**孫**行程。
7. **`SchedulerAutoStart` 是 RunLevel Highest**，未提權的 session 砍不掉它的子行程。

---
# Capital API 待辦事項

**最後更新**: 2026-08-28

---

## ✅ BFW dump：橡膠 nRef 修復＋最活絡月量判滾月＋雙合約結算鏈（2026-08-28，分支 `fix/bfw-settle-chain-roll` 已併 main）

> 計畫單一真相：`~/.claude/plans/bfw-price-dump-active-month-roll-and-rubber-nref-fix.md`
> （2026-08-28 覆核證據＋四任務）。scraper / notion-hub 零改動（價格檔 JSON 介面不變）。

1. **任務 1（橡膠 +0.08% → 真值 +1.14%）**：已收盤分支昨結改「自家鏈 history 優先
   （gap ≤4 天）、nRef 只當 fallback」；nRef 與鏈值不一致印 warning。
2. **任務 2（最活絡月自動換月）**：候選＝LTD 排序近月＋次月、錨＝state active 與 HOT
   映射較晚者（單向不回滾）、次月連 2 完成交易日成交量 > 近月即切換（零成交/進行中
   bar 不計）；鋁（無 HOT）併同一套；LTD < as_of+3 強制滾。實測 08-28 一輪滾了 17 檔
   （九月系穀物/能源→市場慣例月、橘子汁→OJF2611 ＝計畫驗收值 +0.85% 逐位吻合 Barchart）。
3. **任務 3（換月無縫）**：state 改 `{active_code, chains:{code:{history}}}` 雙鏈平養；
   舊 schema 自動遷移（冪等）；已到期鏈整條修剪。
4. 🔴 **實測又揭三雷（已修＋測試釘死）**：
   - **快照單頁上限**：第 2 次 `RequestStocks(-1)` 回 3006 PAGE_EXCEED → 同頁
     「覆蓋式輪換」（每批 40 檔、等快照到手再用同頁訂下一批）。
   - **nRef 收盤後改寫非 SGX 獨有**：09:00 實測 NYM/CME 的 HO/HG/PA/ALI/CL 全部
     `ref==settle`（06:30 生產時點 ref 還是真昨結）→ 冷鏈 fallback 遇 `ref==settle`
     簽名即棄用（退最後成交鏈），不出 +0.00% 假值。
   - **盤中 nRef 可能過時**（DX：day 已滾新日、ref 停在前前日結算）→ settle_val
     鏈上既有正式結算優先、盤中不覆蓋既有值（已收盤 nSettle 仍為權威可覆蓋）。
   - **INDEX 頁收盤後把 nRef 滾成昨收**（nClose==nRef；08-28 06:31 KOSPI/NI225 中招
     → 日報發布 +0.00% 假值，HHHSI 未滾所以正確）→ 混合法未開盤分支偵測簽名，
     前日收退日K 完成列（merge `73d4dc2`，第二輪掃描時發現並修）。
5. **驗證**：77 測試綠（32+4 條新增）、mutation 10/10 轉紅、三輪盤中實跑
   （67/67 快照、滾月三輪重現一致、16 檔結算鏈 14 檔鏈隱含逐位一致＋2 檔合法
   nRef fallback、OJ/可可/橡膠三檔異源錨逐位吻合）。
6. ⚠️ **明晨 06:30 首跑要盯**：17 檔滾月在生產 state 首次觸發（新合約冷鏈 →
   已收盤 nRef fallback 應接住；鋁留空一天）；resolve 應出現「滾月(量判/LTD/錨)」；
   若有 ⚠️ nRef ≠ 鏈上昨結 warning＝又一家交易所改寫，看得見即正常。
7. ✅ **任務 4 已完成（user 同日拍板）**：08-28 橡膠頁回修 +1.14%；第二輪全檔掃描
   再揪出 kospi/nikkei 0.00% 假值（上面 INDEX 雷）與玉米被 youtube 來源閘門擋下，
   四頁全數重生成發布。備份 `d:/tmp/bfw_daily_fix_20260828/`；
   細節 → scraper TODO.md 08-28 節。

---

## ✅ 海期價格源 Phase A0 盤中 spike 完成（2026-08-26，分支 `feat/overseas-futures-spike-a0`）

> 背景＝BFW 日報要以群益取代 yfinance 當期貨價格源（計畫
> `~/.claude/plans/bfw-daily-report-capital-price-and-commodity-expansion.md` Part 1；
> 主交接在 scraper/next_session_prompt.md §-1.0 ③）。
> **五題全數有答案，結論全文 → [docs/overseas_futures_spike_a0.md](docs/overseas_futures_spike_a0.md)**；
> 工具 `scripts/spike_overseas_futures_a0.py`（可重跑）。摘要：

1. **Q1** 線上商品檔 1,313 檔複驗：44 目標代碼 43 個在線；**鋁無 HOT**（只有逐月 ALI2608–2701，
   A1 要自建近月選擇）。FX 現貨頁/INDEX 延遲頁與海期**同通道**可訂、可推播、可查 KLine。
2. **Q2** 日K API 可用（`RequestKLineByDate`，HOT/逐月/FX/INDEX 都吃）。
   🔴 **HOT 的 KLine 是換月拼接**（KC0000 的 08-12 列＝KC2609、08-25 列＝KC2612，逐欄位驗證）
   ——與 yfinance 同構的雷。**週漲跌必須抓「映射合約自身」的 KLine**。
3. **Q3** `nRef`＝該 `nTradingDay` 的昨結（正式結算價）；已收盤市場 `nSettlePrice/nRef` 直接
   得已完成日漲跌；KLine 收盤欄＝最後成交**非結算**。⚠️ 穀物在 06:30（兩盤之間）的欄位
   狀態未實測，A1 開工前明晨 06:30 補跑一次 `--symbols`。
4. **Q4** HOT 映射雙重可解：detail 下單代碼 `{root}_{YYYYMM}` 明示映射 + HOT 名自帶月份；
   `C0000`≡`C2609` 訂閱逐欄位驗證。
5. **Q5** 同 ID 兩行程 API 併發登入**不互踢**（A 全程 IsConnected=1）。維護窗手冊無記載，
   留 A2 排程試跑觀察。
6. 雜項：`nClose=0`＝本節尚無成交哨兵要 guard；訂閱含無效代碼**整批**被拒（3023）；
   TY 32 分數制 API 已解成十進位（dec=6）。

**同日午前追加（user 指示日報改群益價，已實戰上線一次；隨後拍板**常態只用群益**）**：
`scripts/dump_bfw_price_changes.py` 產價格檔 → scraper `daily-report --price-file` 消費，
08-26 全部 43 頁刪除重生成完成。scraper 端已把 dump 接成 `--apply` 的**自動前置步驟**
（scraper merge `95cbd48`；本腳本從此每天 06:30 被排程叫起，改動要顧向後相容：
`--date`/`--out` 介面、exit code 語意、期貨/FX 失敗＝明確 null）。
實戰又揭兩雷（已寫進 dump 註解）：① **INDEX 頁日K 不可信作昨收**（KOSPI 最後一根是
「今天盤中值掛昨天日期」，歷史列與 DB 全等唯最後一根不等）→ 指數剔除、走 scraper DB
fallback；② **極薄合約（COMEX 鋁）最後成交序列是垃圾**（ALI2608 零成交＝結算順延平 bar
→ 日漲跌算成前一天的；ALI2609 最後成交離結算 2.7%）→ EXPLICIT_NULL 留空。
主交接 → scraper/next_session_prompt.md §-1.0b。

**🔜 下一步＝Phase A1**：capital-api 補海期 SKOSQuoteLib 封裝（純 library，比照海選
`options_quote.py` 模式；API 面清單見結論文件 §「對 Phase A1/A2 的直接輸入」）。
A1 設計要吸收上面兩雷（KLine 週漲跌 API 面應內建「指數頁禁用/薄合約偵測」守衛）。
⚠️ 本分支疊在 `feat/overseas-options-ingestion` 上（該分支 6 月完工、push 過但**尚未併 main**，
交接文件只存在於該分支）——併版時兩支一起處理，或先併父分支再併本支。

---

## 🚧 大型功能：海外選擇權即時串流 → PG → Excel (Black-76 + Greeks)

> 計畫已核准、**實作進行中**（分支 `feat/overseas-options-ingestion`）。交接見 [`next_session_prompt.md`](next_session_prompt.md)；
> 完整計畫 `C:\Users\Essen\.claude\plans\capital-api-claude-md-postgresql-db-mac-unified-dongarra.md`。

- [~] **Phase 0**：現場探勘 spike — 腳本 `scripts/spike_overseas_options.py` **已寫好（dump SKFOREIGNLONG 全原生欄位 + 商品清單 + 更新頻率估計）**；
  **待 user 盤中跑**：先 `pip install pywin32` → `python scripts/spike_overseas_options.py --products-only` →
  再 `--symbols "<挑的鏈>" --seconds 60`。產出 `docs/overseas_options_field_survey.md`（自動）+ 填 `docs/symbol_format_spec.md`。
  **解 symbol 格式 / 到期日 / 標的期貨 / 訂閱上限；未 PASS 不進 Phase 2+。**
- [x] **Phase 1**：`src/capitalapi/pricing.py` Black-76 + `tests/test_pricing.py` **完成（27 測試全綠）**。
  - 純標準庫 `math`（純量數學，免 numpy/scipy 依賴風險，Py3.14 venv 友善）；Greeks 全用有限差分驗證。
  - ⚠️ **修正計畫稿 theta 符號錯誤**：正解為 `θ = r·Price − decay`（**+r·Price**，非計畫稿的 −r·Call）。
    → **Phase 4 Excel theta 公式同樣要改成 `… + r*Call`**（計畫 §Phase4 / 端到端 §6 的式子需一併更正）。
- [ ] **Phase 2**：postgresql-db 2 raw + 1 ods 表 migration + ORM（先 `/db-backup`）。**依 Phase 0 欄寬，故 gated。**
  - 註：numpy/scipy/pandas/pywin32 + `pip install -e ../postgresql-db` + `[project.scripts] capital-options`
    **延到 Phase 3** 再加（collector/ods_builder 才真的需要；現在加 scripts entry 會因 cli.py 未建而壞 editable install）。
- [ ] **Phase 3**：`symbol_parser` / `config` / `streaming/collector`（串流 daemon）/ `ods_builder` / `cli`
- [x] **Phase 4**：excel-builder `build_overseas_options_greeks_seed()` + CLI `design-overseas-options`（theta 採 `+r·理論價` 更正）
  **完成（2026-06-16，excel-builder 分支 `feat/overseas-options-greeks`）**：3 sheet（總覽/參數/選擇權鏈+Greeks）、
  單一可刷新 ODBC ListObject + 右接 9 個 Black-76 計算欄；盤中 ES ATM live PASS。
- [x] 端到端驗證（數學單元 / 串流煙霧 / ODS IV / Excel parity）：**parity 全 Greek max|Δ|=9.1e-13 ≪ 1e-6、年化T==ods tau、pytest 94 passed**。

---

## 進行中

- [ ] 測試海外選擇權報價功能 (修正後)

---

## 待完成

### 高優先

- [x] 確認台灣選擇權 (TXO) 的商品代號格式 (已完成 2026-01-27)
  - 格式: {商品代碼}{5位履約價}{月份代碼}{年份尾碼}
  - 例: TXO23000A6 = 月選 23000 Call 1月 2026年
- [x] 整合 options-dashboard 即時報價 (已完成 2026-01-27)
- [x] 新增 `request_stock_list()` 方法 (已完成 2026-01-27)
- [ ] 完善錯誤處理與重連機制

### 中優先

- [ ] 新增單元測試 (mock COM 元件)
- [ ] 新增整合測試 (測試環境)
- [ ] 實作回報解析 (將字串解析為結構化資料)
- [ ] 新增即時委託回報事件

### 低優先

- [ ] 整合 twmarket 套件 (公司名稱對照)
- [ ] 新增 WebSocket 風格的 API
- [ ] 新增非同步 (asyncio) 支援
- [ ] 建立完整 API 文件
- [ ] 實作下單功能 (目前只有查詢)

---

## 已完成

### 2026-01-24
- [x] **修正海外選擇權報價 API 函數名稱錯誤**
  - [x] `SKOOQuoteLib_GetProducts` → `SKOOQuoteLib_RequestProducts` (取得商品清單)
  - [x] `SKOOQuoteLib_RequestStocksLONG` → `SKOOQuoteLib_RequestStocks` (訂閱報價)
  - [x] 新增 `_page_no` 參數支援 (群益 API 需要 page 參數)
  - [x] 修正 `subscribe()` 和 `subscribe_many()` 函數

### 先前完成
- [x] 專案初始化
- [x] 基本架構設計
- [x] CapitalClient 登入模組
- [x] QuoteManager 股票/期貨報價模組
- [x] **OptionsQuoteManager 選擇權報價模組**
- [x] **OptionsChain 選擇權鏈資料結構**
- [x] OrderManager 查詢模組 (預留下單功能)
- [x] 範例程式 (5 個)
  - 01_login.py
  - 02_quote.py
  - 03_order_query.py
  - 04_options_quote.py
  - 05_options_chain.py
- [x] README.md
- [x] CLAUDE.md
- [x] VSCode 設定
- [x] **SKCOM.dll 路徑自動搜尋** (skcom.py)
- [x] **.env 環境變數設定** (帳密安全管理)
- [x] **登入測試通過** (test_login.py)
- [x] 測試腳本 (scripts/)
  - test_login.py
  - test_options_quote.py
  - test_full_integration.py
- [x] **選擇權策略儀表板** (options-dashboard 專案)

---

## 備註

### 選擇權報價欄位

`OptionQuote` 資料結構包含：
- `strike_price` - 履約價
- `close_price` - 成交價
- `bid_price` / `ask_price` - 買賣價
- `bid_qty` / `ask_qty` - 買賣量
- `mid_price` - 買賣中價 (計算)
- `spread` - 價差 (計算)
- `option_type` - Call/Put

### 群益 API 限制

1. **僅支援 Windows**: COM 元件無法在 Linux/Mac 運行
2. **需要憑證**: 下單功能必須先讀取憑證
3. **訊息迴圈**: 報價需要 `pythoncom.PumpWaitingMessages()`
4. **連線數限制**: 同一帳號不能同時多處登入

### 測試環境

- 使用 `Environment.TEST` 進行測試
- 測試環境的報價是模擬資料
- 下單功能在測試環境不會真正執行

### 儀表板規劃

未來可建立選擇權視覺化儀表板：
- 選擇權鏈表格顯示
- 策略損益曲線圖
- Greeks 計算顯示
- 即時報價更新
