# 群益海外選擇權 symbol 格式規格（Phase 0 spike 實測，2026-06-16）

> 來源：`scripts/spike_overseas_options.py` 的 RequestProducts → OnProducts（59,768 檔、7 交易所）。
> 商品檔每筆格式：`交易所代號,交易所名稱,商品代號,商品描述,到期日(YYYYMMDD)`
> 例：`OSE,大阪交易所,JNI20000G6,大日經2607C 20000 C,20260709`

## 1. symbol 拆解規則 ✅ 已破解

```
{ROOT}{履約價5碼零填}{月碼}{年末碼}
```

| 區段 | 規則 | 例 |
|---|---|---|
| ROOT | 變長英數（含週選前綴數字） | `C`(玉米)/`ES`(小SP)/`GC`(黃金)/`JNI`(大日經)/`HSI`(恆生) |
| 履約價 | **5 碼零填整數**（與 desc 末位數字一致） | `00448`=448、`19000`=19000 |
| 月碼 | **A–L = Call 1–12月；M–X = Put 1–12月** | F=Call6月、R=Put6月、I=Call9月、U=Put9月、X=Put12月 |
| 年末碼 | 西元年最後一位 | `6`=2026 |

- 與台指 TXO 同一套 Call/Put 月碼方案。
- desc 結構：`{中文品名}{YYMM}{C/P}{空格}{strike}{空格}{C/P}`，例 `玉米2607C 448 C`。
- 範例：`C00448G6` = 玉米(C) 履約價 448 G(Call 7月) 2026 → desc `玉米2607C 448 C`。

## 2. 到期日(LTD) 來源 ✅ 解決最高風險

- **商品檔第 5 欄直接給到期日 YYYYMMDD**（如 `20260626`）→ 不必靠交易所行事曆/ltd_rule 推算。
- 作法：RequestProducts 後，從 OnProducts 建 `{symbol → expiry_date}` map，ODS 端 join 取得 T。
- ⚠️ 報價結構 `SKFOREIGNLONG` 本身**無到期欄**（只有 `nTradingDay` 交易日）→ 到期務必取自商品檔，不可期待報價帶。

## 3. 履約價/價格 divisor（待報價確認）

- symbol 與 desc 的 strike 為整數（玉米 448 = $4.48？小麥 628、黃豆 1166 同為「美分」級）。
- 實際數值縮放由報價 `sDecimal`/`nDenominator` 決定（價格 = 整數 / divisor）。**待報價實測填**。
- ⚠️ NYM CL（原油）前月 strike 跨度 250..40000、中位 11950 與現價($70)不符 → CL strike 縮放特殊，MVP 先避開。

## 4. option root 目錄（→ Black-76 標的期貨對應，待補）

| 交易所 | 主要 root（檔數） |
|---|---|
| CME | ES 小SP、NQ 小那、MNQ 微那、MES 微SP、EW/EX 月底選 + 大量週選(E3x/D3x/X3x) |
| NYM | **GC 黃金 4282、CL 原油 3630、SI 白銀 1860、NG 天然氣** |
| Cboe | SPX 指數、VIX 波動率 |
| CBOT | YM 小道瓊、W 小麥、S 黃豆、C 玉米、TN/TY/US/UB/FV 美債 |
| Eurex | DAX 德國指數、STXE 藍籌50、FVS、OGBL 歐元10年債 |
| OSE | JNI 大日經、3JM/4JM 小日經(週選) |
| HKEx | HSI 恆生、HHI 國企 + 週選(3HS/4HS…) |

- **TODO**：option root → 標的期貨 root 對應（Black-76 的 F）。多數同名（ES 選 ↔ ES 期、C 選 ↔ 玉米期）；
  用 `ref_market.margin_root_xref` / `contract_specs` 對映。

## 5. 訂閱 / 連線實測

- **RequestProducts → OnProducts 串回 59,768 檔**（約 3MB）；分多批，需等下載完成。
- **`SKOOQuoteLib_RequestStocks(psPageNo, nos)`：psPageNo 必須帶 1**（官方文件；帶 0 失敗）。
- **3023 = SK_SUBJECT_STOCKNO_IS_INVALID（商品代碼無效）**：商品檔未下載完成就訂閱會觸發 → 必須等
  OnProducts 下載完（spike 已改 idle 偵測 + page=1）。
- 單帳號訂閱檔數上限：**待報價實測**（API PageNo 上限一般用戶為 1）。

## 6. 近 ATM 訂閱候選（前月、中位 strike；供報價實測）

```
玉米   Call C00448G6 / Put C00448S6   （前月到期 20260626）
黃豆   Call S01166G6 / Put S01166S6
小麥   Call W00628G6 / Put W00628S6
小SP   Call ES07000F6 / Put ES07000R6 （前月到期 20260618）
```

## 7. PASS 判定

- [x] symbol 可確定性拆解
- [x] 到期日來源已定（商品檔第 5 欄）
- [ ] 報價結構欄位實測（sDecimal/nDenominator/nStrikePrice/bid/ask/exchange…）← **下一步：訂閱上方候選**
- [ ] 選定 MVP 標的 root + 標的期貨對應
- [ ] flush 秒數依報價頻率定
- [ ] 單帳號訂閱上限
