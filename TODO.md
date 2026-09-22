# 🔴 2026-09-22 驗收：**不通過** → 已修四件（本段最新）

> user 說「應該可以驗收了」，於是派 14 名驗證員（7 蒐證 + 6 反駁 + 1 完整性批評）做
> 對抗式覆核。**三條反駁成立。** 09-21 那輪的宣稱字面上都撐得住，但範圍與安全網有實質破洞。

## ✅ 先說驗收點：09-22 早上 06:30 那輪生產線**逐格命中**

`daily_pct=1.3178`／`last_date=2026-09-21`／`last_close=48053.0`／`weekly_pct=4.6838`，
42 檔的資料日期分佈 `{'2026-09-21': 42}`（沒有落單的）。與前一晚寫進交接文件的預測相同。

## 🔴 驗收抓到的四件（都已修）

### ① 陳舊閘門三天後必定誤殺 —— 已改成只示警不改值

單一市場休市時，該市場商品的資料日期天生就比別人舊、而值是對的。
期交所 **2026-09-25／09-28** 休市（DB 實查）⇒ **09-26~09-29 連四份報告**的台指期
正確值會被清空，警告還寫「要查的是上游」把人導向沒壞的地方。
拿真實價格檔改成該形狀實跑：taiex `(0.5214, 1.11)` → `(None, None)`。
反方向也錯：「美盤休市隔天」多數商品自己也落後 ⇒ 基準跟著移動 ⇒ **零訊號放行錯值**
（未來一年 8 天，最近 2026-11-26）。

🔴 **最該記住的**：我拿來背書它的「28 份歷史檔零誤殺」在**結構上量不到**這件事——
讓資料日期會落後的上游改動 2026-09-16 才併入，28 份裡只有最後 6 份帶著它，
而那 6 天對所有走結算鏈的交易所**一次休市都沒有**。
**對照組裡根本沒有要測的那個條件**——這條正是我自己 memory 裡記過的坑。

⇒ 新鮮度改由**上游 capital-api 自己判**：官方行情裡的最大日期就是交易所自己認定的
最後一個交易日（休市日它根本不發資料），**不需要交易日曆**。對不上或拿不到就由它
輸出明確的 null。這一條同時擋掉另一個形狀：連假後盤中重跑會在休市日長出假節點
並算出 +0.00%（2026-09-29 15:00 會發生），與 2026-09-16 那次假平盤同型。

### ② 我引入的新風險：prompt 會「命令」模型寫出非交易日 —— 已擋

nikkei／kospi／hang_seng 走 SPOT_INDEX 混合法，**週日那份價格檔的資料日期會標成
星期六**（實測 08-30／09-06／09-13／09-20 四份 100% 如此，而值其實是星期五的）。
09-21 那版不只印出來，還用最高強度的規則**命令**模型照寫 ⇒ 把原本含糊但不算錯的
「單日上漲 0.60%」變成白紙黑字的錯誤交易日。下一次必然發生是 **2026-09-27（星期日）**。
現在解析不出來／週末／不早於報告日一律當成「不知道」，不印。

### ③ 全市場概覽那一列完全沒接上 —— 已補

它是唯一把 43 檔數字**聚合在一起**的那一列，也正是被錯值污染過而必須重做的那條線，
卻從頭到尾沒有日期資訊。歷史 22 列有 6 列（27%）用「今日」統攝這些其實是 D−1 的數字。
現在**逐列標**盤面日（單一市場休市時各商品天生就不同，不可統一標一天）。

### ④ 🔴 blocker：錯值流到了**第三個消費者**，而且修好之後產出的成品仍是錯的

trading-card 的 **podcast 線**讀同一個 Notion Daily Report 資料庫。
09-18／09-20 兩集的講稿與 MP3 在我 13:47 修好 DB/Notion **約 3 小時後**才產出，
內容卻仍是舊值（0.73%／0.87%，正確是 0.87%／2.09%），而且掛回了 Notion。
病因：素材快取的指紋只涵蓋設定、不涵蓋來源資料 ⇒ 來源改對了也不會失效。

🔴 我判斷「沒有其他消費者」的依據是 content-hub 與 notion-hub 兩份 TODO 寫的
「**實查全庫零下游消費者**」——**那兩句已經過期**（podcast 線後來上線了），
而我只查了 PG（view／pub／Superset 確實全 0），這條路徑走的是 Notion。
⚠️ 那兩句仍留在那兩個 repo 裡（**不在本次授權範圍**，未動），下一個人照樣會被誤導。

已修：日報那側一律問 live（單一分頁查詢、一次 API 呼叫），拿內容指紋跟快取比；
兩集已重產並**換掉** Notion 上的音檔（獨立複查：兩頁各只剩 1 個音檔、sha256 與本機新檔相同）。

## 📌 驗收也指出、但**尚未處理**的

| # | 事項 | 說明 |
|---|---|---|
| 1 | `raw_taifex.futures_daily` 缺 09-21 | TX 的 max(trade_date) 停在 09-18，而 macrodata 的班 09-21 17:00 有跑。⇒「用自家 DB 核對昨日結算」這條驗證路徑目前是壞的。**macrodata 不在授權內** |
| 2 | 連假後次日會留空 | `_chain_changes` 要求昨結 gap ≤ 4 個日曆天，而 09-29 − 09-24 = 5 ⇒ **2026-09-30** 那份即使一切正常也會留空。方向安全（留空不發錯），但可在 8 天後當場驗證 |
| 3 | weekly 空窗其實是 **6 天** | 09-16~09-21（不是我先前說的 5 天）。現行結算鏈已補到 09-09，這 6 天的週漲跌都算得出來，補不補待拍板 |
| 4 | content-hub／notion-hub 的「零下游消費者」過期句 | 不在授權內，未動 |
| 5 | 09-20 那集重產後沒把 +2.09% 講出來 | 改成質化描述，不算錯；屬 LLM 變異，未再燒點數重跑 |

## ⚠️ 兩個容易誤判的事實

- **排程是 06:30 不是 06:32**（`jobs.yml` 是 `cron[hour=6,minute=30]`）。
  06:32 是 capital-api dump 子行程落檔的時間。整份 `jobs.yml` **沒有** capital-api 的獨立班
  ——它是 scraper 那班用硬編碼路徑 spawn 的，存廢完全綁在 `bloomberg_daily_report` 上。
- **08:45 之後手動跑，未修版也會算出一模一樣的數字**（走盤中分支拿 nRef）
  ⇒ 白天做的抽查對這條修法是**零資訊量的假綠**。要驗必須在 08:45 前，或用盤前的快照形狀。

## 測試

scraper 2,948 → **2,961**｜capital-api 106 → **112**｜trading-card 396 → **400**。

---
# 🔴 2026-09-21：國內結算鏈**永遠落後一個交易日**已修 —— 改由期交所官方行情餵

> 分支 `fix/domestic-settle-chain-one-day-lag`｜探針 `0118f8b`／本體 `ba378a1`／文件 `8c904d0`
> 起因：user 在 scraper 那邊指出「台指期今天日報應該是 +2.09%」，實際發出去的是 +0.87%。

---

## 病灶

`_domestic_snapshot()` 硬寫 `settle: None`——國內的 `SKSTOCKLONG` **沒有 `nSettlePrice` 欄**
（2026-09-21 由新加的唯讀探針實測證實，此前只是文件這樣寫、沒人量過）。
唯一拿得到的結算價來源是 `nRef`，而它永遠是「`nTradingDay` 的**前一個**交易日」的結算；
`nTradingDay` 又要到**隔天 08:45 開盤**才跳。

**逐時點實測（同一天、同一個合約）**：

| 時點 | `nTradingDay` | `nRef` | 是哪一天的結算 |
|---|---|---|---|
| 06:32（排程跑的時點）| 20260918 | 46459 | 09-17 |
| 11:41（日盤中）| 20260921 | 47428 | 09-18 |
| **15:02 / 15:12 / 15:35**（夜盤已開 35 分）| **20260921** | **47428** | **仍是 09-18** |

⇒ 06:32 的排程**結構上**拿不到最後一個交易日的結算，`_feed_chain()` 只寫得進 `hist[L-1]`。
狀態檔實證：鏈停在 `{09-14, 09-15, 09-16, 09-17}`，**09-18 那筆從頭到尾不存在**。
實際後果：日報 **2026-09-17 ~ 09-21 連續 5 天**發出前一個交易日的漲跌幅，全部上了 Notion。

🔴 **「傍晚多跑一次餵鏈」這個修法實測不成立**（上表最後一列）。
這一列留在這裡就是為了不讓下一個人重走——夜盤開盤**不會**讓 `nTradingDay` 滾。

---

## 修法：06:32 當場向期交所要官方結算價，**先墊鏈再餵快照**

順序不可反。`_feed_chain` 的已收盤分支本來就是「鏈上有這一天就用鏈上的」，
官方值先進去之後那條分支自然拿到正確的當日結算 ⇒ **`_feed_chain` 一行都沒改。**

- `_taifex_official_settles()` —— `futDataDown` → `{契約月: {日期: 結算價}}`。
  ⚠️ **不要改用 `openapi.taifex.com.tw/v1/DailyMarketReportFut`**：同一天的 15:07／15:19／15:34
  三次，它回的最新日期都還停在 09-18，**比官網下載介面慢**。
  ⚠️ 走 stdlib `urllib` 不引入 `requests`（本專案是純 library、venv 裡也沒有 requests）。
  四條過濾各自對應一個會靜默出錯的形狀（`盤後` 列結算價是 `-`／價差月份長 `202610/202611`／
  最後交易日的結算價 0 哨兵相除得 −100%／`交易日 < as_of`）。
  🔴 取不到一律回 `{}` **不拋**：退回快照鏈，而下游 scraper 的陳舊閘門會把落後的值留空。
- `_domestic_contract_month()` —— 由商品清單的 LTD 推契約月，**不由代碼的兩位月份推**
  （跨年時 `TX01AM` 的年份要靠 as_of 猜，而清單裡本來就有確定答案）。
- `_seed_chain_from_official()` —— 官方值優先，但**改掉既有值一定要印出來**，
  否則哪天官方與快照系統性不一致，這裡會無聲改寫歷史而畫面完全正常。

---

## 驗收（不是只有假資料）

| 項目 | 結果 |
|---|---|
| 單元測試 | 93 → **106**（+13）|
| 端到端單測 | 同一個 06:32 快照：未墊官方值重現當天發錯的 **+0.8663%**、墊了之後 **+2.0857%** |
| **真實端點實跑** | `as_of=09-21` 最新 09-18=47428；`as_of=09-22` 最新 **09-21=48053** ⇒ 隔天 06:32 來得及 |
| **獨立雙路徑對帳** | 官網 CSV vs `raw_taifex.futures_daily`：7 個共同交易日**值不符 0**；差異只在邊界（09-21 官網有、DB 尚未載入 ⇒ 正好證明官網較新）|
| **完整 dump 實跑** | 「官方結算價寫入 4 筆」、**零筆「與鏈上既有值不同」**（＝鏈上原有 4 天本來就對）；鏈 4 天 → 8 天、原有各日值零改動；taiex 日 **+2.09%**、資料日 **09-18**；42 檔成功 0 失敗 |
| 下游閘門複驗 | 把產出丟進 scraper 的陳舊閘門：基準日 09-18、**判定陳舊 0 檔**、零商品被留空 |

---

## ⚠️ 附帶效果：週漲跌不再永遠留空

官方值一次帶回 12 個日曆天 ⇒ 鏈湊得滿 7 天 ⇒ `weekly_pct` 開始有值（實跑 +2.28%、
模擬明天 +4.68%）。此前一律 None 是「2026-09-14 才冷啟動」的真實「算不出來」，不是缺陷。
要關掉只需把 `_TAIFEX_LOOKBACK_D` 調小。**此事 user 尚未逐項確認，若不要就調那個常數。**

## 📌 明天的驗收點

明天（09-22）06:32 那輪，台指期應為 **+1.3178%**（48,053 / 47,428，官方 TX 202610 結算）、
資料日 **2026-09-21**。對不上就先看 dump 的 stdout 有沒有「期交所官方行情取得失敗」。

---

# ✅ 2026-09-16 下午：假日假平盤已修並併回 main —— 根因與文件記載的不同

> main `5c034b6`（merge）／`067d8a2`（fix）。分支 `fix/holiday-fake-settle-node` 已刪、無殘留。
> 全套 **93 passed**。user 當日拍板「擴指派範圍，我來修」。

## 🔴 訂正：根因**不是** `_prev_weekday`

同日稍早那段（P0-1）與 scraper／postgresql-db 兩邊的交接都寫著
「`_feed_chain()` 回推昨結算日時只跳週末 ⇒ 用 nRef 憑空補節點」。**離線重現後推翻。**

真正寫出假節點的是**已收盤分支最後那個 `else`**：

```python
if day_d < as_of:
    settle_date = day_d
    if q.get("settle"): ...            # 有結算價 ⇒ 權威
    elif hist.get(...): ...            # 鏈上已有 ⇒ 沿用
    elif q.get("ref_is_prev_day"): ... # 國內線
    else:
        settle_val = q["ref"]
        hist[settle_date.isoformat()] = settle_val   # 🔴 就是這一行
```

`day_d < as_of`（已收盤）＋ 沒有 `nSettle` ＋ 鏈上也沒有 `day_d` 時，
它把 `nRef` 當成 **`day_d` 當天**的結算價寫進鏈。
而休市日根本沒有結算價，`nRef` 是**前一個交易日**的結算
⇒ 鏈上多出一個與前一日逐位元組相同的節點 ⇒ 隔天 `daily = 同值 / 同值 - 1 = +0.00%`。

🔴 **週末之所以沒事，不是因為 `_prev_weekday` 擋住了**——是因為交易所根本不回報
週末的 `nTradingDay`。離線重現情境 C 證明：真餵一個週六進去，**同樣會捏造**。

## 🔴 訂正：不需要交易日曆

原註解寫「要靠可信的交易日曆才修得了」。**那個前提是錯的**，而且是雙重錯：

1. **交易日曆答不出該問的問題**。2026-09-07 勞動節那天 NYMEX／COMEX／CME 股指
   走的是**縮短時段、真的有成交**（CL=F 10.3 萬口），只是不產生當日結算價。
   用「交易所有沒有休市」當判準會誤刪真實資料。
2. **快照自己就答得出來**：`nSettle` 缺、且 `nRef` **仍等於鏈上最近一筆結算**
   ⇒ 那天沒有產生新的官方結算價。

### 判別器的實證

| 2026-09-07 有節點的鏈 | 條數 | 判讀 |
|---|---|---|
| 值與 09-04 **完全相同** | **49** | 美國線休市、無結算價 ⇒ 假節點 |
| 值與 09-04 **不同** | 7 | Brent／橡膠／恆生科技／A50 那天有開、有真結算 |

正常日「與前一節點等值」的基準率只有 **0~2%**（08-31 與 09-03 各 1/56），
而那些走的是 `nSettle` 權威分支、**根本進不到這個判斷** ⇒ 誤判成本極低。

## 改了什麼

- **已收盤分支**：判別器命中 ⇒ 不寫節點、在鏈上記一筆 `no_settle`，
  本日值退回鏈上最近一筆真結算（＝沿用前一個真實漲跌，與週末同行為）。
- **`_prev_weekday` 加 `no_settle` 參數**並在兩個呼叫點帶入。
  🔴 少了這步，隔天**盤中分支**會用 `setdefault` 把同一個假節點造回來——
  修一處不夠。
- **`_prune_entry`** 同窗（30 天）修剪 `no_settle`，不讓它無限長大。
- `_migrate_settle_entry` 對既有 schema 原樣回傳 ⇒ 新欄位不會被丟掉（實查確認）。

## 驗證（先紅後綠 ＋ 兩條刻意行為的回歸守衛）

1. 新增 7 條守衛：先失敗 5 條，實作後全套 **93 passed**。
2. 🔴 **從頭到尾綠的那兩條就是證據**，證明判別器沒有把刻意行為一起關掉：
   - `test_哨兵結算但nRef是新值_仍照舊寫入`（SGX 收盤後改寫 nRef，橡膠 2026-08-28）
   - `test_鏈是空的時候不可以自作聰明`（冷啟動）
   兩者的差別正是 **nRef 與鏈上最近一筆不同**。
3. 離線重現腳本：修正前鏈變成 `{09-04, 09-07}`，修正後維持 `{09-04}`。

---

## 🔴 訂正：台灣連假**不會**重演假平盤

scraper 交接寫「台指期接上後，台灣連假（春節／清明／端午／中秋）也會觸發同一個問題」。
**模擬後推翻。** 國內線走的是另一條路：`nTradingDay` 在休市日**停在最後交易日**、
不回報休市當天 ⇒ 不會捏造節點。

模擬台指期跨 2026-09-25（中秋，週五）＋ 09-28（教師節，週一）：

| 發報日 | 快照 day | 日漲跌 | |
|---|---|---|---|
| 09-25 / 09-28 / 09-29 | 09-24 | +0.2183 | ✅ 沿用 09-24 的真實漲跌（與週末同行為）|
| **09-30** | 09-29 | **留空** | ⚠️ 鏈上 09-24→09-29 相隔 **5 個日曆天 > 4 天容忍度** |
| 10-01 | 09-30 | −0.2165 | ✅ 回復正常 |

⇒ 台灣連假的症狀是**隔一個交易日留空**，不是假平盤。
⚠️ 這個模擬有一個**未驗證的假設**：休市日 `nTradingDay` 停在最後交易日。
支持它的是程式註解記載的實測（「09-16 06:57 台股 08:45 才開盤、nTradingDay 仍是 09-15」），
但那是平日、不是假日。台指期 09-11 才上線，**還沒經歷過任何台灣假日** ⇒ 09-25 是第一次。

**下一棒務必在 09-25～09-30 逐日記下 `nTradingDay` 與日漲跌**，驗證這個模擬。

## 🔴 訂正：下一次大規模發作是 11-26 感恩節，不是 09-25

假平盤需要「交易所回報休市當天為交易日」＝海外線的形狀。
價格鏈指紋掃描（30 天窗）：**09-07 是唯一的捏造日（49/56 ＝ 88%）**，其餘每天 0~2%。
依稽核推估未來 12 個月至少再犯 11 次，最近一次 **2026-11-26 感恩節**。
本次修正已經涵蓋它。

---

## 🟡 仍開放

### 1. 連假後那一天留空（Taiwan 與任何 > 4 天的連假）

`_chain_changes` 的昨結判準是 `1 <= (settle_date - prev_d).days <= 4`，
那是「連續交易日」的粗略代理。09-24 → 09-29 是**連續交易日**、真實日漲跌算得出來，
只是相隔 5 個日曆天就被擋掉。

🔴 **不可以盲目放寬**：那個 4 天窗擋的是「漏抓造成的資料洞」——放寬等於讓
多日變動偽裝成日漲跌（2026-09-11 快照整批失敗那次已經有 30 列是這個形狀）。
要修得靠「中間每個平日是不是都休市」，而那需要交易日曆。

### 2. TAIFEX 行事曆對未來零覆蓋（前置）

實查：441 列、涵蓋 1998-10-05 ~ **2026-07-10**、`kind` **全部**是 `derived_no_tick_file`
（從「那個平日沒有逐筆來源檔」反推）。

🔴 **那本書不可信**：它把「休市」與「我們沒有檔案」混在一起。
與 TWSE 的 `scheduled`（官方預定假日，排到 2035-12-31）比對重疊期：

| | 天數 |
|---|---|
| 兩邊都有 | **410** |
| 只有 TAIFEX | 31（含 2024-10-31 颱風停市＝TWSE 記在 `unscheduled_closure`；1999–2001 一串像早期資料缺口）|
| 只有 TWSE | 2 |

⇒ 一致率 93%，分歧集中在**預定行事曆本來就預測不到**的非預定停市。
照 TWSE 的 `scheduled` 補 TAIFEX 未來會新增 **144 列（2026-09-25 ~ 2035-12-31）**。
**待 user 拍板**——那張表歸 contract-stitcher 管，且寫既有表要另做針對性備份。

### 3. 09-08 那 28 列的**文章內文**還沒改（落點在 scraper／notion-hub）

09-15 的更正只改了 `daily_pct` 數值欄。實查 `ods_bloomberg.daily_report` 09-08：
**44 檔裡有 27 檔**的 `note`／`bullets` 仍寫著 `+0.00%`
（鋁：數值欄 −0.6436、文章「日漲跌幅為 +0.00%，盤面走勢呈現平盤整理」）。
⇒ 同一列自己打自己，而讀者在 Notion 上看到的是**文章**。

### 4. 鏈上那 49 個 09-07 假節點還在

本次修正只防止**未來**再產生，沒有回頭清除既有的。
評估後**判定無害**：它們的值與 09-04 逐位元組相同 ⇒ 週漲跌取基準時算出來一樣，
而 30 天修剪窗會在 **2026-10-07** 自動清掉。要提前清需另做針對性備份。

---

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
