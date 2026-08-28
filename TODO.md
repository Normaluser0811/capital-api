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
5. **驗證**：77 測試綠（32+4 條新增）、mutation 10/10 轉紅、三輪盤中實跑
   （67/67 快照、滾月三輪重現一致、16 檔結算鏈 14 檔鏈隱含逐位一致＋2 檔合法
   nRef fallback、OJ/可可/橡膠三檔異源錨逐位吻合）。
6. ⚠️ **明晨 06:30 首跑要盯**：17 檔滾月在生產 state 首次觸發（新合約冷鏈 →
   已收盤 nRef fallback 應接住；鋁留空一天）；resolve 應出現「滾月(量判/LTD/錨)」；
   若有 ⚠️ nRef ≠ 鏈上昨結 warning＝又一家交易所改寫，看得見即正常。
7. 🔜 **任務 4 未做（待 user 拍板）**：08-28 橡膠頁回修（發布 +0.08%、真值 +1.14%，
   內文敘事也錯）——重生成該頁需 user 確認。

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
