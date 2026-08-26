# 海期價格源 Phase A0 盤中 spike 結論（2026-08-26）

> 對應計畫：`~/.claude/plans/bfw-daily-report-capital-price-and-commodity-expansion.md`
> Part 1「群益價格源」Phase A0 五個待答問題。
> 工具：`scripts/spike_overseas_futures_a0.py`（探勘腳本，不入庫）；
> 原始 capture：`docs/overseas_futures_spike_a0_capture_*.md`（gitignored，重跑即重建）。
> 實測時間：2026-08-26 09:56–10:03 台北（= CT 週一 20:56–21:03，CME/CBOT 夜盤、
> OSE/SGX/FX 日盤開市中；ICEUS 軟性商品、CME 畜產日盤休市中——正好兩種狀態都採到樣）。

## 結論總表

| # | 問題 | 答案 |
|---|------|------|
| Q1 | 線上商品檔複驗 | ✅ 線上 1,313 檔（xlsx 1,208 檔為 2025-03 舊版）。計畫 44 個目標代碼 **43 個確認在線**；唯一缺口＝**鋁沒有 HOT**（`ALI0000` 不存在，只有逐月 `ALI2608`–`ALI2701`）。FX 現貨頁（`FX,SUSDJPY`…）與 INDEX 延遲頁（`INDEX,NI225`…）**與海期同一條 `SKOSQuoteLib_RequestStocks` 通道可訂、可推播、可查 KLine** |
| Q2 | 海期歷史日K API | ✅ 有：`SKOSQuoteLib_RequestKLineByDate("交易所,代碼", 1, YYYYMMDD, YYYYMMDD, 1)` → `OnKLineData`。HOT／逐月合約／FX 頁／INDEX 頁全部吃得到；值已解碼（非原始整數）；資料給到**前一交易日**（進行中交易日不含）。🔴 **但 HOT 的 KLine 是換月拼接序列，見下** |
| Q3 | nRef/nClose 交易日語意 | ✅ 已釐清（見下節）；nRef＝**該 nTradingDay 交易日的昨結（正式結算價）**，nSettlePrice＝該交易日自己的結算價（未結算前＝nRef 同值） |
| Q4 | HOT 映射具體合約 | ✅ 雙重可解：① `GetOverseaProductDetail(1)` 的商品下單代碼欄＝`{root}_{YYYYMM}`（如 `KC_202612`）直接明示當下映射；② HOT 商品名自帶月份（「咖啡熱**2612**」）。訂閱驗證 `C0000` 與 `C2609` 逐欄位相等 |
| Q5 | 登入併發 / 維護窗 | ✅ 同 ID 兩行程並行 API 登入＋海期報價連線**不互踢**（A 全程 IsConnected=1、零重連事件，B 正常登入取價）。維護窗：官方手冊**無記載**，留 A2 的 06:00 排程試跑觀察 |

## 🔴 最重要發現：HOT 的 KLine 也是換月拼接（與 yfinance 同構的雷）

咖啡 HOT 於 08-22~25 間由 2609 移倉到 2612，正好可判別：

| 日期 | KC0000（HOT）KLine | = 哪個合約 |
|---|---|---|
| 08-12 | 336.60 / 342.05 / 333.40 / 337.45 vol 14743 | **KC2609**（Sep）逐欄位相等 |
| 08-25 | 342.80 / 345.65 / 329.00 / 334.85 vol 18004 | **KC2612**（Dec）逐欄位相等 |

⇒ HOT KLine＝「舊日期給舊合約、新日期給新合約」的無回調拼接。**跨換月日的 bar-over-bar
漲跌一樣是合約價差假值**（KC2609 08-25 收 372.50 vs KC2612 收 334.85，差 -10%）。

**正解（A1/A2 設計依據）**：
1. 用 detail 下單代碼（`KC_202612`）解析 HOT 當下映射的具體合約；
2. 週漲跌抓**該具體合約自身的 KLine**（逐月合約 KLine 乾淨，KC2609 到最後 vol=49 都有）；
3. 日漲跌用即時報價的 `nClose / nRef`（天生同合約＋正式結算價，這是群益源的核心價值，不受此雷影響）；
4. 快照入庫時**必存映射合約欄**（計畫的 `hot` 欄），跨日拼接由 ods 層以合約鍵防護。

## Q3 語意細節（09:58 台北實測，24/24 檔皆收到推播）

**夜盤已開的市場**（CBOT 穀物/公債、NYM 金屬/能源、CME 匯率/指數、ICEEU 布蘭特、
OSE/SGX/FX/INDEX 日盤）：

- `nTradingDay=20260826`（新交易日）、`nRef = nSettlePrice = 08-25 結算價`、`nClose`＝新交易日盤中價。
- ⇒ **當日盤中漲跌 = nClose/nRef − 1，天生同合約**。
- 例：玉米 C0000 close 505.00 / ref 500.50；金 GC0000（dec=1）close 4716.2 / ref 4694.5；
  十年債 TY0000 dec=6（32 分數制已由 API 解成十進位，nDenominator 不需另處理）。

**日盤未開的市場**（ICEUS 軟性商品 KC/SB/DX、CME 畜產 LC/FC）：

- `nTradingDay=20260825`（仍是已完成的交易日）、`nSettlePrice`＝該日結算、`nRef`＝再前一日結算、
  `nClose`＝該日最後成交。
- ⇒ **已完成交易日的日漲跌 = nSettlePrice/nRef − 1 直接可算**（如 SB：17.27/17.65 = −2.15%）。
- ⚠️ `nSettlePrice ≠ nClose`（最後成交 vs 結算，如 KC 334.85 vs 335.50）——**結算口徑一律用
  settle/ref，不用 close**；KLine 的收盤欄＝最後成交價，亦非結算價。

**06:30（排程時點）推論 + 待複測**：06:30 台北＝17:30 CT，CME 金屬/能源/匯率/指數新電子盤
已開 30 分（狀態＝上表第一種，昨日漲跌＝快照史或 KLine 的昨結序列）；CBOT 穀物 19:00 CT
才開（06:30 時介於兩盤之間，nTradingDay 停在哪一天**未實測**）；ICEUS 軟性商品未開
（狀態＝第二種，settle/ref 直接可算）。⚠️ **穀物在 06:30 的欄位狀態要在明晨 06:30 補一次
`--symbols "CBOT,C0000#..."` 實測**（A1 開工前做，一次 2 分鐘）。

## 其他實測記錄

- 更新頻率：45s 內 24 檔共約 1,600+ 筆推播，活躍檔（ES/GC/CL）秒級多筆 → collector 取樣
  flush 2s 的既有設計沿用即可。
- `ALI2609` 夜盤 `nClose=0`（尚無成交）但 ref/settle 有值 → **close=0 是「本節尚無成交」哨兵，
  必須 guard**（用 ref/settle 補位，勿把 0 當價格）。
- 鋁（無 HOT）：A1 要自建「近月選擇」——detail 有每月 LTD，選最近未到期月即可（或比對
  各月 volume）。
- 訂閱格式：`RequestStocks(psPageNo=-1 自動配號, "CBOT,C0000#ICEUS,KC0000#…")`；
  **含任一無效代碼整批被拒**（3023），故訂閱清單一律先過線上商品檔驗證。
- 報價事件僅 `pythoncom.PumpWaitingMessages` 泵得到（comtypes.PumpEvents 收不到），
  與 2026-06-16 海選結論一致。
- FX 現貨頁方向與市場慣例一致（SUSDJPY 159.03 = USDJPY），與拍板②吻合。
- 商品檔 `ltd=0/99991231`＝不可交易頁（FX/INDEX 現貨），可作「現貨頁 vs 期貨」判別欄。
- 群益海期報價連線：登入即佔一條海期報價連線（手冊 4-5 註記）；`GetQuoteStatus` 回
  `[0, False, 0]`（連線數資訊，未見超限）。

## 對 Phase A1/A2 的直接輸入

1. capital-api 海期封裝（A1）需要的 API 面：`EnterMonitorLONG` / `RequestOverseaProducts` /
   `GetOverseaProductDetail(1)`（含 HOT 映射）/ `RequestStocks(-1, "exch,code#…")` /
   `GetStockByIndexLONG`·`GetStockByNoLONG` / `RequestKLineByDate` / `LeaveMonitor`。
2. raw 表（A2）欄位依 SKFOREIGNLONG 24 欄照搬（同海選慣例：原始整數＋sDecimal），
   另存 `hot_contract`（detail 解析的 `{root}_{YYYYMM}`）。
3. 日報日漲跌＝快照 `nClose/nRef`；週漲跌＝映射合約 KLine（**絕不用 HOT KLine 跨換月**）。
4. 對照期（A3）oracle 用彭博信件/交易所結算，**不可拿 yfinance 驗 yfinance**（既有鐵律）。
