# 群益海外選擇權 symbol 格式規格（Phase 0 spike 實測，2026-06-16）— ✅ PASS

> 來源：`scripts/spike_overseas_options.py`（RequestProducts 59,769 檔 + 11 檔近 ATM 報價實測）。
> 商品檔每筆：`交易所代號,交易所名稱,商品報價代碼,商品名稱,最後交易日(YYYYMMDD)`
> 例：`OSE,大阪交易所,JNI20000G6,大日經2607C 20000 C,20260709`

## 1. symbol 拆解規則 ✅

```
{ROOT}{履約價5碼零填}{月碼}{年末碼}
```

| 區段 | 規則 | 例 |
|---|---|---|
| ROOT | 變長英數（含週選前綴數字） | `C`玉米/`ES`小SP/`GC`黃金/`JNI`大日經/`HSI`恆生 |
| 履約價 | **5 碼零填整數**（= nStrikePrice、與 desc 末位一致） | `00448`=448、`19000`=19000 |
| 月碼 | **A–L = Call 1–12月；M–X = Put 1–12月** | F=Call6月、G=Call7月、R=Put6月、S=Put7月、U=Put9月、X=Put12月 |
| 年末碼 | 西元年最後一位 | `6`=2026 |

- desc 結構：`{品名}{YYMM}{C/P}{空格}{strike}{空格}{C/P}`，例 `玉米2607C 448 C`。
- 範例：`C00448G6` = 玉米 履約 448 Call 7月 2026。

## 2. 到期日(LTD) ✅ — 商品檔第 5 欄直接給

- OnProducts 第 5 欄 = 最後交易日 YYYYMMDD（如 `20260626`）→ 建 `{symbol → expiry}` map 供 ODS 算 T。
- 報價結構 `SKFOREIGNLONG` **無到期欄**（只有 `nTradingDay` 交易日）→ 到期一律取自商品檔。

## 3. 訂閱（RequestStocks）✅ — 格式是關鍵（曾卡 3023）

```python
page = 1   # 官方文件 psPageNo「請固定帶 1」
# bstrStockNos：以「交易所代碼,商品報價代碼」為單位、多筆以 "#" 區隔（不是逗號！）
nos = "CBOT,C00448G6#CME,ES07000F6#NYM,GC04455G6"
page, rc = oo.SKOOQuoteLib_RequestStocks(page, nos)   # rc=0 SK_SUCCESS
```

- **必須帶交易所前綴**：裸代碼 `C00448G6` 或逗號分隔多檔 → `rc=3023 SK_SUBJECT_STOCKNO_IS_INVALID（商品代碼無效）`。
- 交易所代碼取自商品檔第 1 欄（spike 已自動 code→exchange 對照）。
- 前置條件：先 `EnterMonitorLONG` + 等 `IsConnected()==1`（OnConnect 3001=SK_SUBJECT_CONNECTION_CONNECTED），
  **且商品檔下載完成**才可訂閱（未完成也會 3023）。
- 實測 11 檔（跨 6 交易所）同 page=1 一次 OK；單帳號上限未觸（API PageNo 上限一般用戶=1）。
- Tick/五檔/十檔：`RequestTicks`/`RequestMarketDepth`，一個 page 一檔，格式同「交易所,代碼」。

## 4. 報價結構 SKFOREIGNLONG（23 欄）+ divisor ✅

欄位順序：`nStockIdx, sDecimal, nDenominator, bstrMarketNo, bstrExchangeNo, bstrExchangeName,
bstrStockNo, bstrStockName, bstrCallPut, nOpen, nHigh, nLow, nClose, nSettlePrice, nTickQty,
nRef, nBid, nBc(買量), nAsk, nAc(賣量), nTQty(成交量), nStrikePrice, nTradingDay`。

**價格解碼鐵律**：`價格 = raw / 10^sDecimal`（價量欄 open/high/low/close/settle/ref/bid/ask 皆是）；
`strike = nStrikePrice`（**不除**，已是最終單位、與解碼後報價同單位）；本籃 `nDenominator` 全 = 1。

| 商品 | 交易所 | sDecimal | divisor | 範例（raw→值） |
|---|---|---|---|---|
| 玉米/黃豆/小麥 | CBOT | 3 | ÷1000 | 玉米 put settle 33000→33.0¢ |
| 小SP ES | CME | 2 | ÷100 | call settle 56200→562.0 |
| 天然氣 NG | NYM | 3 | ÷1000 | bid 2→0.002 |
| 黃金 GC | NYM | 1 | ÷10 | settle 290→29.0 |
| 德國 DAX | Eurex | 1 | ÷10 | bid 12040→1204.0 |
| 恆生 HSI | HKEx | 0 | ÷1 | settle 2451→2451 |
| 大日經 JNI | OSE | 0 | ÷1 | settle 10810→10810 |

- ⚠️ `sDecimal` **逐商品不同**（必須讀每筆報價的 sDecimal，不可寫死）。
- ⚠️ 美債（TN/TY/US/UB/FV）可能 `nDenominator≠1`（32 進位分數制）→ MVP 先避開，之後另測。
- 非盤中/冷門時段：bid/ask 可能為 0（HSI/JNI 當下），但 settle/ref 有值。

## 5. Black-76 的標的價 F

- 同履約價 Call/Put 由 put-call parity 反推：`F = K + (C − P)·e^{rT}`。
  玉米實測 K=448, C≈0.5, P≈33 → F≈415.5¢($4.15) ✓。
- 或另訂閱標的期貨（SKOSQuoteLib 海期）取 F。Phase 3 決定（parity 法免再訂閱、較省）。

## 6. option root 目錄（→ 標的期貨對應，Phase 3 補）

| 交易所 | 主要 root |
|---|---|
| CME | ES 小SP、NQ 小那、MES/MNQ 微、EW/EX 月底選 + 週選 |
| NYM | GC 黃金、CL 原油、SI 白銀、NG 天然氣 |
| Cboe | SPX、VIX |
| CBOT | YM 小道瓊、W 小麥、S 黃豆、C 玉米、TN/TY/US/UB/FV 美債 |
| Eurex | DAX、STXE 藍籌50、FVS、OGBL |
| OSE | JNI 大日經、3JM/4JM 小日經 |
| HKEx | HSI 恆生、HHI 國企 |

## 7. PASS 判定 — ✅ 全數達成（可進 Phase 2）

- [x] symbol 可確定性拆解
- [x] 到期日來源（商品檔第 5 欄）
- [x] 訂閱格式（交易所,代碼#…、page=1）+ 連線/下載前置
- [x] 報價欄位 + divisor（price=raw/10^sDecimal、strike=nStrikePrice、nDenominator）
- [x] 報價頻率 ~1.4 筆/秒（11 檔）→ flush 2–3s
- [x] F 取得法（put-call parity 反推，或訂閱標的期貨）
- [ ]（Phase 3）option root → 標的期貨 root 對應；美債分數制；單帳號訂閱上限壓測
