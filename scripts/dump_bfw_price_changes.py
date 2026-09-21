"""BFW 日報價格檔 dump：群益 SKOSQuoteLib → 日／週漲跌幅 JSON。

供 scraper `daily-report --price-file` 使用（2026-08-26 user 指示：日報漲跌幅改用
群益 API 報價）。這是 A1/A2 正式管線落地前的過渡工具——COM 只在本腳本內使用，
scraper 生成管線不碰 COM。

方法（依 Phase A0 結論 `docs/overseas_futures_spike_a0.md` + 2026-08-28 覆核計畫）：
- 期貨＝**結算價鏈**：快照 nRef/nSettle＝正式結算價，逐日存 `data/bfw_settle_state.json`，
  日漲跌＝今結算/昨結算（同合約）。🔴 昨結「鏈 history 優先、nRef 只當 fallback」
  ——SGX 收盤後會把 nRef 改寫成非昨結的值（2026-08-28 橡膠 +0.08% vs 真值 +1.14%）。
- **最活絡月自動換月**（2026-08-28）：候選＝LTD 排序近月＋次月（錨＝state active 與
  HOT 映射較晚者，單向不回滾；鋁無 HOT 走同一套）；次月連 2 完成日成交量 > 近月
  → 切換報導合約（橘子汁：HOT 08-28 仍指 Sep、市場 08-24 已移倉 Nov）。兩條鏈
  平常一起養（雙合約 state），切換日昨結已在鏈上＝無縫。
  🔴 絕不用 HOT 的 KLine 算跨日漲跌——它是換月拼接序列（KC0000 實證），
  與 yfinance 同一種雷。
- FX 現貨頁／INDEX 延遲頁：代碼自身日K（無合約無換月）；INDEX 走混合法。
- 漲跌幅語意**鏡射 scraper `materials._changes_from_closes`**：只取 `< as_of` 且
  非週末的 bar；日＝最近一根 vs 前一根；週＝最近一根 vs 最近的「≤7 日曆天前」bar；
  最近 bar 距 as_of > 7 天＝過期序列 → 整組留空。
- ⚠️ KLine 收盤欄＝最後成交價非結算價（A0 結論）——只用於週漲跌過渡與
  鏈未接上的 fallback；成交量欄（parts[5]）供滾月判準。

用法：
  python scripts/dump_bfw_price_changes.py                  # as_of=今天（台北）
  python scripts/dump_bfw_price_changes.py --date 2026-08-26 --out d:/tmp/bfw_capital_prices.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date as _date, datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import comtypes.client  # noqa: E402

from capitalapi import CapitalClient  # noqa: E402
from capitalapi.skcom import create_os_quote_lib, get_sk_module  # noqa: E402

# commodity key（scraper commodities.yml）→ 群益來源
# kind: hot＝HOT 檔解映射合約後抓該合約日K；spot＝代碼自身日K；front＝逐月自選近月
FUTURES_HOT: dict[str, tuple[str, str]] = {
    "brent_crude": ("ICEEU", "B0000"),
    "wti_crude": ("NYM", "CL0000"),
    "wheat": ("CBOT", "W0000"),
    "corn": ("CBOT", "C0000"),
    "soybean": ("CBOT", "S0000"),
    "soybean_oil": ("CBOT", "BO0000"),
    "copper": ("NYM", "HG0000"),
    "gold": ("NYM", "GC0000"),
    "silver": ("NYM", "SI0000"),
    "rubber": ("SGX", "STF0000"),
    "sugar": ("ICEUS", "SB0000"),
    "live_cattle": ("CME", "LC0000"),
    "coffee": ("ICEUS", "KC0000"),
    "rough_rice": ("CBOT", "RR0000"),
    "cotton": ("ICEUS", "CT0000"),
    "cocoa": ("ICEUS", "CC0000"),
    "lean_hog": ("CME", "LH0000"),
    "orange_juice": ("ICEUS", "OJF0000"),
    "oats": ("CBOT", "O0000"),
    "dollar_index": ("ICEUS", "DX0000"),
    "ust_10y": ("CBOT", "TY0000"),
    "palladium": ("NYM", "PA0000"),
    "platinum": ("NYM", "PL0000"),
    "heating_oil": ("NYM", "HO0000"),
    "natural_gas": ("NYM", "NG0000"),
    "rbob_gasoline": ("NYM", "RB0000"),
    "feeder_cattle": ("CME", "FC0000"),
    # 指數期貨（2026-08-26 user 指正後補上）。⚠️ 亞系指數期貨的日 bar 含夜盤到凌晨
    # （含美股時段），close-chain 與現貨收盤漲跌可以差到方向翻轉（實測富時台期貨
    # +0.43% vs 加權指數 -0.55%）——所以只有下列兩類進這張表：
    # ① 美系（ES/YM）：期貨收盤 16:00 CT vs 現貨 15:00 CT，口徑差 ~0.1pp 可忽略；
    # ② 恆科/A50：無現貨源（原本永遠留空），期貨 close-chain 自身一致，標注口徑。
    # 日經/恆生/Kospi 走 SPOT_INDEX 混合法（現貨口徑）；台股 taiex 群益無可用源
    # （富時台≠加權且含夜盤、國內指數線需證券帳戶）→ UNCOVERED 留 DB。
    "sp500": ("CME", "ES0000"),             # 小SP
    "dow": ("CBOT", "YM0000"),              # 小道
    "hang_seng_tech": ("HKEx", "HTI0000"),  # 恆生科技（期貨口徑，含夜盤）
    "ftse_a50": ("SGX", "CN0000"),          # 富時A50（期貨口徑，含夜盤）
}
SPOT: dict[str, tuple[str, str]] = {
    "jpy": ("FX", "SUSDJPY"),
    "gbp": ("FX", "SGBPUSD"),
    "eur": ("FX", "SEURUSD"),
    "chf": ("FX", "SUSDCHF"),
    "cad": ("FX", "SUSDCAD"),
    "aud": ("FX", "SAUDUSD"),
}
# 🔴 INDEX 現貨頁三檔走「混合法」（2026-08-26 定案）：
# - 日K 最後一根不可信——KOSPI 實測「今天盤中值掛昨天日期」（歷史列與 DB ^KS11 逐日
#   全等、唯最後一根 6742.74 vs 真值 6642.71）。
# - 但快照的 nRef＝現貨**正式昨收**（NI225 實測 65856.43＝08-25 收盤，逐位吻合）。
# ⇒ 昨收用快照（nRef 或未開盤時 nClose）、前日收/週基準用日K「完成 bar」（< 昨收日），
#   兩種盤態都不吃日K 最後一根 → 污染免疫，且數字＝現貨口徑（與新聞收盤行情一致）。
SPOT_INDEX: dict[str, tuple[str, str]] = {
    "nikkei": ("INDEX", "NI225"),
    "kospi": ("INDEX", "KOSPI"),
    "hang_seng": ("INDEX", "HHHSI"),
}
# 🔴 結算價累積法（user 拍板 2026-08-26）：COMEX 鋁極薄——最後成交序列是雜訊
# （ALI2608 全零成交＝結算順延平 bar；ALI2609 最後成交離結算 2.7%），但快照 nRef＝
# **正式結算價**（零成交日交易所也每天發布）。dump 每天把 nRef 存進 data/ 狀態檔，
# 隔日起用「今結算/昨結算」算日漲跌（同合約、結算對結算）；週漲跌等歷史累積滿 7 天。
# 冷啟動：首日留空。無 HOT → 候選走 LTD 近月/次月同一套（雙鏈平養，換約無縫）；
# 鏈未接上**不退**最後成交鏈（極薄合約序列是雜訊）。
SETTLE_CHAIN: dict[str, tuple[str, str]] = {
    "aluminum": ("NYM", "ALI"),
}
STATE_PATH = ROOT / "data" / "bfw_settle_state.json"

# 🔴 國內期貨（2026-09-15 新增）：走群益**國內**報價線 SKQuoteLib，與海外線
# SKOSQuoteLib 是兩條各自獨立的連線。
#
# 為什麼是現在才加：舊註解寫「台股加權群益無可用源」，那句話對的是**加權指數現貨**
# （國內指數線需證券帳戶）與**富時台指期貨**（SGX，標的不同且含夜盤，實測方向翻轉）。
# 台指期（TAIFEX）不在那兩個排除理由裡，只是從來沒人試過。2026-09-15 實測：
# 國內線連得上、台指期日K 與快照都拿得到（user 拍板改用台指期當日報標的）。
#
# 🔴 查詢代碼與下單代碼不是同一個東西。商品清單（RequestStockList(2)）每一筆長這樣：
#       查詢代碼, 名稱,   到期日,   下單代碼, 契約乘數|tick|, 幣別
#       TX09AM,  台指09, 20260916, TXFI6,   100000| 1 | ,  NTD
#    要用來查詢的是 **TX09AM**；`TXFI6` 是下單代碼，丟進 GetStockByNoLONG 或
#    RequestKLineAMByDate 一律回 SK_FAIL（rc=9999）。這一條踩過整整五輪。
#
# 🔴 日漲跌走**快照結算鏈**、不走 K 線：國內線的日K 只有連續代碼（TX00「台指近」）
#    拿得到，具體月份合約一律 rc=9999。而連續序列是無回調拼接——2026-09-15 實測
#    近月 TX09AM nRef=45777 vs 次月 TX10AM nRef=45903，換月當天會**憑空跳 +0.28%**，
#    比日報裡很多真實單日變動還大。所以照 aluminum 那套「結算價累積法」做：
#    每天把快照的 nRef 存進鏈，隔日起用「今結算/昨結算」算。
#    代價是冷啟動——鏈要養滿 7 天週漲跌才有值（user 2026-09-15 知情並同意）。
DOMESTIC_CHAIN: dict[str, tuple[str, str]] = {
    "taiex": ("TAIFEX", "TX"),      # 台指期；查詢代碼 TX<月><AM>，如 TX10AM
}
#: 國內查詢代碼的形狀：root + 兩位月份 + "AM"。刻意排除 TX00AM（那是近月**連續**）。
_DOMESTIC_CODE_RE = r"^{root}(\d{{2}})AM$"

# 走 scraper DB fallback 的商品（群益沒有同口徑來源）。
# 2026-09-15：taiex 移出此清單，改由 DOMESTIC_CHAIN 供應。
UNCOVERED: tuple[str, ...] = ()

_STALE_DAYS = 7


class _State:
    def __init__(self):
        self.detail: list[str] = []
        self.detail_done = False
        self.last_frag_ts: float | None = None
        self.kline: dict[str, list[str]] = {}
        self.kline_last_ts: float | None = None
        self.quotes: dict[str, dict] = {}   # code -> {close, ref, day}（已除 10^sDecimal）


def _make_pump():
    import pythoncom

    def pump(seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            pythoncom.PumpWaitingMessages()
            time.sleep(0.05)

    return pump


def _build_event(state: _State, os_lib, sk):
    class Ev:
        def OnConnect(self, code, socket_code):
            print(f"[OnConnect] code={code} socket={socket_code}")

        def OnOverseaProducts(self, value):
            pass

        def OnOverseaProductsDetail(self, value):
            state.detail.append(str(value))
            state.last_frag_ts = time.time()
            if str(value).startswith("##"):
                state.detail_done = True

        def OnKLineData(self, stock_no, data):
            state.kline.setdefault(str(stock_no), []).append(str(data))
            state.kline_last_ts = time.time()

        def OnNotifyQuoteLONG(self, index):
            # SPOT_INDEX 混合法 + SETTLE_CHAIN 用：抓快照的 nClose/nRef/nSettle/nTradingDay
            try:
                stock = sk.SKFOREIGNLONG()
                stock, rc = os_lib.SKOSQuoteLib_GetStockByIndexLONG(index, stock)
                if rc != 0:
                    return
                divisor = 10 ** int(stock.sDecimal)
                state.quotes[str(stock.bstrStockNo)] = {
                    "close": stock.nClose / divisor,
                    "ref": stock.nRef / divisor,
                    "settle": stock.nSettlePrice / divisor,
                    "day": int(stock.nTradingDay),
                }
            except Exception as exc:  # noqa: BLE001
                print(f"[OnNotifyQuoteLONG] 解析失敗: {exc}")

        def OnNotifyTicksNineDigitLONG(self, *a):
            pass

        def OnNotifyBest5NineDigitLONG(self, *a):
            pass

        def OnNotifyBest10NineDigitLONG(self, *a):
            pass

        def OnNotifyHistoryTicksNineDigitLONG(self, *a):
            pass

    return Ev()


def _parse_detail(fragments: list[str]) -> dict[str, dict]:
    """detail 片段 → {報價代碼: {exch, name, order_code, ltd}}。

    格式（手冊 4-5-d）：[交易所代碼],[交易所名稱],[商品報價代碼],[商品名稱],
    [交易所下單代碼],[商品下單代碼],[最後交易日],[第一通知日](,小數位?)
    """
    out: dict[str, dict] = {}
    for frag in fragments:
        for line in str(frag).replace("\r", "\n").split("\n"):
            line = line.strip()
            if not line or line.startswith("##"):
                continue
            parts = line.split(",")
            if len(parts) < 7:
                continue
            out[parts[2]] = {
                "exch": parts[0], "name": parts[3],
                "order_code": parts[5], "ltd": parts[6],
            }
    return out


def _hot_mapped_code(catalog: dict[str, dict], hot_code: str) -> str | None:
    """HOT 檔的下單代碼 `{order_root}_{YYYYMM}` → 報價代碼 `{quote_root}{YYMM}`。

    ⚠️ 月份取自下單代碼，root 取自 HOT **報價**代碼——兩者的 root 可以不同
    （橘子汁報價 root=OJF、下單 root=OJ，實測 2026-08-26）。
    """
    rec = catalog.get(hot_code)
    if not rec:
        return None
    m = re.fullmatch(r"[A-Z0-9]+_(\d{6})", rec["order_code"])
    if not m:
        return None
    quote_root = hot_code[:-4]  # 去掉 '0000'
    return f"{quote_root}{m.group(1)[2:]}"


def _changes_from_closes(closes: dict[_date, float], as_of: _date):
    """鏡射 scraper materials._changes_from_closes 的語意（含週末/過期守衛）。"""
    dates = sorted(d for d in closes if d < as_of and d.weekday() < 5)
    if len(dates) < 2:
        return None
    latest_date = dates[-1]
    if (as_of - latest_date).days > _STALE_DAYS:
        return None
    latest, prev = closes[latest_date], closes[dates[-2]]
    daily = (latest / prev - 1) * 100 if prev else None
    weekly = None
    week_ago = latest_date - timedelta(days=7)
    for d in reversed(dates[:-1]):
        if d <= week_ago:
            base = closes[d]
            weekly = (latest / base - 1) * 100 if base else None
            break
    return {
        "daily_pct": round(daily, 4) if daily is not None else None,
        "weekly_pct": round(weekly, 4) if weekly is not None else None,
        "last_date": latest_date.isoformat(),
        "last_close": latest,
        "prev_date": dates[-2].isoformat(),
        "prev_close": prev,
    }


def _hybrid_index_changes(q: dict | None, closes: dict[_date, float], as_of: _date,
                          series: str) -> dict:
    """SPOT_INDEX 混合法：昨收取快照（污染免疫）、前日收/週基準取日K 完成列。

    兩種盤態（A0 Q3 語意）：
    - 快照 day == as_of（今天已開盤）：昨收＝nRef；前日收＝日K「昨天以前」的最大完成列
      （「昨天」那根日期可信、值不可信——KOSPI 污染列掛的就是昨天日期，故只取其日期）。
    - 快照 day < as_of（未開盤）：昨收＝nClose、前日收＝nRef。
      🔴 但 INDEX 頁收盤後會把 nRef 滾成「昨收」（nClose==nRef；2026-08-28 06:31 實測
      NI225/KOSPI 中招 → 兩頁發布 +0.00% 假值，HHHSI 當時未滾所以正確；各所滾動時點
      不同）→ 偵測到該簽名時前日收改用日K「< 昨收日」的完成列（未開盤時日K 無盤中
      污染列，< day_d 的列可信）。
    """
    def _null(reason: str) -> dict:
        return {"daily_pct": None, "weekly_pct": None, "series": series,
                "resolve": f"混合法失敗：{reason} → 留空"}

    if not q or not q.get("ref"):
        return _null("快照未取得（nRef 空）")
    day = q["day"]
    try:
        day_d = _date(day // 10000, day // 100 % 100, day % 100)
    except ValueError:
        return _null(f"nTradingDay 異常（{day}）")
    dates = sorted(d for d in closes if d < as_of and d.weekday() < 5)

    if day_d >= as_of:
        # 今天已開盤：昨收=nRef；昨收日=日K < as_of 的最大日期（僅取日期）
        if len(dates) < 2:
            return _null("日K 完成列不足")
        last_date, prev_date = dates[-1], dates[-2]
        last_val = q["ref"]
        prev_val = closes[prev_date]
        mode = f"開盤中：昨收=nRef({last_val})、前日收=日K {prev_date}"
    else:
        # 未開盤：快照本身就是已完成日
        last_date = day_d
        last_val = q["close"]
        prev_val = q["ref"]
        prev_date = "快照nRef"
        mode = f"未開盤：昨收=nClose({last_val})、前日收=nRef({prev_val})"
        if last_val and prev_val and abs(last_val - prev_val) < 1e-9:
            # 🔴 nClose==nRef＝「nRef 已被滾成昨收」簽名 → 前日收退日K 完成列
            hist_dates = [d for d in dates if d < last_date]
            if not hist_dates:
                return _null("nRef 已滾成昨收（==nClose）且日K 無更早完成列")
            prev_date = hist_dates[-1]
            prev_val = closes[prev_date]
            mode = (f"未開盤：昨收=nClose({last_val})、前日收=日K {prev_date}"
                    "（nRef 已滾成昨收，棄用）")

    if (as_of - last_date).days > _STALE_DAYS:
        return _null(f"昨收日 {last_date} 距 as_of 過久")
    daily = (last_val / prev_val - 1) * 100 if prev_val else None

    weekly = None
    week_ago = last_date - timedelta(days=7)
    for d in reversed([d for d in dates if d < last_date]):
        if d <= week_ago:
            weekly = (last_val / closes[d] - 1) * 100 if closes[d] else None
            break

    return {
        "series": series, "resolve": f"SPOT_INDEX 混合法（{mode}）",
        "daily_pct": round(daily, 4) if daily is not None else None,
        "weekly_pct": round(weekly, 4) if weekly is not None else None,
        "last_date": last_date.isoformat(), "last_close": last_val,
        "prev_date": str(prev_date), "prev_close": prev_val,
    }


def _month_codes(catalog: dict[str, dict], quote_root: str, as_of: _date) -> list[str]:
    """root 的逐月報價代碼，依 LTD 升冪；只留 LTD ≥ as_of+3 天（臨到期月＝強制滾月保險）。

    比對沿用「報價 root + 4 位數字」fullmatch（與舊 _chain_front_contract 同款；
    刻意不比對交易所欄——catalog 的 exch 欄格式未經驗證，錯比會整批落空）。
    """
    out: list[tuple[str, str]] = []
    for code, rec in catalog.items():
        if not re.fullmatch(re.escape(quote_root) + r"\d{4}", code):
            continue
        ltd = rec.get("ltd", "")
        if not re.fullmatch(r"\d{8}", ltd) or ltd in ("0", "99991231"):
            continue
        try:
            ltd_d = _date(int(ltd[:4]), int(ltd[4:6]), int(ltd[6:]))
        except ValueError:
            continue
        if ltd_d < as_of + timedelta(days=3):
            continue
        out.append((ltd, code))
    return [c for _ltd, c in sorted(out)]


def _pick_candidates(months: list[str], anchors: list[str | None]) -> tuple[str, str | None]:
    """候選＝(近月, 次月)。錨（state active_code / HOT 映射月）取「較晚 LTD」者＝單向不回滾；
    錨不在 months（已被 LTD 濾掉）→ 從第一個可用月起＝強制滾月。"""
    idx = 0
    for a in anchors:
        if a and a in months:
            idx = max(idx, months.index(a))
    front = months[idx]
    nxt = months[idx + 1] if idx + 1 < len(months) else None
    return front, nxt


def _should_roll(front_bars: dict[_date, dict], next_bars: dict[_date, dict],
                 as_of: _date) -> bool:
    """最活絡月判準：次月「最近 2 個完成交易日」成交量皆 > 近月 → 切換報導合約。

    群益海外報價無未平倉量欄（A0 實證）——volume 是唯一可得判準。
    零成交/假日/as_of 當天（進行中）bar 不計入；有效共同日不足 2 → 不切（保守）。
    """
    common = sorted(
        d for d in front_bars
        if d in next_bars and d < as_of and d.weekday() < 5
        and (front_bars[d].get("volume") or 0) > 0
        and (next_bars[d].get("volume") or 0) > 0
    )
    if len(common) < 2:
        return False
    return all(next_bars[d]["volume"] > front_bars[d]["volume"] for d in common[-2:])


def _load_settle_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _migrate_settle_entry(st: dict) -> dict:
    """舊 schema `{code, history}` → `{active_code, chains: {code: {history}}}`（冪等）。"""
    if "chains" in st:
        return st
    out: dict = {"active_code": st.get("code"), "chains": {}}
    if st.get("code"):
        out["chains"][st["code"]] = {"history": dict(st.get("history", {}))}
    if st.get("updated"):
        out["updated"] = st["updated"]
    return out


def _prev_weekday(d: _date, no_settle: list[str] | None = None) -> _date:
    """前一個可能有官方結算價的日子：跳週末，並跳過已知沒有結算價的日子。

    🔴 `no_settle` 是**這條鏈自己觀測到**的「那天已收盤卻沒有結算價」清單
    （由 `_feed_chain` 記下），不是外部交易日曆。

    原本這裡寫著「要靠可信的交易日曆才修得了」——**那個前提是錯的**。
    交易日曆答不出真正該問的問題：2026-09-07 勞動節那天 NYMEX/COMEX/CME 股指
    走的是縮短時段、**真的有成交**（CL=F 10.3 萬口），只是不產生當日結算價。
    用「交易所有沒有休市」當判準會誤刪真實資料；而「那天有沒有官方結算價」
    **快照自己就答得出來**（`nSettle` 缺、且 `nRef` 仍等於鏈上最近一筆結算）。

    ⚠️ 只跳「已觀測到沒有結算價」的日子，不跳沒看過的日子——沒看過不等於沒有，
    盤中分支正是靠這點在鏈還沒補上昨日結算時仍能正確標記 `nRef`。
    """
    skip = set(no_settle or ())
    d -= timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in skip:
        d -= timedelta(days=1)
    return d


def _feed_chain(entry: dict, code: str, q: dict | None,
                as_of: _date) -> tuple[_date, _date, float] | None:
    """把本次快照的結算價寫進**該合約自身**的鏈（近月/次月平常一起養＝切換日無縫）。

    回傳 (day_d, settle_date, settle_val)；快照缺/壞 → None（不動鏈）。
    - 已收盤（day < as_of）：settle_date=day、值=nSettle（0 哨兵退用 nRef）。
    - 盤中（day >= as_of）：nRef=昨結 → settle_date=前一平日。
    """
    if not q or not q.get("ref"):
        return None
    day = q["day"]
    try:
        day_d = _date(day // 10000, day // 100 % 100, day % 100)
    except ValueError:
        return None
    ch = entry.setdefault("chains", {}).setdefault(code, {"history": {}})
    hist = ch["history"]
    if day_d < as_of:
        settle_date = day_d
        # nSettle=0 哨兵時先信鏈上既有值再退 nRef；nSettle 有值＝權威，覆蓋
        if q.get("settle"):
            settle_val = q["settle"]
            hist[settle_date.isoformat()] = settle_val
        elif hist.get(settle_date.isoformat()):
            settle_val = hist[settle_date.isoformat()]
        elif q.get("ref_is_prev_day"):
            # 🔴 國內線（2026-09-16 修）：nRef 是 **day_d 的前一交易日**結算，
            # 不是 day_d 當天的。原本三段退回 `settle or 鏈上 or ref` 共用同一個
            # `settle_date = day_d` 標籤，而三者語意不同 ⇒ 退到 ref 時差一天。
            #
            # 事故：09-16 06:57（台股 08:45 才開盤、nTradingDay 仍是 09-15）把
            # 09-14 的結算 45903.0 寫成 `hist["2026-09-15"]`，日漲跌算出 +0.00%，
            # 模型據此寫「結算日多空拉鋸持平」發上 Notion。官方 raw_taifex 佐證：
            # 45903.0／46032.0 正是 09-14 的 TX 202610／202611 結算價。
            #
            # ⚠️ 只由旗標驅動、**不可**推廣到海外：nRef 語意逐交易所而異——
            # SGX 收盤後把 nRef 改寫成**當日**結算（橡膠 2026-08-28），
            # NYMEX/CME 改寫成 = settle（下面 `_chain_changes` 已有棄用判斷）。
            settle_date = _prev_weekday(day_d, ch.get("no_settle"))
            settle_val = hist.get(settle_date.isoformat()) or q["ref"]
            hist.setdefault(settle_date.isoformat(), settle_val)
        else:
            # day_d 已收盤、沒有 nSettle、鏈上也沒有這一天。兩種可能：
            #   (a) 真交易日但 nSettle 是 0 哨兵 —— nRef 帶來新資訊（SGX 收盤後會把
            #       nRef 改寫成**當日**結算，橡膠 2026-08-28）⇒ 照舊掛在 day_d。
            #   (b) 那天根本沒有官方結算價（休市／縮短時段不結算）—— nRef 仍是
            #       **前一個交易日**的結算 ⇒ 掛在 day_d 就會造出一個與前一日逐位元組
            #       相同的假節點，隔天 daily = 同值相除 = +0.00%。
            # 判別器＝nRef 與鏈上最近一筆結算是否相同。2026-09-07 勞動節實測：
            # 有 09-07 節點的 56 條裡 49 條與 09-04 完全相同（美國線休市），
            # 7 條不同（Brent／橡膠／恆生科技／A50 那天有開）。正常日「與前一節點
            # 等值」的基準率只有 0~2%，而那些走的是 nSettle 權威分支、進不到這裡。
            prior = [x for x in hist if x < settle_date.isoformat()]
            latest = max(prior) if prior else None
            if latest is not None and hist[latest] and abs(hist[latest] - q["ref"]) < 1e-9:
                no_settle = ch.setdefault("no_settle", [])
                if settle_date.isoformat() not in no_settle:
                    no_settle.append(settle_date.isoformat())
                # 本日值退回鏈上最近一筆真結算 ⇒ 沿用前一個真實漲跌（與週末同行為）
                settle_date = _date.fromisoformat(latest)
                settle_val = hist[latest]
            else:
                settle_val = q["ref"]
                hist[settle_date.isoformat()] = settle_val
    else:
        settle_date = _prev_weekday(day_d, ch.get("no_settle"))
        # 🔴 盤中 nRef 可能過時（DX 實測 09:00：day 已滾新日、ref 還停在前前日結算）
        # → 鏈上既有值（已收盤分支存的正式結算）優先，且**不覆蓋**既有值
        settle_val = hist.get(settle_date.isoformat()) or q["ref"]
        hist.setdefault(settle_date.isoformat(), settle_val)
    return day_d, settle_date, settle_val


def _chain_changes(key: str, code: str, q: dict | None, as_of: _date,
                   entry: dict, series: str) -> dict:
    """結算價累積法（雙合約鏈版）：日漲跌＝今結算/昨結算。

    🔴 昨結一律「鏈 history 優先、nRef 只當 fallback」（2026-08-28 橡膠事故）：
    SGX 收盤後把快照 nRef 改寫成非昨結的值（238.8；昨結實為 236.3），舊版已收盤
    分支 settle/ref 直接相除算出 +0.08%（真值 +1.14%）。nRef 與鏈值不一致時印
    warning——下次哪家交易所又改寫 nRef 要看得見。
    """
    def _null(reason: str) -> dict:
        return {"daily_pct": None, "weekly_pct": None, "series": series,
                "resolve": f"結算價累積法：{reason} → 留空"}

    fed = _feed_chain(entry, code, q, as_of)
    if fed is None:
        day = (q or {}).get("day")
        return _null("快照未取得" if not q or not q.get("ref")
                     else f"nTradingDay 異常（{day}）")
    day_d, settle_date, settle_val = fed
    history: dict[str, float] = entry["chains"][code]["history"]

    # 昨結：鏈上 < settle_date 最近一筆、gap ≤ 4 日曆天（週末/連假容忍，沿用原規則）
    prev_v: float | None = None
    prev_src = "無"
    prev_dates = sorted(d for d in (_date.fromisoformat(x) for x in history)
                        if d < settle_date)
    if prev_dates:
        prev_d = prev_dates[-1]
        v = history[prev_d.isoformat()]
        if 1 <= (settle_date - prev_d).days <= 4 and v:
            prev_v, prev_src = v, f"鏈{prev_d}"
    if day_d < as_of and q.get("ref"):
        # 已收盤快照自帶 ref（名義上=昨結）：只在鏈缺該日時 fallback
        if prev_v is None:
            if q.get("settle") and abs(q["ref"] - q["settle"]) < 1e-9:
                # 🔴 ref==settle＝「收盤後 nRef 被改寫成當日結算」簽名（NYM/CME 09:00
                # 實測 HO/HG/PA/ALI/CL 全中招）→ 昨結不可得，寧可鏈未接上退最後成交鏈，
                # 也不出 settle/ref=+0.00% 假值
                prev_src = "nRef 已被改寫（=settle），棄用"
            elif q.get("ref_is_prev_day"):
                # 🔴 國內線：nRef 已經被 `_feed_chain` 當成 **settle_date 當天**的值
                # 用掉了（它就是 day_d 前一交易日的結算）⇒ 不可以同一個數字再當
                # 「settle_date 的前一天」。那正是 09-16 台指期 +0.00% 的成因：
                # 分子分母都是 09-14 的結算。拿不到更早的結算就留空。
                prev_src = "nRef 已用作本日值，不可再當昨結"
            else:
                prev_v, prev_src = q["ref"], "nRef(fallback)"
        elif abs(q["ref"] - prev_v) > 1e-9:
            print(f"   ⚠️ {key}: 快照 nRef({q['ref']}) ≠ 鏈上昨結({prev_v})——"
                  "交易所收盤後改寫 nRef？沿用鏈值（SGX 橡膠 2026-08-28 模式）")

    daily = (settle_val / prev_v - 1) * 100 if prev_v else None
    mode = (f"已收盤：settle({q.get('settle')})/昨結[{prev_src}]" if day_d < as_of
            else f"盤中：昨結=nRef({settle_val})、前結[{prev_src}]")

    # 週漲跌：最近的「≤ settle_date-7」歷史結算
    weekly = None
    week_ago = settle_date - timedelta(days=7)
    for d in sorted((_date.fromisoformat(x) for x in history), reverse=True):
        if d <= week_ago:
            base = history[d.isoformat()]
            weekly = (settle_val / base - 1) * 100 if base else None
            break

    if daily is None:
        return {**_null(f"鏈尚未接上（{mode}；已存 {settle_date} 結算 {settle_val}，"
                        "明日起有值）"), "last_date": settle_date.isoformat()}
    return {
        "series": series, "resolve": f"結算價累積法（{mode}）",
        "daily_pct": round(daily, 4),
        "weekly_pct": round(weekly, 4) if weekly is not None else None,
        "last_date": settle_date.isoformat(), "last_close": settle_val,
        "prev_date": "結算鏈", "prev_close": None,
    }


def _prune_entry(entry: dict, keep_codes: set[str], as_of: _date) -> None:
    """修剪：已到期/不再追蹤的合約鏈整條刪；各鏈 30 天外舊值刪。"""
    entry["chains"] = {c: ch for c, ch in entry.get("chains", {}).items()
                       if c in keep_codes}
    for ch in entry["chains"].values():
        ch["history"] = {d: v for d, v in ch["history"].items()
                         if (as_of - _date.fromisoformat(d)).days <= 30}
        # 「那天沒有結算價」的紀錄與 history 同窗修剪，否則會無限長大
        if ch.get("no_settle"):
            ch["no_settle"] = [d for d in ch["no_settle"]
                               if (as_of - _date.fromisoformat(d)).days <= 30]


def _parse_kline_bars(rows: list[str]) -> dict[_date, dict]:
    """日K 列 → {date: {close, volume}}。格式 `YYYY/MM/DD, O, H, L, C[, VOLUME]`
    （parts[5]＝成交量，A0 實證；缺欄＝None，滾月判準視同不可比）。"""
    bars: dict[_date, dict] = {}
    for row in rows:
        parts = [p.strip() for p in row.split(",")]
        if len(parts) < 5:
            continue
        m = re.fullmatch(r"(\d{4})/(\d{2})/(\d{2})", parts[0])
        if not m:
            continue  # 分線格式（帶時間）不會出現在 type=1，防禦性略過
        try:
            close = float(parts[4])
        except ValueError:
            continue
        volume: float | None = None
        if len(parts) >= 6:
            try:
                volume = float(parts[5])
            except ValueError:
                volume = None
        bars[_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = {
            "close": close, "volume": volume}
    return bars


def _parse_kline_rows(rows: list[str]) -> dict[_date, float]:
    return {d: b["close"] for d, b in _parse_kline_bars(rows).items()}


# ─────────────── 期交所官方結算價（2026-09-21 新增）───────────────
#
# 🔴 為什麼非要它不可：國內快照唯一拿得到的結算價來源是 `nRef`，而 `nRef` 永遠是
# 「`nTradingDay` 的**前一個**交易日」的結算；而 `nTradingDay` 要到**隔天 08:45
# 開盤**才跳。2026-09-21 實測四個時點：
#     06:32 → nTradingDay=20260918、nRef=46459（09-17 結算）
#     11:41 → nTradingDay=20260921、nRef=47428（09-18 結算）
#     15:02 / 15:12 / 15:35（夜盤已開 35 分鐘）→ **仍是 20260921、仍是 47428**
# ⇒ 06:32 的排程**結構上**拿不到最後一個交易日的結算，結算鏈永遠落後一個交易日。
# ⇒ 原本規劃的「傍晚多跑一次餵鏈」**實測不成立**，別再試那條。
#
# 實際後果：日報 2026-09-17 ~ 09-21 連續 5 天發出的台指期漲跌幅都是**前一個交易日**
# 的（09-21 發 +0.87%，官方結算價算出的真值 +2.09%），5 天全部發上了 Notion。
#
# 官方每日行情（`futDataDown`）實測**當天 15:09 就有當日結算價**
# （2026-09-21 TX 202610 結算 48053）⇒ 隔天 06:32 一定來得及。
# ⚠️ **不要改用 `openapi.taifex.com.tw/v1/DailyMarketReportFut`**：同一天的
# 15:07／15:19／15:34 三次，它回的最新日期都還停在 09-18，比官網下載介面慢。
# ⚠️ 走 stdlib `urllib` 而不引入 `requests`：capital-api 是純 library 專案，
# 為了一天一次的 POST 加一個依賴不划算（它的 .venv 目前也沒有 requests）。
TAIFEX_FUT_DAILY_DOWNLOAD = "https://www.taifex.com.tw/cht/3/futDataDown"
_TAIFEX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_TAIFEX_TIMEOUT_S = 45
#: 回看天數。7 個日曆天是週漲跌的基準需要的，再加連假緩衝。
#: ⚠️ 與 `_prune_entry` 的 30 天保留窗相容（12 < 30）。
_TAIFEX_LOOKBACK_D = 12

#: 官方 CSV 必備欄位。表頭對不上就整批放棄——期交所的表頭會隨查詢視窗變
#: （選擇權日行情已有前例），硬用欄位位置會靜默讀到別的欄。
_TAIFEX_COLS = ("交易日期", "契約", "到期月份(週別)", "結算價", "交易時段")


def _taifex_official_settles(root: str, as_of: _date, *,
                             lookback_days: int = _TAIFEX_LOOKBACK_D,
                             timeout_s: int = _TAIFEX_TIMEOUT_S,
                             fetch=None) -> dict:
    """期交所官方每日行情 → `{契約月: {日期: 結算價}}`。取不到一律回 `{}`，**不拋**。

    失敗不可以炸掉整條國內線：拿不到官方值就退回原本的快照鏈，而下游
    （scraper `load_price_file` 的陳舊閘門）會把落後的值**留空**
    ——留空遠比「發一個看起來完全正常的舊數字」好。

    四條過濾各自對應一個會靜默出錯的形狀：
    - 只收 `交易時段 == 一般`：`盤後` 那列的結算價欄是 `-`。
    - 只收六位數的到期月份：價差交易的月份欄長成 `202610/202611`。
    - 丟掉結算價 0：最後交易日當天交易所不發結算價，本欄是 0 哨兵（網頁顯示 `-`），
      拿它去相除會算出 -100%（本專案 2026-08/09 已為同型哨兵出過兩次事）。
    - 只收 `交易日 < as_of`：報告日 D 講的是 D **之前**最後一個交易日的收盤。
    """
    start = as_of - timedelta(days=lookback_days)
    body_params = {
        "down_type": "1",
        "queryStartDate": f"{start:%Y/%m/%d}",
        "queryEndDate": f"{as_of:%Y/%m/%d}",
        "commodity_id": root,
    }
    if fetch is None:
        def fetch(params: dict) -> bytes:
            req = urllib.request.Request(
                TAIFEX_FUT_DAILY_DOWNLOAD,
                data=urllib.parse.urlencode(params).encode("ascii"),
                headers={"User-Agent": _TAIFEX_UA,
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.read()

    try:
        body = fetch(body_params)
    except Exception as exc:  # noqa: BLE001
        print(f"   ⚠️ 期交所官方行情取得失敗（{type(exc).__name__}: {exc}）——退回快照鏈")
        return {}
    try:
        text = body.decode("big5")
    except UnicodeDecodeError as exc:
        # 🔴 不可以用 errors="replace" 硬吞：那會讓壞掉的回應長得像正常資料。
        print(f"   ⚠️ 期交所回應不是 Big5（{exc}）——退回快照鏈")
        return {}

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        print("   ⚠️ 期交所回應是空的——退回快照鏈")
        return {}
    header = [c.strip() for c in rows[0]]
    try:
        idx = {name: header.index(name) for name in _TAIFEX_COLS}
    except ValueError:
        print(f"   ⚠️ 期交所表頭與預期不符（{header[:6]}）——退回快照鏈")
        return {}

    out: dict = {}
    span = max(idx.values())
    for r in rows[1:]:
        if len(r) <= span:
            continue
        if r[idx["契約"]].strip() != root:
            continue
        if r[idx["交易時段"]].strip() != "一般":
            continue
        month = r[idx["到期月份(週別)"]].strip()
        if not re.fullmatch(r"\d{6}", month):
            continue
        try:
            settle = float(r[idx["結算價"]].strip().replace(",", ""))
        except ValueError:
            continue
        if settle == 0:
            continue
        try:
            day = _date.fromisoformat(r[idx["交易日期"]].strip().replace("/", "-"))
        except ValueError:
            continue
        if day >= as_of:
            continue
        out.setdefault(month, {})[day.isoformat()] = settle
    return out


def _domestic_contract_month(catalog: list, code: str):
    """由商品清單的最後交易日推出契約月 `YYYYMM`。查不到回 None。

    TX 的最後交易日就落在契約月之內（TX10AM → ltd 20261021 → 202610）。
    刻意**不**由代碼的兩位月份自己推年份——跨年時 `TX01AM` 的年份要靠 as_of 猜，
    而清單裡本來就帶著確定答案。
    """
    for rec in catalog:
        if rec.get("code") == code:
            ltd = str(rec.get("ltd", ""))
            return ltd[:6] if re.fullmatch(r"\d{8}", ltd) else None
    return None


def _seed_chain_from_official(entry: dict, code: str, settles: dict):
    """把官方結算價寫進該合約自身的鏈。回傳 `(寫入筆數, 與原值不同的說明清單)`。

    官方值**優先**：那是交易所自己發布的結算價，比從快照 `nRef` 推出來的權威。
    但「改掉既有值」一定要看得見 —— 差異清單交給呼叫端印出來，否則哪天官方與快照
    系統性不一致，這裡會**無聲地改寫歷史**，而畫面上完全正常。
    """
    ch = entry.setdefault("chains", {}).setdefault(code, {"history": {}})
    hist = ch["history"]
    changed = []
    written = 0
    for day, value in sorted(settles.items()):
        old = hist.get(day)
        if old is not None and abs(old - value) <= 1e-9:
            continue
        if old is not None:
            changed.append(f"{day}: {old} -> {value}")
        hist[day] = value
        written += 1
    return written, changed


def _parse_domestic_catalog(fragments: list[str]) -> list[dict]:
    """國內商品清單原文 → [{code, name, ltd, order_code}, ...]

    原文格式（實測 RequestStockList(2) 的回傳）：
        TX09AM,台指09,20260916,TXFI6,100000| 1 | ,NTD;TX10AM,台指10,20261021,TXFJ6,…
    以 `;` 分筆、`,` 分欄。乘數那一欄自己帶 `|`，但不影響前四欄的位置。
    """
    out: list[dict] = []
    for blob in fragments:
        for item in blob.split(";"):
            parts = [p.strip() for p in item.split(",")]
            if len(parts) < 4 or not parts[0]:
                continue
            out.append({"code": parts[0], "name": parts[1],
                        "ltd": parts[2], "order_code": parts[3]})
    return out


def _domestic_months(catalog: list[dict], root: str, as_of: _date) -> list[str]:
    """該 root 的逐月查詢代碼，依到期日升冪；只留 LTD ≥ as_of+3 天。

    `as_of+3` 這個緩衝是鏡像海外線的 `_month_codes`——臨到期月強制滾月，
    免得結算日當天還在追一個當晚就消失的合約。
    """
    pat = re.compile(_DOMESTIC_CODE_RE.format(root=re.escape(root)))
    rows: list[tuple[str, str]] = []
    for rec in catalog:
        code = rec["code"]
        m = pat.match(code)
        if not m or m.group(1) == "00":        # TX00AM ＝近月連續，不是具體月份
            continue
        ltd = rec.get("ltd", "")
        if not re.fullmatch(r"\d{8}", ltd):
            continue
        try:
            ltd_d = _date(int(ltd[:4]), int(ltd[4:6]), int(ltd[6:]))
        except ValueError:
            continue
        if ltd_d < as_of + timedelta(days=3):
            continue
        rows.append((ltd, code))
    return [c for _ltd, c in sorted(rows)]


def _domestic_snapshot(q_lib, sk, code: str) -> dict | None:
    """國內快照 → `_feed_chain` 吃的形狀 `{day, ref, settle}`。取不到回 None。

    🔴 `settle` 一律 None：國內的 SKSTOCKLONG **沒有** nSettlePrice 欄
    （那是海外 SKOSSTOCKLONG 才有的）。`_feed_chain` 在 settle 缺值時會退回
    「鏈上既有值 → nRef」，對國內正是想要的語意（nRef ＝ 交易所給的參考價＝昨結）。

    🔴 **不碰 nClose**。實測盤中 nClose=0（還沒收盤），那與 2026-08-30／09-13 把
    日經、恆生算成 -100% 的哨兵是同一個東西。這條路徑只用 nRef，結構上踩不到。
    """
    try:
        stock = sk.SKSTOCKLONG()
        res = q_lib.SKQuoteLib_GetStockByNoLONG(code, stock)
        # 🔴 comtypes 把 out 參數回成 **list**（不是 tuple）：`[SKSTOCKLONG, rc]`。
        # 第一版只判 tuple，於是 rc 被賦成整個 list、`rc != 0` 永遠成立 ⇒ 每次都留空。
        # （單獨寫探針時讀的是傳進去那個 struct——comtypes 原地填值——剛好繞過這個
        #   判斷，所以探針「成功」而整合後失敗。）
        if isinstance(res, (tuple, list)):
            stock, rc = res[0], res[-1]
        else:
            rc = res
    except Exception as exc:  # noqa: BLE001
        print(f"   ⚠️ 國內快照 {code} 呼叫失敗：{type(exc).__name__}: {exc}")
        return None
    if rc != 0:
        print(f"   ⚠️ 國內快照 {code} rc={rc}")
        return None
    dec = int(getattr(stock, "sDecimal", 0) or 0)
    scale = 10 ** dec if dec else 1
    ref = (getattr(stock, "nRef", 0) or 0) / scale
    day = int(getattr(stock, "nTradingDay", 0) or 0)
    if ref <= 0 or day <= 0:
        print(f"   ⚠️ 國內快照 {code} 值不可用（nRef={ref}、nTradingDay={day}）")
        return None
    return {"day": day, "ref": ref, "settle": None,
            # 🔴 nRef ＝ **nTradingDay 前一交易日**的結算，不是 nTradingDay 當天的。
            # `_feed_chain` 的已收盤分支預設 nRef 就是 day_d 當天（那對 SGX／NYMEX
            # 那種「收盤後改寫 nRef」的交易所成立），對 TAIFEX 不成立 ⇒ 必須明講，
            # 否則差一天（2026-09-16 台指期 +0.00% 假平盤事故）。
            "ref_is_prev_day": True,
            "name": str(getattr(stock, "bstrStockName", "") or "")}


def _run_domestic(as_of: _date, settle_state: dict, prices: dict,
                  problems: list[str], pump) -> None:
    """國內期貨（台指期）整段。**任何失敗只讓這幾檔留空，不影響海外那 41 檔。**

    刻意獨立開一條連線、獨立 try/except：這支腳本每天 06:32 餵整份日報，
    為了新增一檔商品而讓既有的全部一起掛掉是不能接受的。
    """
    from capitalapi.skcom import create_quote_lib, get_sk_module  # noqa: PLC0415

    def _blank(reason: str) -> None:
        for key, (exch, root) in DOMESTIC_CHAIN.items():
            problems.append(f"{key}（國內線：{reason}）")
            prices[key] = {"daily_pct": None, "weekly_pct": None,
                           "series": f"{exch},{root}",
                           "resolve": f"國內報價線：{reason} → 留空"}

    connected = {"ok": False}
    q_lib = None
    try:
        q_lib = create_quote_lib()
        sk = get_sk_module()

        class _DomEv:
            def OnConnection(self, nKind, nCode):          # noqa: N802
                if int(nKind) == 3003:                      # SK_SUBJECT_CONNECTION_STOCKS_READY
                    connected["ok"] = True

            def OnNotifyStockList(self, sMarketNo, bstrStockData):   # noqa: N802
                _dom_lists.append(str(bstrStockData))

            def OnNotifyQuoteLONG(self, sMarketNo, nIndex):          # noqa: N802
                pass

        _dom_lists: list[str] = []
        handler = comtypes.client.GetEvents(q_lib, _DomEv())         # noqa: F841

        # 🔴 一定要用 EnterMonitor**LONG**。非 LONG 版送得出去（rc=0）但連線永遠不會
        # 完成，之後每個查詢都回 1095 SK_ERROR_QUOTE_CONNECT_FIRST——2026-09-15 曾
        # 據此誤判成「這個帳號沒有國內報價權限」，白繞一大圈。
        rc = q_lib.SKQuoteLib_EnterMonitorLONG()
        print(f"🏠 國內報價線 EnterMonitorLONG rc={rc}")
        t0 = time.time()
        while time.time() - t0 < 60 and not connected["ok"]:
            pump(1.0)
        if not connected["ok"]:
            _blank("60 秒內沒連上")
            return

        q_lib.SKQuoteLib_RequestStockList(2)                 # 2 ＝期貨
        t0 = time.time()
        while time.time() - t0 < 15 and not _dom_lists:
            pump(0.5)
        catalog = _parse_domestic_catalog(_dom_lists)
        print(f"   商品清單 {len(_dom_lists)} 段、解析出 {len(catalog)} 筆")
        if not catalog:
            _blank("商品清單沒收到")
            return

        for key, (exch, root) in DOMESTIC_CHAIN.items():
            months = _domestic_months(catalog, root, as_of)
            if not months:
                problems.append(f"{key}（{root} 無可用月份）")
                prices[key] = {"daily_pct": None, "weekly_pct": None,
                               "series": f"{exch},{root}",
                               "resolve": f"{root} 無可用月份（LTD ≥ as_of+3）→ 留空"}
                continue
            front = months[0]
            nxt = months[1] if len(months) > 1 else None
            entry = _migrate_settle_entry(settle_state.setdefault(key, {}))

            # 🔴 先用**期交所官方結算價**把鏈墊好，再餵快照。順序不可反：
            # `_feed_chain` 的已收盤分支是「鏈上有這一天就用鏈上的」，官方值先進去
            # 之後，那條分支自然會拿到正確的當日結算，不必改 `_feed_chain` 一行。
            official = _taifex_official_settles(root, as_of)
            for code in (front, nxt):
                if not code:
                    continue
                month = _domestic_contract_month(catalog, code)
                if not month or month not in official:
                    print(f"   ⚠️ {code}：官方行情沒有契約月 {month or '（推不出來）'}"
                          f"，本合約退回快照鏈")
                    continue
                n, changed = _seed_chain_from_official(entry, code, official[month])
                print(f"   📥 {code} 官方結算價寫入 {n} 筆"
                      f"（契約月 {month}，共 {len(official[month])} 天）")
                for line in changed:
                    print(f"      🔴 官方值與鏈上既有值不同 {line}")

            # 近月＋次月都餵鏈（與海外線同策略：兩條鏈平常一起養，換月當天無縫）
            for code in (front, nxt):
                if code:
                    snap = _domestic_snapshot(q_lib, sk, code)
                    if snap:
                        _feed_chain(entry, code, snap, as_of)

            snap = _domestic_snapshot(q_lib, sk, front)
            series = f"{exch},{front}"
            se = _chain_changes(key, front, snap, as_of, entry, series)
            entry["active_code"] = front
            _prune_entry(entry, {c for c in (front, nxt) if c}, as_of)
            entry["updated"] = datetime.now().isoformat(timespec="seconds")

            name = (snap or {}).get("name", "")
            note = f"{root} 近月 {front}（{name}）候選 {front}/{nxt or '—'}"
            if se["daily_pct"] is None:
                problems.append(f"{key}（{series}：{se['resolve'][:80]}）")
                prices[key] = {"daily_pct": None, "weekly_pct": None, "series": series,
                               "resolve": f"{note}；{se['resolve']}"}
                continue
            prices[key] = {**se, "resolve": f"{note}；{se['resolve']}"}
    except Exception as exc:  # noqa: BLE001
        print(f"   ⚠️ 國內線整段失敗：{type(exc).__name__}: {exc}")
        _blank(f"{type(exc).__name__}: {exc}")
    finally:
        if q_lib is not None:
            try:
                q_lib.SKQuoteLib_LeaveMonitor()
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="BFW 日報價格檔 dump（群益 SKOSQuoteLib）")
    parser.add_argument("--date", default=None, help="as_of 報告日期 YYYY-MM-DD（預設今天台北）")
    parser.add_argument("--out", default=None,
                        help="輸出 JSON 路徑（預設 d:/tmp/bfw_capital_prices_{as_of}.json）")
    parser.add_argument("--days", type=int, default=15, help="日K 回看天數（週漲跌需要 >=10）")
    args = parser.parse_args()

    as_of = _date.fromisoformat(args.date) if args.date else datetime.now().date()
    out_path = Path(args.out or f"d:/tmp/bfw_capital_prices_{as_of:%Y%m%d}.json")

    user_id = os.getenv("CAPITAL_USER_ID", "")
    password = os.getenv("CAPITAL_PASSWORD", "")
    if not user_id or not password:
        print("❌ 請在 .env 設定 CAPITAL_USER_ID / CAPITAL_PASSWORD")
        return 1

    pump = _make_pump()
    state = _State()
    client = CapitalClient()
    os_lib = None
    handler = None
    try:
        print(f"📡 登入群益… as_of={as_of}")
        client.login(user_id, password)
        os_lib = create_os_quote_lib()
        sk = get_sk_module()
        handler = comtypes.client.GetEvents(os_lib, _build_event(state, os_lib, sk))

        rc = os_lib.SKOSQuoteLib_EnterMonitorLONG()
        print(f"EnterMonitorLONG rc={rc}")
        deadline = time.time() + 20
        while time.time() < deadline:
            pump(0.5)
            try:
                if int(os_lib.SKOSQuoteLib_IsConnected()) == 1:
                    break
            except Exception:  # noqa: BLE001
                pass
        pump(3.0)

        print("📋 抓商品檔（含下單代碼）…")
        rc = os_lib.SKOSQuoteLib_GetOverseaProductDetail(1)
        start = time.time()
        while not state.detail_done and time.time() - start < 120:
            pump(1.0)
            if state.detail and state.last_frag_ts and time.time() - state.last_frag_ts > 5:
                break
        catalog = _parse_detail(state.detail)
        print(f"   商品檔 {len(catalog)} 檔（done={state.detail_done}）")
        if len(catalog) < 500:
            print("❌ 商品檔不完整，中止（不產出殘缺價格檔）")
            return 1

        # 解每個 key 要抓的（exch, 具體代碼）。
        # 🔴 解析失敗＝進 resolve_failed → 輸出「明確 null」（報告留空）。
        # user 拍板（2026-08-26）：日報價格**只用群益**——群益拿不到就留空，
        # 絕不讓 scraper 因缺 key 而 fallback 回 yfinance 期貨路徑。
        # 🔴 最活絡月自動換月（2026-08-28 規劃）：HOT 換月落後市場慣例（橘子汁：市場
        # 08-24 已移倉 Nov、HOT 08-28 仍指 Sep）→ 候選=LTD 排序近月+次月、錨取
        # state active / HOT 映射較晚者（單向不回滾）、切換由成交量判準（_should_roll）。
        settle_state = _load_settle_state()
        for k in list(settle_state):
            settle_state[k] = _migrate_settle_entry(settle_state[k])

        plan: dict[str, tuple[str, str, str]] = {}          # key -> (exch, 近月code, 說明)
        candidates: dict[str, tuple[str, str | None]] = {}  # key -> (近月, 次月)
        resolve_failed: dict[str, str] = {}                 # key -> 原因

        def _resolve_months(key: str, exch: str, quote_root: str, hot: str | None) -> None:
            months = _month_codes(catalog, quote_root, as_of)
            if not months:
                resolve_failed[key] = f"{quote_root} 無可用月份（LTD ≥ as_of+3）"
                print(f"   ⚠️ {key}: {resolve_failed[key]}")
                return
            hot_mapped = _hot_mapped_code(catalog, hot) if hot else None
            if hot and not hot_mapped:
                print(f"   ⚠️ {key}: HOT {hot} 映射失敗"
                      f"（order_code={catalog.get(hot, {}).get('order_code')}）→ 改用 LTD 近月")
            prev_active = settle_state.get(key, {}).get("active_code")
            front, nxt = _pick_candidates(months, [prev_active, hot_mapped])
            hot_tag = f"HOT {hot}→{hot_mapped or '?'} " if hot else ""
            plan[key] = (exch, front, f"{hot_tag}候選 {front}/{nxt or '—'}")
            candidates[key] = (front, nxt)

        for key, (exch, hot) in FUTURES_HOT.items():
            _resolve_months(key, exch, hot[:-4], hot)
        for key, (exch, root) in SETTLE_CHAIN.items():
            _resolve_months(key, exch, root, None)
        for key, (exch, code) in SPOT.items():
            if code in catalog:
                plan[key] = (exch, code, "spot")
            else:
                resolve_failed[key] = f"{exch},{code} 不在商品檔"
                print(f"   ⚠️ {key}: {resolve_failed[key]}")
        spot_index_plan: dict[str, tuple[str, str]] = {}
        for key, (exch, code) in SPOT_INDEX.items():
            if code in catalog:
                spot_index_plan[key] = (exch, code)
            else:
                resolve_failed[key] = f"{exch},{code} 不在商品檔"
                print(f"   ⚠️ {key}: {resolve_failed[key]}")

        # 快照訂閱（結算價鏈 + SPOT_INDEX 混合法都要）：
        # 🔴 user 拍板（2026-08-26 第五輪）：**全期貨改結算價鏈**——每檔期貨的快照 nRef
        # ＝正式結算價，逐日存狀態檔；鏈未接上（冷啟動/換約日）退回同合約最後成交鏈
        # 並在 resolve 註明。FX 現貨無結算概念（nRef=NY 17:00 昨收＝KLine 同口徑）維持
        # KLine；SPOT_INDEX 維持混合法（現貨收盤口徑）。
        # 近月＋次月**都訂**（兩條鏈平常一起養，切換日無縫——任務 3）。
        settle_keys = {k for k in plan if k in FUTURES_HOT or k in SETTLE_CHAIN}
        snap_codes: set[str] = set()
        code2exch: dict[str, str] = {}
        for k in settle_keys:
            for c in candidates[k]:
                if c:
                    snap_codes.add(c)
                    code2exch[c] = plan[k][0]
        for _e, c in spot_index_plan.values():
            snap_codes.add(c)
            code2exch[c] = _e
        if snap_codes:
            codes_sorted = sorted(snap_codes)
            # 🔴 SKOS 快照頁數有限：第 2 次 RequestStocks(-1) 回 3006
            # SK_SUBJECT_QUOTE_PAGE_EXCEED（2026-08-28 實測，67 檔雙合約後超過單頁）。
            # → 同一頁「覆蓋式輪換」：每批訂完等快照全到（存進 state.quotes 後不受
            #   換頁影響），再用**同一頁**訂下一批（RequestStocks 同頁＝整頁替換）。
            page_no = -1   # 首批自動配號，之後重用該頁
            for i in range(0, len(codes_sorted), 40):
                batch = codes_sorted[i:i + 40]
                nos = "#".join(f"{code2exch[c]},{c}" for c in batch)
                page, rc = os_lib.SKOSQuoteLib_RequestStocks(page_no, nos)
                print(f"📸 快照訂閱 batch{i // 40 + 1} {len(batch)} 檔 rc={rc} page={page}")
                if rc == 0 and int(page) >= 0:
                    page_no = int(page)
                want = set(batch)
                t0 = time.time()
                while time.time() - t0 < 15 and not want <= set(state.quotes):
                    pump(0.5)
            missing = snap_codes - set(state.quotes)
            print(f"   快照到位 {len(snap_codes) - len(missing)}/{len(snap_codes)}"
                  + (f"，未到：{sorted(missing)}" if missing else ""))

        start_d = (as_of - timedelta(days=args.days)).strftime("%Y%m%d")
        end_d = as_of.strftime("%Y%m%d")
        kline_items: list[tuple[str, str, str, str]] = []   # (顯示名, exch, code, note)
        seen_kline: set[str] = set()
        for key, (exch, front, note) in plan.items():
            if key in settle_keys:
                front_c, nxt_c = candidates[key]
                for c, tag in ((front_c, "近月"), (nxt_c, "次月")):
                    if c and c not in seen_kline:
                        seen_kline.add(c)
                        kline_items.append((f"{key}:{tag}", exch, c, note))
            else:
                kline_items.append((key, exch, front, note))
        for key, (exch, code) in spot_index_plan.items():
            kline_items.append((key, exch, code, "spot_index(週基準/前日收)"))
        print(f"📈 逐檔抓日K（{len(kline_items)} 檔）…")
        for label, exch, code, note in kline_items:
            rc = os_lib.SKOSQuoteLib_RequestKLineByDate(f"{exch},{code}", 1, start_d, end_d, 1)
            t0 = time.time()
            # 等這一檔的資料到齊（idle 2s）再抓下一檔，避免事件交錯時難定位缺漏
            while time.time() - t0 < 20:
                pump(0.5)
                if code in state.kline and state.kline_last_ts and time.time() - state.kline_last_ts > 2:
                    break
            n = len(state.kline.get(code, []))
            print(f"   {label:<18} {exch},{code:<9} rc={rc} rows={n}  ({note})")

        prices: dict[str, dict] = {}
        problems: list[str] = []
        roll_events: list[str] = []
        for key, (exch, front, note) in plan.items():
            if key in settle_keys:
                front_c, nxt_c = candidates[key]
                front_bars = _parse_kline_bars(state.kline.get(front_c, []))
                next_bars = _parse_kline_bars(state.kline.get(nxt_c, [])) if nxt_c else {}
                rolled = bool(nxt_c) and _should_roll(front_bars, next_bars, as_of)
                active = nxt_c if rolled else front_c
                entry = settle_state.setdefault(key, {"active_code": None, "chains": {}})
                prev_active = entry.get("active_code")
                roll_note = ""
                if prev_active and active != prev_active:
                    kind = "量判" if rolled else "LTD/錨"
                    roll_note = f"；滾月({kind}) {prev_active}→{active}"
                    roll_events.append(f"{key}: {prev_active}→{active}（{kind}）")
                    print(f"   🔁 {key}: 滾月({kind}) {prev_active}→{active}")
                # 非 active 的候選也餵鏈（兩條鏈平常一起養，切換日昨結已在鏈上＝無縫）
                for c in {front_c, nxt_c} - {None, active}:
                    _feed_chain(entry, c, state.quotes.get(c), as_of)
                series = f"{exch},{active}"
                se = _chain_changes(key, active, state.quotes.get(active), as_of,
                                    entry, series)
                entry["active_code"] = active
                _prune_entry(entry, {c for c in (front_c, nxt_c) if c}, as_of)
                entry["updated"] = datetime.now().isoformat(timespec="seconds")

                active_bars = next_bars if rolled else front_bars
                closes = {d: b["close"] for d, b in active_bars.items()}
                cc = _changes_from_closes(closes, as_of)   # 同合約最後成交鏈（fallback/週過渡）
                if se["daily_pct"] is not None:
                    # 結算鏈為主；週漲跌：結算歷史滿 7 天前用最後成交鏈過渡
                    weekly = se["weekly_pct"]
                    wk_src = "結算鏈"
                    if weekly is None and cc is not None:
                        weekly = cc["weekly_pct"]
                        wk_src = "最後成交鏈(過渡)"
                    prices[key] = {
                        "series": series,
                        "resolve": f"{note}{roll_note}；日=結算鏈、週={wk_src}",
                        "daily_pct": se["daily_pct"], "weekly_pct": weekly,
                        "last_date": se["last_date"], "last_close": se["last_close"],
                        "prev_date": "結算鏈", "prev_close": None,
                    }
                    continue
                # 鏈未接上（冷啟動/換約日）→ 同合約最後成交鏈 fallback（resolve 註明）。
                # SETTLE_CHAIN（極薄合約）例外：最後成交序列是雜訊，不退、直接留空。
                if key not in SETTLE_CHAIN and cc is not None:
                    prices[key] = {
                        "series": series,
                        "resolve": f"{note}{roll_note}；結算鏈未接上（{se['resolve'][:60]}）"
                                   "→ 本日用同合約最後成交鏈",
                        **cc,
                    }
                    continue
                problems.append(f"{key}（{series}：{se['resolve'][:80]}）")
                prices[key] = {"daily_pct": None, "weekly_pct": None, "series": series,
                               "resolve": f"{note}{roll_note}；{se['resolve']}"}
                continue

            # FX 現貨：維持 KLine 最後成交鏈（nRef=NY 17:00 昨收，同口徑）
            series = f"{exch},{front}"
            closes = _parse_kline_rows(state.kline.get(front, []))
            cc = _changes_from_closes(closes, as_of)
            if cc is None:
                problems.append(f"{key}（{series}：bar 不足或過期）")
                prices[key] = {
                    "daily_pct": None, "weekly_pct": None, "series": series,
                    "resolve": f"{note}；bar 不足或過期 → 留空",
                }
                continue
            prices[key] = {"series": series, "resolve": note, **cc}
        for key, (exch, code) in spot_index_plan.items():
            closes = _parse_kline_rows(state.kline.get(code, []))
            entry = _hybrid_index_changes(state.quotes.get(code), closes, as_of, f"{exch},{code}")
            if entry["daily_pct"] is None:
                problems.append(f"{key}（{entry['resolve']}）")
            prices[key] = entry
        # 國內期貨（台指期）——獨立一條連線、獨立 try/except，掛掉只影響它自己。
        # 放在寫狀態檔**之前**，讓國內鏈與海外鏈存進同一份 bfw_settle_state.json。
        if DOMESTIC_CHAIN:
            _run_domestic(as_of, settle_state, prices, problems, pump)

        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(settle_state, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        for key, reason in resolve_failed.items():
            prices[key] = {
                "daily_pct": None, "weekly_pct": None, "series": None,
                "resolve": f"{reason} → 留空",
            }

        payload = {
            "version": 1,
            "as_of": as_of.isoformat(),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": "capital-api SKOSQuoteLib dump_bfw_price_changes（結算價鏈＋"
                      "最活絡月量判滾月；合約自身序列，絕不用 HOT 拼接）",
            "uncovered_fallback": list(UNCOVERED),
            "prices": prices,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"\n===== 結果：{len(prices)} 檔成功、{len(problems)} 檔失敗 =====")
        for key, e in prices.items():
            d = f"{e['daily_pct']:+.2f}%" if e["daily_pct"] is not None else "—"
            w = f"{e['weekly_pct']:+.2f}%" if e["weekly_pct"] is not None else "—"
            if e.get("last_date") and e.get("daily_pct") is not None:
                print(f"  {key:<14} 日 {d:>8} 週 {w:>8}  {str(e.get('series')):<15} "
                      f"{e.get('prev_date')}→{e['last_date']} {e.get('prev_close')}→{e.get('last_close')}")
            else:
                print(f"  {key:<14} 日 {d:>8} 週 {w:>8}  （留空：{e['resolve']}）")
        if roll_events:
            print(f"  🔁 滾月：{roll_events}")
        if problems:
            print(f"  ⚠️ 失敗：{problems}")
        print(f"  （fallback 給 scraper 既有路徑：{UNCOVERED}）")
        print(f"\n📝 已寫出：{out_path}")
        return 0 if prices and len(problems) == 0 else (0 if prices else 1)

    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"❌ 錯誤：{exc}")
        traceback.print_exc()
        return 1
    finally:
        try:
            if os_lib is not None:
                os_lib.SKOSQuoteLib_LeaveMonitor()
        except Exception:  # noqa: BLE001
            pass
        handler = None  # noqa: F841
        if client.is_logged_in:
            client.logout()
        print("📴 已結束。")


if __name__ == "__main__":
    raise SystemExit(main())
