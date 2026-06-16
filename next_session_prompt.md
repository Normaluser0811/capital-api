# 交接：群益海外選擇權 → PostgreSQL → Excel (Black-76 + Greeks)

> **狀態（2026-06-16）**：**Phase 0 + Phase 1 + Phase 2 完成**（Phase 2 migration `oseaopt01` 已套用 live macrodata DB、ORM round-trip 驗證綠、4-lens 對抗式複核 0 blocker）。下一步 = **Phase 3（macrodata `agencies/capital/` 串流 collector + ods_builder 算 IV + cli）**。

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
| capital-api | `D:\PythonProjects\capital-api` | `feat/overseas-options-ingestion` | HEAD `08e0e0e`，**已 push**（pricing+spike+tests+docs）|
| postgresql-db | `d:\PythonProjects\postgresql-db` | `feat/margin-ingestion` | **alembic head=`oseaopt01`（Phase 2 已套用 live macrodata DB；migration+model+exports 未 commit）** |
| macrodata | `d:\PythonProjects\macrodata` | — | 已有 `agencies/capital/`；Phase 3 落這 |
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

## 5. Phase 3 — macrodata `agencies/capital/`（依 Phase 2）
- `import capitalapi`（OptionsQuoteManager + pricing）+ `from db import …`。
- `symbol_parser`（重用 `ref_market.margin_root_xref`；symbol 拆解見 spec §1）+ 商品檔 `{symbol→expiry}` map。
- `collector.py`：主執行緒 pump（pythoncom）+ DB flush worker thread + `queue.Queue` + 斷線重連；**回調內禁 DB IO；COM 物件只主執行緒碰**。flush 2–3s。
- `ods_builder.py`：raw → 算 expiry/T、取 F（parity）、option_mid、`pricing.implied_vol` → 寫 ods（不收斂 NULL + iv_status）。
- option root → 標的期貨 root 對應（多數同名）；美債 32 分數制、單帳號訂閱上限壓測。

## 6. Phase 4 — excel-builder
- `build_overseas_options_greeks_seed()` + CLI `design-overseas-options`；群益主題 + ODBC + Excel 公式 Black-76（**theta 用 `… + r*Call`**）。

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
