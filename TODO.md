# Capital API 待辦事項

**最後更新**: 2026-06-16

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
- [ ] **Phase 4**：excel-builder `build_overseas_options_greeks_seed()` + CLI（**theta 公式採上方更正**）
- [ ] 端到端驗證（數學單元 / 串流煙霧 / ODS IV / Excel parity）

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
