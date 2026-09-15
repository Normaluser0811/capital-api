# 交接：capital-api（三條線）

> ⚠️ 本檔含**三份**交接：**Part C｜國內報價線／台指期（2026-09-15，已上線）**、
> **Part A｜海期價格源（2026-08-26 起，進行中）** 與
> **Part B｜海外選擇權（2026-06-16 完工待併版）**。不要擇一刪除。


# 🟢 2026-09-15：Part C｜國內報價線（台指期）已上線

> 本段最新。下面的 Part A（海期價格源）與 Part B（海外選擇權）都沒動、內容仍有效。

## 做了什麼

`scripts/dump_bfw_price_changes.py` 新增**國內**報價線（`SKQuoteLib`），供應台指期，
取代原本走 scraper DB fallback 的台灣加權指數現貨。merge `9ff27d3`。

本檔原本的註解寫「台股加權群益無可用源」——那句話對的是**加權指數現貨**（國內指數線
需證券帳戶）與**富時台指期貨**（SGX，標的不同且含夜盤）。**台指期（TAIFEX）不在那兩個
排除理由裡**，只是從來沒人試過。實測：國內線連得上、快照與日K 都拿得到。

改用它的理由是 scraper 那條 fallback 長期出錯：2026-09-15 稽核發現 21 篇已發佈日報
有 14 篇日漲跌是錯的、其中 4 篇方向相反（正解由證交所官方 `ods_twse.taiex_index`
獨立背書 10 日）。

## 設計（與海外線同形狀，刻意不另立一套）

| 項目 | 做法 | 依據 |
|---|---|---|
| 日漲跌 | 快照**結算鏈**（`_feed_chain` / `_chain_changes`，與 aluminum 共用）| 日K 只有連續代碼拿得到 |
| 週漲跌 | 同上，鏈養滿 7 天後 | 同上 |
| 換月 | 商品清單「到期日」欄，鏡像海外線 `LTD ≥ as_of+3` | `TX00` 到期日欄＝當期合約 |
| 口徑 | `sTradeSession=0`（日盤）| 收盤 46187 對上現貨 46184.85 |

🔴 **為什麼不用日K**：具體月份合約的日K 一律 rc=9999，只有連續代碼 `TX00` 拿得到，
而連續序列是無回調拼接——實測近月 `TX09AM` nRef=45777 vs 次月 `TX10AM` nRef=45903，
**換月當天憑空跳 +0.28%**，比日報裡很多真實單日變動還大。

🔴 **整段獨立連線、獨立 try/except**：這支腳本每天 06:32 餵整份日報，為了新增一檔商品
讓既有 41 檔一起掛掉不可接受。實跑驗證：taiex 取不到時單獨留空、41 檔零回歸；
狀態檔 32 → 33 檔、既有鏈歷史零損失。

## 🔴 冷啟動（不是故障）

2026-09-15 只種得下一格（`TX10AM` 09-14 = 45903）。
**日漲跌 09-16 起有值、週漲跌約 09-22**。user 知情同意。

下一棒要驗：09-16 早上那班台指期日漲跌是否出現、`data/bfw_settle_state.json` 的
`taiex` 是否多一格。

## 三個實測出來、否則一定會踩的坑

1. **必須用 `SKQuoteLib_EnterMonitorLONG`**。非 LONG 版送得出去（rc=0）但連線永遠
   不完成，之後每個查詢回 `1095 SK_ERROR_QUOTE_CONNECT_FIRST`。曾據此誤判成
   「這個帳號沒有國內報價權限」。
2. **查詢代碼 ≠ 下單代碼**。`RequestStockList(2)` 每筆是
   `TX09AM,台指09,20260916,TXFI6,100000| 1 | ,NTD`——要用第一欄 `TX09AM`；
   `TXFI6` 是下單代碼，丟進 `GetStockByNoLONG` 或 `RequestKLineAMByDate` 一律 rc=9999。
3. **comtypes 的 out 參數回 `list` 不是 `tuple`**（`[SKSTOCKLONG, rc]`）。只判 tuple
   會讓 rc 永遠不等於 0。單獨寫探針時直接讀傳進去的 struct（comtypes 原地填值）
   剛好繞過這個判斷 ⇒ **探針成功、整合後失敗**。

## ⏭️ 下一棒：`_feed_chain` 的假日缺陷（user 09-15 同意留到下一輪）

`_feed_chain()` 回推「昨結算日」時只有 `while settle_date.weekday() >= 5` 跳週末，
**對非交易日毫無概念** ⇒ 用 nRef `setdefault` 憑空補節點 ⇒ 隔日算出 0.00%。

- 2026-09-08（勞動節隔天）造成 **28/41 檔假 0.00%**，全部發佈到 Notion（已更正）
- 證據：整份 history 沒有任何週六日節點，卻在**全部 60 條鏈**上都有 09-07 節點，
  其中 53 條與 09-04 逐位元組相等
- 未來 12 個月至少再犯 11 次，最近一次 **2026-11-26 感恩節**
- 🔴 **台指期接上後，台灣連假也會觸發同一個問題**
- 判準要寫「**該日有沒有官方結算價**」而非「有沒有休市」——09-07 那天
  NYMEX/COMEX/CME 股指走縮短時段且真有成交（CL=F 10.3 萬口），只是不產生結算價
- ⚠️ `ref_market.trading_calendar_holidays` 2026 年對 CME／ICE **不完整**
  （只標 01-01／04-03／12-25），拿它當判準會誤刪真實資料 ⇒ 要先補行事曆
- ⚠️ 這支函式餵**全部 33 檔**商品的鏈，風險量級與加一檔商品完全不同

## 附帶查明：歷史結算價補不回來

結算價只在**當天快照**的 `nSettlePrice`，dump 每天存進鏈才形成歷史；**API 沒有查歷史
結算價的端點**，鏈是唯一紀錄。09-11 快照整批失敗 ⇒ 09-10 那格永久缺失。

替代品是日K 收盤（＝最後成交價）。兩者差距可用鏈上兩邊都有的日子量：
- **A50 / CN2609：7/7 天完全相同**（差 0）⇒ 日K 收盤就是結算價
- **恆生科技 / HTI2609：結算 = 最後成交 −1 或 −2**，最大相對差 0.0463%

據此已補回 09-10 並更正 6 列（ftse_a50 −1.0365 → −0.6571、
hang_seng_tech −2.2835 → −0.1155）。

---

---

# Part A｜海期價格源（BFW 日報群益化）— Phase A0 ✅ 完成，下一步 A1

> 計畫單一真相：`~/.claude/plans/bfw-daily-report-capital-price-and-commodity-expansion.md`（Part 1）；
> 主交接：scraper/next_session_prompt.md §-1.0 ③。
> **A0 結論全文：[docs/overseas_futures_spike_a0.md](docs/overseas_futures_spike_a0.md)**（五題全答，
> 摘要見 TODO.md）。spike 工具：`scripts/spike_overseas_futures_a0.py`（可重跑）。

## 🆕 2026-08-28：dump 三改造完成（橡膠 nRef 修復＋量判滾月＋雙合約鏈）已併 main

> 詳見 TODO.md 最上節與計畫 `~/.claude/plans/bfw-price-dump-active-month-roll-and-rubber-nref-fix.md`。
> **A1 設計必吸收的四條鐵律更新**：① nRef 收盤後改寫**不只 SGX**（NYM/CME 09:00 實測
> `ref==settle` 全中招；06:30 生產時點 ref 才是真昨結）——昨結一律自家鏈 history 優先；
> ② 盤中 nRef 可能過時（DX：day 已滾、ref 停前前日）——鏈上正式結算優先且不可被覆蓋；
> ③ SKOS 快照**單頁上限**（第 2 頁 3006）——多批訂閱走同頁覆蓋式輪換；
> ④ 報導合約＝最活絡月（成交量判準、單向），HOT 只當錨。
> ⚠️ 任務 4（08-28 橡膠頁回修）未做，待 user 拍板。
> ⚠️ 明晨 06:30 首跑：17 檔滾月首次在生產 state 觸發，盯 resolve/problems/warning。

**分支結構**：~~stacked~~ **✅ 2026-08-28 已全部併回 main 並清理**（`feat/overseas-options-ingestion`
→ `feat/overseas-futures-spike-a0` → `fix/bfw-settle-chain-roll` 三支依序併入，遠端分支已刪）。
主工作樹（`D:\PythonProjects\capital-api`）停在 main＝排程 06:30 讀的生產碼，部署漂移已解。

**A1（下個 session）要做的**：
1. （2 分鐘前置）明晨 06:30 補跑 `--symbols "CBOT,C0000#CBOT,W0000#NYM,GC0000#ICEUS,KC0000"`
   實測穀物在兩盤之間的 `nTradingDay`/`nRef` 狀態（A0 唯一未實測的時點）。
2. `src/capitalapi/` 新增海期報價封裝（比照海選 `options_quote.py`）：
   EnterMonitorLONG / RequestOverseaProducts + GetOverseaProductDetail(1)（**含 HOT 映射解析**
   `{root}_{YYYYMM}`）/ RequestStocks(-1, "exch,code#…") / GetStockByNo·IndexLONG /
   RequestKLineByDate / LeaveMonitor；`SKFOREIGNLONG` 原始整數 + sDecimal 全欄保留。
3. 鐵律：🔴 HOT KLine 是換月拼接，週漲跌只能用**映射合約自身** KLine；日漲跌用快照
   `nClose/nRef`（同合約＋正式結算）；`nClose=0`＝無成交哨兵；訂閱清單先過線上商品檔
   （含無效代碼整批 3023）；報價事件只有 pythoncom 泵得到。
4. A2（capital-api 之後）：pgdb 純新增表 `raw_quotes.overseas_future_daily`（PK (symbol,
   trade_date)、原始整數 + decimal_places + `hot_contract` 欄）+ macrodata collector 06:00 job
   （⚠️ scheduler repo 在指派範圍外，屆時請 user 展延授權）；A3 雙源並跑 ≥5 交易日、
   彭博信件當異源 oracle 後才切主。

---

# Part B｜群益海外選擇權 → PostgreSQL → Excel (Black-76 + Greeks)

> **狀態（2026-06-16）**：**Phase 0–4 全完成 + live 端到端 PASS（parity 9.1e-13）** ✅。盤中端到端：`stream`→raw 185 列、`build-ods`→ods IV 76 ok（parity F ES 7557.82/DAX 24978 + Black-76 IV + 同履約價 C/P IV 一致）。🔴 串流必需 pywin32（已修，collector 硬性要求）。**架構一致**：raw 對標 `foreign_futures_bar_1m`、ods 對標 `continuous_bars`(Python 物化表)、cli 對標 capital standalone；`db.read_dataset("ods_quotes","overseas_option_iv")` 可直接消費（excel-builder 就緒）。**測試資料已 TRUNCATE 清空**（兩表 0 列、結構保留）。
>
> **✅ Phase 4 excel-builder 已完成（2026-06-16 盤中 live PASS、未 commit）**：excel-builder 分支 `feat/overseas-options-greeks`
> 新增 `build_overseas_options_greeks_seed()` + CLI `design-overseas-options`（3 sheet：總覽/參數/選擇權鏈+Greeks；單一可刷新
> ODBC ListObject + 右接 9 個 Black-76 計算欄；σ=ods IV、F=ods 標的價、r/T 取『參數』→ 改一格全表重算）。盤中 ES ATM 30 檔
> → raw 1337 → ods IV 1320 全 ok → seed 開檔零修復/Refresh 存活/**parity 全 Greek max|Δ|=9.1e-13 ≪ 1e-6**/年化T==ods tau；
> pytest 94 passed。🔴 坑＝pywin32 把 naive datetime 當本地時區轉 UTC（估價日偏移）→ 改 `=DATE()` 公式。產出
> `excel-builder/templates/小型 S&P 500ES_海外選擇權Greeks_seed.xlsx`。**🟢 Phase 0–4 全完成。**
>
> **🟢 剩下副任務**：① collector 斷線重連（MVP 未實作）② macrodata `feat/overseas-options-agency` cherry-pick 進 main
> （避 superset/EIA WIP）③ 多 root（DAX/穀物 C）/ 美債 32 分數制 ODS 解碼分支 ④ 4 repo commit/PR 待 user 拍板
> （pgdb Phase 2 已 commit `b86701e`；capital-api/macrodata 已 push；excel-builder Phase 4 已 commit 於 `feat/overseas-options-greeks`、未 push）。

## 0. 先讀
- 完整計畫（單一真相，頂部有架構決議）：`C:\Users\Essen\.claude\plans\capital-api-claude-md-postgresql-db-mac-unified-dongarra.md`
- Phase 0 實測規格（symbol/到期/訂閱/欄位/divisor）：`D:\PythonProjects\capital-api\docs\symbol_format_spec.md`

## 1. 🧭 架構決議（user 拍板，覆寫原計畫 Phase 分工）
- **capital-api = 純 library**：以官方 `D:\CapitalFuturesAPI` 為準把 COM 功能（login/報價/海期K/海選/下單）鍵好 + `pricing.py`（Black-76）。**不碰 DB、不裝 `-e postgresql-db`**。
- **macrodata = 只調用 + 計算**：`import capitalapi` + `from db import …`，於 `src/mdw/agencies/capital/` 寫串流 collector + ods_builder（算 IV）+ CLI。（macrodata 已有 capital agency = 既有入庫的家。）
- **postgresql-db** = raw/ods 選擇權表 migration + ORM。**excel-builder** = 讀 PG → Excel。

## 2. git 狀態
| Repo | 路徑 | 分支 | 狀態 |
|---|---|---|---|
| capital-api | `D:\PythonProjects\capital-api` | `feat/overseas-options-ingestion` | HEAD `fed400a`（raw 欄 + 3 解碼 bug + pywin32 必需 + page=1 + 事件 *args；已 push）|
| postgresql-db | `d:\PythonProjects\postgresql-db` | `feat/margin-ingestion` | **alembic head=`oseaopt01`（Phase 2 已套用 live macrodata DB；migration+model+exports 未 commit）** |
| macrodata | `d:\PythonProjects\macrodata` | `feat/overseas-options-agency` | HEAD `3a6ebc5`（Phase 3 + live 煙霧修 + 一致性 docs；已 push；建議 cherry-pick 進 main，避 superset/EIA WIP）|
| excel-builder | `d:\PythonProjects\excel-builder` | — | 無 remote |

## 3. ✅ 已完成
- **Phase 2 postgresql-db migration + ORM（2026-06-16，已套用 live macrodata DB、未 commit）**：
  - migration `oseaopt01`（`migrations/versions/20260616_1200_oseaopt01_create_overseas_options_quotes.py`，`down_revision="m4rgnxref01"`）建 **2 表**：
    - `raw_quotes.overseas_option_quote_snapshot`（24 欄、PK `(symbol, snapshot_ts)`、原始整數 BIGINT 報價 + `decimal_places`/`denominator`、parser 衍生 `root_symbol`/`option_type`/`strike`、2 index、hypertable chunk 1d + compress segmentby symbol + policy 7d、24/24 中文 COMMENT）。
    - `ods_quotes.overseas_option_iv`（14 欄、PK `(symbol, snapshot_ts)`、`expiry_date`/`tau_years`/`underlying_price`/`option_mid`/`risk_free_rate`/`implied_vol`/`iv_status`、1 index、hypertable 1d + compress + policy 30d、14/14 COMMENT）。
  - ORM `src/db/models/overseas_option.py`（`OverseasOptionQuoteSnapshot` + `OverseasOptionIV`），雙重 export（`models/__init__.py` + `db/__init__.py` + `__all__`）。
  - **決策定案**：A=raw 存原始整數 + decimal_places/denominator（raw 禁值計算）；B=F 走 put-call parity、**不建 4b 期貨表**（之後純加法可補）。
  - **驗證**：`alembic current`=oseaopt01；2 表皆 hypertable（7d/30d 壓縮）；ORM insert/read/delete round-trip 綠；4-lens 對抗式複核 0 blocker/0 major（symbol VARCHAR(16) 已對全 59,769 商品檔驗證最長 11 字、不會 overflow）。
  - **⚠ 未 commit**（user 未要求）。pgdb 分支 `feat/margin-ingestion`。
- **Phase 1 `src/capitalapi/pricing.py`**（純 math、37 測試全綠）：Black-76 理論價 + delta/gamma/vega/theta/rho + Newton/bisection IV。
  - theta 正解 `θ = r·Price − decay`（計畫稿/Phase 4 Excel 的 `−r·Call` 是錯的，須改 `+ r*Call`）。
  - 對抗式複核（6 agent）+ 修 IV bisection 端點 bug + 修錯誤價格錨點。
- **Phase 0 `scripts/spike_overseas_options.py`**（盤中實測 PASS）：抓 59,769 檔商品 + 11 檔跨 6 交易所報價（rc=0）。重點全寫進 `docs/symbol_format_spec.md`：
  - symbol = `{ROOT}{履約價5碼}{月碼 A–L Call / M–X Put}{年末碼}`；到期日 = 商品檔第 5 欄。
  - **訂閱**：`RequestStocks(psPageNo=1, "交易所,代碼#交易所,代碼…")`（裸代碼/逗號併 → 3023）。
  - **報價 SKFOREIGNLONG 23 欄**；`價格 = raw / 10^sDecimal`（逐商品不同、**不可寫死**）；`strike = nStrikePrice`（不除）；`nDenominator=1`（美債 32 分數制可能≠1）。
  - **F** 可由同履約價 put-call parity 反推（`F = K + (C−P)·e^{rT}`，玉米驗 ≈$4.15）。

## 4. ✅ Phase 2 — postgresql-db（完成 2026-06-16，以下為實作規格／已落地）

> **執行紀錄**：備份閘判定＝此 migration 為純加法 CREATE-only（只建兩張全新空表、不碰既有 ~20GB raw_quotes 1-min bars 與 ~18GB ods_quotes continuous_bars → 既有資料零風險），`guard_db_backup` 已由 0.9h 內既有備份滿足、downgrade() 可乾淨回滾 → 未另做 38GB hypertable 全量 dump。手寫 migration（autogenerate 結構性不可用）→ `alembic upgrade head` 套用成功 → `alembic current`=`oseaopt01`。version table `alembic_version_pgdb`。

**取樣式串流**：daemon 記憶體保留每 symbol 最新報價，每 N 秒對有更新者各 flush 一列；PK 含 `snapshot_ts`（我方擷取時戳、台北 naive、`timezone=False`）。

### 4a. `raw_quotes.overseas_option_quote_snapshot`（依實測欄位）
- PK `(symbol VARCHAR(16), snapshot_ts TIMESTAMP)`
- parser 衍生（比照 raw_quotes.foreign_futures_bar_1m 存 root_symbol 的慣例）：`root_symbol VARCHAR(16)`、`option_type CHAR(1)`（bstrCallPut）、`strike INTEGER`（nStrikePrice，原值如 448）
- 交易所：`market_no VARCHAR(8)`、`exchange_no VARCHAR(16)`、`exchange_name VARCHAR(32)`、`trading_day INTEGER`（nTradingDay）
- 解碼資訊：`decimal_places SMALLINT`（sDecimal）、`denominator INTEGER`（nDenominator）
- 報價：`open/high/low/close/settle/ref BIGINT`（**原始整數** nOpen…nRef）、`bid BIGINT`+`bid_qty BIGINT`(nBid/nBc)、`ask BIGINT`+`ask_qty BIGINT`(nAsk/nAc)、`tick_qty BIGINT`(nTickQty)、`volume BIGINT`(nTQty)
- `created_at TIMESTAMPTZ DEFAULT now()`
- Index `(root_symbol, snapshot_ts)`、`(symbol, snapshot_ts)`；Hypertable on `snapshot_ts`(chunk 1d) + compress(segmentby symbol) + policy 7d；中文 `COMMENT ON`

> **🔶 開放決策 A（raw 存原始整數 vs 已除 divisor）**：本檔採「**raw 存原始整數 + decimal_places/denominator**，divisor 解碼留 ODS」＝最忠於 raw 不可變鐵律（CLAUDE.md：raw 禁值計算）。計畫稿原寫「decoded NUMERIC 入 raw（divisor 解碼可接受）」亦可——擇一，建議前者。

### 4b. `raw_quotes.overseas_future_quote_snapshot`（標的期貨 F）— **可選/可延後**
- 因 F 可由 put-call parity 反推，MVP 可**不建此表**；要更準再訂閱海期（SKOSQuoteLib）存精簡欄（symbol/snapshot_ts PK + OHLC/bid/ask/settle/trading_day/decimal_places/denominator）。
> **🔶 開放決策 B**：F 走 parity（不建期貨表、最省）還是訂閱海期建表？建議 MVP 先 parity、之後驗證再加期貨表。

### 4c. `ods_quotes.overseas_option_iv`（IV 在此；理論價/Greeks 留 Excel）
- PK `(symbol, snapshot_ts)`；`root_symbol`、`option_type`、`strike NUMERIC(18,6)`
- `expiry_date DATE`（商品檔第 5 欄）、`tau_years NUMERIC(12,8)`
- `underlying_price NUMERIC(18,6)`（F：parity 或期貨）、`option_mid NUMERIC(18,6)`（=(bid+ask)/2 / 10^sDecimal）、`iv_price_source VARCHAR(8)`('mid'/'settle'/'close')
- `risk_free_rate NUMERIC(8,6)`、`implied_vol NUMERIC(10,6)`(不收斂 NULL)、`iv_status VARCHAR(12)`('ok'/'no_converge'/'no_price'/'expired')、`created_at`
- Hypertable + compress(segmentby symbol) + policy 30d；中文 `COMMENT ON`

### 4d. ORM + export
- 新檔 `src/db/models/overseas_option.py`（仿 `quote.py::ForeignFuturesBar1m`），於 `src/db/models/__init__.py` + `src/db/__init__.py` **雙重 import + `__all__`**。
- 驗證：建表 + `timescaledb_information.hypertables` + COMMENT。

## 5. ✅ Phase 3 — macrodata `agencies/capital/`（程式完成 2026-06-16，commit `1f7f8ed`，未做 live 煙霧）
**已交付（branch `feat/overseas-options-agency`，21 測試綠）**：
- `options_symbol.py`：symbol 純拆解（`{ROOT}{strike5}{月碼 A-L Call / M-X Put}{年末}`，含週選前綴/邊界/錯誤）。
- `options_collector.py`：串流 daemon（pump 主緒 pythoncom + flush worker thread；**回調禁 DB IO、COM 只主緒**；
  寫 raw **原始整數** → `raw_quotes.overseas_option_quote_snapshot`；同 flush 批共用 snapshot_ts 利 parity；
  `fetch_products_map`/`save_expiry_map`/`load_expiry_map` 供 build-ods 取 expiry）。flush 預設 2s（env 可調）。
- `options_ods.py`：`compute_iv_rows`（純函式：解碼 raw/10^dp + 日曆 T + **put-call parity 反推 F〔分組鍵含 expiry 避免跨月誤配〕**
  + `capitalapi.pricing.implied_vol` Black-76 反解；不收斂/無價/到期/無標的 → NULL + iv_status）+ `build_ods_iv`（讀 raw→寫 ods）。
- `options_config.py`（r/flush/連線參數，env 覆寫；憑證沿用 capital `.env` fallback）+ `cli.py` 加 `stream` / `build-ods`。
- **capital-api 補強已並行完成（commit `12ff7dc`）**：`OptionQuote` 加 `raw_*` 整數欄 + `denominator`；修 3 解碼 bug
  （sDecimal=0→divisor 1、strike 不除、保留 nDenominator）；`subscribe_many` 改 `#`；抽 `build_option_quote` 純函式。

**✅ Phase 3 live 煙霧測試 PASS（2026-06-16 盤中實測）**：
- `stream --symbols "<ES/STXE/DAX/NQ ATM 24 檔>" --seconds 40 --flush-interval 2 --dump-expiry ...` → raw **185 列**（每 ~2s flush、首批快照後逐筆更新；原始整數+decimal_places 正確，PK 無重複）。
- `build-ods --products-json ...` → ods IV **185 列（76 ok / 109 no_under）**；parity 反推 F（ES 7557.82 / DAX 24978）、Black-76 反解 IV、**同履約價 C/P IV 一致**（ES 0.4244 / DAX 0.24）= 端到端數學驗證。
- ✅ 測試資料已 **TRUNCATE 清空**（兩表 0 列、表結構/hypertable 保留）；正式上線由排程器跑 collector 重新累積。
- 🔑 **盤中選股**：GC 等冷門/離峰時段可能 0 報價（群益**只在變動時推送**，非保證 subscribe 快照）→ 用當下活躍市場 + 近 ATM（median strike）；商品檔第 5 欄取 expiry，median strike ≈ ATM。

**🔴 根因排查紀錄（重要、避免重踩）**：collector 連線/商品都正常但 **0 報價**，逐步隔離（symbol/page/sink/pump/venv/comtypes 版本/gen cache 全排除）→ 真因 = **`comtypes.client.PumpEvents` 不會推送 SKOOQuoteLib 的 `OnNotifyQuoteLONG`**（`OnConnect`/`OnProducts` 會、報價不會），**只有 `pythoncom.PumpWaitingMessages`（pywin32）會**。spike 能跑是因 capital-api venv 有 pywin32；macrodata venv 缺 → 靜默收 0。修：capital-api 加 pywin32 依賴 + collector `_make_pump` 硬性要求 pythoncom（缺則 raise）。

**▶️ 剩（下個 session）**：
1. **collector 斷線重連未實作**（MVP；on_connection 重訂閱 + 指數退避，留下個 live session 補）。
2. **單帳號訂閱上限壓測**（`--max-symbols`，本次 24~30 檔 OK）；美債 32 分數制（denominator≠1）ODS 解碼分支。
3. **macrodata Phase 3 cherry-pick 進 main**（比照 margin，避 superset/EIA WIP 污染）。
4. **Phase 4 excel-builder** 海外選擇權 Greeks 母版。

## 6. ▶️ Phase 4 — excel-builder（下個 session 主任務）

> **前置全就緒**：ods_quotes.overseas_option_iv（IV）+ raw_quotes.overseas_option_quote_snapshot（報價）已建、
> 端到端驗證綠、`db.read_dataset` 可直接消費。**架構一致性審查通過**（見 §5）—— 比照其他 agency 的 excel-over-PG 模式即可。

**落點**：`d:\PythonProjects\excel-builder`（無 git remote）。新函式 `build_overseas_options_greeks_seed()`
（`seed_builder.py`，**新寫、不改 `build_options_seed`**）+ CLI `design-overseas-options`（仿 `_cmd_design_options`）。
沿用 `_apply_capital_futures_theme` / `odbc_querytable_connection` / 中文 quoted alias / win32com。

**4 sheet**：① 總覽（標的 name_zh 走 contract_specs PG-first + 刷新/換商品指引）② **選擇權鏈+Greeks**（主表：每 symbol
最新 raw 報價〔需解碼 `raw/10^decimal_places`〕+ ods IV，右接 Excel 公式算 Black-76 理論價與 5 Greeks）
③ **參數**（可調格 `無風險利率 r`/`估價日`或`到期天數`/`年化基準 365`，主表引用→改一格全表重算）④ **資料**（ODBC 來源，可隱藏）。

**ODBC SQL**（中文 alias 撐 RefreshAll）：取每 symbol 最新快照 `DISTINCT ON (symbol) … ORDER BY symbol, snapshot_ts DESC`
LEFT JOIN `ods_quotes.overseas_option_iv`（IV/F/tau），`WHERE root_symbol='<ROOT>'`；`BackgroundQuery=False`。
（或直接 `db.read_dataset("ods_quotes","overseas_option_iv", filters={"root_symbol":...}, date_column="snapshot_ts")`。）

**Black-76 Excel 公式逐欄**（F=標的價、K=履約價、T=年數、r=參數格、σ=ods IV 欄）：
```
d1 = (LN(F/K)+(σ^2/2)*T)/(σ*SQRT(T)) ；d2 = d1 - σ*SQRT(T)
Call = EXP(-r*T)*(F*NORM.S.DIST(d1,TRUE) - K*NORM.S.DIST(d2,TRUE))
Put  = EXP(-r*T)*(K*NORM.S.DIST(-d2,TRUE) - F*NORM.S.DIST(-d1,TRUE))
Delta_Call = EXP(-r*T)*NORM.S.DIST(d1,TRUE) ；Delta_Put = -EXP(-r*T)*NORM.S.DIST(-d1,TRUE)
Gamma = EXP(-r*T)*NORM.S.DIST(d1,FALSE)/(F*σ*SQRT(T))
Vega  = F*EXP(-r*T)*NORM.S.DIST(d1,FALSE)*SQRT(T)        (每 1.0σ；/100 得每 1%)
Theta_Call = -F*EXP(-r*T)*NORM.S.DIST(d1,FALSE)*σ/(2*SQRT(T)) - r*Call   (🔴 +(-r*Call)，計畫舊稿 -r*Call 是錯的；/365 得每日)
Rho_Call = -T*Call ；Rho_Put = -T*Put
```
驗證：Excel 公式 Black-76 vs Python `capitalapi.pricing.calc_all_greeks` 同參數誤差 <1e-6；改 r/T 參數格全表即時重算。
完整見 plan `capital-api-claude-md-postgresql-db-mac-unified-dongarra.md` §Phase4 + `docs/symbol_format_spec.md`。

## 7. 鐵律
- raw 不可變：Greeks/IV/理論價/`expiry_date`/`tau_years` 絕不進 raw。
- DB 入庫/DDL 前必 `/db-backup`（`guard_db_backup` 近 12h 無備份會 BLOCK）；備份落 D/E NVMe 勿 H/G。
- postgresql-db autogenerate 不可用 → 手寫 migration；`alembic current` 查狀態（勿 SELECT alembic_version）。
- capital-api 僅 Windows（COM）；報價 pump；回調內禁 DB IO。
- 溝通繁體中文、禁日文。

## 8. 重跑 Phase 0（驗證 spike，盤中）
```powershell
cd D:\PythonProjects\capital-api
.\.venv\Scripts\python.exe scripts/spike_overseas_options.py --symbols "C00448G6,C00448S6,GC04455G6,ES07000F6" --seconds 60
```
（自動補交易所前綴；`docs/overseas_options_field_survey.md` 為自動產出、已 gitignore。近 ATM 候選見 spec §… 或用 `d:\tmp\analyze_oo_products.py` 重算。）
