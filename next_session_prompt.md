# 交接：群益海外選擇權 → PostgreSQL → Excel (Black-76 + Greeks)

> **狀態**：Phase 0 spike 已寫（待盤中跑）、Phase 1 數學完成並 commit。**架構已於 2026-06-16 由 user 改定**（見下）。

## 完整計畫（單一真相來源，含 2026-06-16 架構決議）

`C:\Users\Essen\.claude\plans\capital-api-claude-md-postgresql-db-mac-unified-dongarra.md`
（頂部「⚠️ 架構決議更新」覆寫原 Phase 分工，務必先讀。）

## 🧭 架構決議（user 拍板 2026-06-16）

- **capital-api = 純 library**：以官方 `D:\CapitalFuturesAPI` 為準，把 COM 功能（login/報價/OS K/選擇權/下單）
  鍵好 + `pricing.py`（Black-76 數學）。**不碰 DB、不裝 `-e postgresql-db`**。
- **macrodata = 只負責調用 + 計算**：`import capitalapi` + `from db import …`，在 `src/mdw/agencies/capital/`
  寫**串流 collector + ods_builder（算 IV 寫 PG）+ CLI**。（macrodata 已有 capital agency = 既有入庫的家。）
- **postgresql-db** = raw/ods 選擇權表 migration + ORM。**excel-builder** = 讀 PG → Excel。

## 起手 git 狀態（2026-06-16）

| Repo | 路徑 | 分支 | 狀態 |
|---|---|---|---|
| capital-api（純 lib） | `D:\PythonProjects\capital-api` | `feat/overseas-options-ingestion` | **commit `6f74378`**（pricing+spike+tests）已在；本檔未 commit |
| macrodata（入庫+計算） | `d:\PythonProjects\macrodata` | — | 已有 `agencies/capital/`；Phase 3 落這 |
| postgresql-db | `d:\PythonProjects\postgresql-db` | `feat/margin-ingestion` | alembic head=`m4rgnxref01`（Phase 2 down_revision 接這）|
| excel-builder | `d:\PythonProjects\excel-builder` | — | 無 remote |

## ✅ 已完成

- **Phase 1 — `src/capitalapi/pricing.py`**（純標準庫 math）：Black-76 理論價 + 5 Greeks + Newton/bisection IV。
  `tests/test_pricing.py` **37 測試全綠**（有限差分驗 Greeks、獨立 NormalDist CDF 對照、parity、ATM/Hull 錨、IV round-trip+邊界）。
  - 🔴 **theta 正解 = `r·Price − decay`**（計畫稿/Phase 4 Excel 的 `−r·Call` 是錯的）。
  - 🔴 已修：IV bisection 端點 bug（σ 落下界回 5.0）、錯誤價格錨點（7.576083→7.5770821301）。
  - 對抗式複核（6 agent）確認 price/parity/delta/gamma/vega/theta/rho 全對。
- **Phase 0 — `scripts/spike_overseas_options.py`**：盤中已跑、抓到 **59,768 檔商品清單**（7 交易所）。
  - ✅ **symbol 格式破解**：`{ROOT}{履約價5碼}{月碼A-L Call/M-X Put}{年末碼}`（同 TXO 月碼）。詳見 `docs/symbol_format_spec.md`。
  - ✅ **到期日來自商品檔第 5 欄**（YYYYMMDD）→ 最高風險「到期日解析」解決（報價結構無到期欄、只有 nTradingDay）。
  - ✅ **訂閱格式（3023 真因）**：`RequestStocks` 的 `bstrStockNos` 須「**交易所,代碼**」為單位、多筆以 **`#`** 區隔（非逗號）+ `psPageNo=1` + 商品下載完成。spike 已自動 code→exchange 補前綴。
  - ✅ **報價欄位實測完成（11 檔跨 6 所、rc=0）**：23 欄 layout、`價格=raw/10^sDecimal`（逐商品不同：CBOT 3/CME 2/GC·DAX 1/HSI·JNI 0）、`strike=nStrikePrice`、nDenominator=1；F 可由同履約價 put-call parity 反推（玉米驗 F≈$4.15）。**Phase 0 全 PASS**，詳見 `docs/symbol_format_spec.md`。

## ▶️ 下一步（依賴排序）

1. ✅ **Phase 0 PASS（2026-06-16）** — symbol 格式 / 到期日 / 訂閱格式 / 報價欄位 + divisor 全確認，見 `docs/symbol_format_spec.md`。
   重跑驗證：`.\.venv\Scripts\python.exe scripts/spike_overseas_options.py --symbols "C00448G6,C00448S6,GC04455G6,ES07000F6" --seconds 60`（盤中、自動補交易所前綴）。
2. **Phase 2 — postgresql-db（現可開工）**（先 `/db-backup` schema `raw_quotes,ods_quotes`）：2 raw + 1 ods 表手寫 migration
   （`down_revision="m4rgnxref01"`、hypertable+compress）、ORM `overseas_option.py`、雙重 export。
3. **Phase 3 — macrodata `agencies/capital/`**（**非 capital-api**）：`import capitalapi`（OptionsQuoteManager + pricing）
   + `db`，寫 collector daemon（pump 主執行緒 + DB flush worker + queue + 斷線重連）+ ods_builder（算 IV）+ CLI。
   symbol_parser 重用 `ref_market.margin_root_xref`。
4. **capital-api 補強**：以 `D:\CapitalFuturesAPI` 官方範例為準，把選擇權串流 COM 能力做完整（OptionsQuoteManager 已具雛形）。
5. **Phase 4 — excel-builder** `build_overseas_options_greeks_seed()` + CLI（theta Excel 用 `… + r*Call`）。

## 鐵律

- raw 不可變：Greeks/IV/理論價/`expiry_date`/`tau_years` 絕不進 raw。
- DB 入庫/DDL 前必 `/db-backup`（`guard_db_backup` 近 12h 無備份會 BLOCK）；備份落 D/E NVMe 勿 H/G。
- postgresql-db autogenerate 不可用 → 手寫 migration；version table=`alembic_version_pgdb`。
- capital-api 僅 Windows（COM）；報價 pump（pythoncom/comtypes）；COM 物件只主執行緒碰、回調內禁 DB IO。
- 溝通繁體中文。
