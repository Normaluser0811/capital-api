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
import json
import os
import re
import sys
import time
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
# 群益無可用源：台股加權——富時台期貨口徑不同且含夜盤（實測日漲跌方向翻轉）、
# 國內上市櫃指數線需證券帳戶 → 走 scraper DB fallback（^TWII 現貨，乾淨）。
UNCOVERED = ("taiex",)

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
        settle_val = q.get("settle") or hist.get(settle_date.isoformat()) or q["ref"]
        hist[settle_date.isoformat()] = settle_val
    else:
        settle_date = day_d - timedelta(days=1)
        while settle_date.weekday() >= 5:
            settle_date -= timedelta(days=1)
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
