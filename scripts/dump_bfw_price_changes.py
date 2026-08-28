"""BFW 日報價格檔 dump：群益 SKOSQuoteLib → 日／週漲跌幅 JSON。

供 scraper `daily-report --price-file` 使用（2026-08-26 user 指示：日報漲跌幅改用
群益 API 報價）。這是 A1/A2 正式管線落地前的過渡工具——COM 只在本腳本內使用，
scraper 生成管線不碰 COM。

方法（依 Phase A0 結論 `docs/overseas_futures_spike_a0.md`）：
- 期貨：由 `GetOverseaProductDetail(1)` 的下單代碼 `{root}_{YYYYMM}` 解出 HOT 當下
  映射的**具體合約**，抓該合約自身日K 算漲跌。🔴 絕不用 HOT 的 KLine 算跨日漲跌
  ——它是換月拼接序列（KC0000 實證），與 yfinance 同一種雷。
- 鋁（無 HOT）：從商品檔挑「最後交易日 >= as_of 的最近月份」當近月。
- FX 現貨頁／INDEX 延遲頁：代碼自身日K（無合約無換月）。
- 漲跌幅語意**鏡射 scraper `materials._changes_from_closes`**：只取 `< as_of` 且
  非週末的 bar；日＝最近一根 vs 前一根；週＝最近一根 vs 最近的「≤7 日曆天前」bar；
  最近 bar 距 as_of > 7 天＝過期序列 → 整組留空。
- ⚠️ KLine 收盤欄＝最後成交價非結算價（A0 結論）；與 yfinance 日線口徑一致，
  但與交易所正式結算可有 ~0.1-0.5% 差（黃金 08-25 實測 4715.9 vs 結算 4694.5）。

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
# 冷啟動：首日留空。合約選「LTD ≥ as_of+3 天的最近月」，換約時鏈重啟（再空一天）。
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
    - 快照 day < as_of（未開盤）：昨收＝nClose、前日收＝nRef（全快照，日K 只供週基準）。
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
        mode = f"未開盤：昨收=nClose({last_val})、前日收=nRef({prev_val})"

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
        "prev_date": str(prev_date if day_d >= as_of else "快照nRef"), "prev_close": prev_val,
    }


def _chain_front_contract(catalog: dict[str, dict], root: str, as_of: _date) -> str | None:
    """SETTLE_CHAIN 用：挑「LTD ≥ as_of+3 天的最近月」（避開臨到期月，減少換約頻率）。"""
    best: tuple[str, str] | None = None
    for code, rec in catalog.items():
        if not re.fullmatch(re.escape(root) + r"\d{4}", code):
            continue
        ltd = rec.get("ltd", "")
        if not re.fullmatch(r"\d{8}", ltd) or ltd in ("0", "99991231"):
            continue
        if _date(int(ltd[:4]), int(ltd[4:6]), int(ltd[6:])) < as_of + timedelta(days=3):
            continue
        if best is None or ltd < best[0]:
            best = (ltd, code)
    return best[1] if best else None


def _load_settle_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _settle_chain_changes(key: str, code: str, q: dict | None, as_of: _date,
                          settle_state: dict, series: str) -> dict:
    """結算價累積法：日漲跌＝今結算/昨結算（快照 nRef 逐日累積）。

    - 已收盤（day < as_of）：daily = nSettle/nRef 直接（快照自帶結算對）。
    - 盤中（day >= as_of）：nRef=昨結；昨結存檔、與**上一個交易日**存的 nRef 相除。
      上一筆不是前一交易日（週末容忍 ≤4 日曆天）或換了合約 → 留空（鏈重啟）。
    - 週漲跌：歷史滿 7 日曆天才有值。狀態檔同時被本函式更新（呼叫端負責存檔）。
    """
    def _null(reason: str) -> dict:
        return {"daily_pct": None, "weekly_pct": None, "series": series,
                "resolve": f"結算價累積法：{reason} → 留空"}

    if not q or not q.get("ref"):
        return _null("快照未取得")
    day = q["day"]
    try:
        day_d = _date(day // 10000, day // 100 % 100, day % 100)
    except ValueError:
        return _null(f"nTradingDay 異常（{day}）")

    st = settle_state.setdefault(key, {})
    prev_code = st.get("code")
    history: dict[str, float] = st.get("history", {}) if prev_code == code else {}

    if day_d < as_of:
        # 已收盤：settle=該日結算、ref=前一交易日結算 → 直接可算
        daily = (q["settle"] / q["ref"] - 1) * 100 if (q.get("settle") and q["ref"]) else None
        settle_date, settle_val = day_d, q.get("settle") or q["ref"]
        mode = f"已收盤：settle({q.get('settle')})/ref({q['ref']})"
    else:
        # 盤中：ref=settle(前一交易日)。與上一筆存檔（必須是前一交易日的 run）相除。
        settle_date = day_d - timedelta(days=1)
        while settle_date.weekday() >= 5:
            settle_date -= timedelta(days=1)
        settle_val = q["ref"]
        daily = None
        prev_dates = sorted(_date.fromisoformat(d) for d in history if _date.fromisoformat(d) < settle_date)
        if prev_dates:
            prev_d = prev_dates[-1]
            gap = (settle_date - prev_d).days
            prev_v = history[prev_d.isoformat()]
            if 1 <= gap <= 4 and prev_v:
                daily = (settle_val / prev_v - 1) * 100
        mode = f"盤中：昨結=nRef({settle_val})、前結=狀態檔"

    history[settle_date.isoformat()] = settle_val
    # 週漲跌：最近的「≤ settle_date-7」歷史結算
    weekly = None
    week_ago = settle_date - timedelta(days=7)
    for d in sorted((_date.fromisoformat(x) for x in history), reverse=True):
        if d <= week_ago:
            base = history[d.isoformat()]
            weekly = (settle_val / base - 1) * 100 if base else None
            break
    # 修剪 30 天外的舊值、更新狀態
    history = {d: v for d, v in history.items()
               if (as_of - _date.fromisoformat(d)).days <= 30}
    settle_state[key] = {"code": code, "history": history,
                        "updated": datetime.now().isoformat(timespec="seconds")}

    if daily is None:
        return {**_null(f"鏈尚未接上（{mode}；已存 {settle_date} 結算 {settle_val}，"
                        "明日起有值）"), "last_date": settle_date.isoformat()}
    return {
        "series": series, "resolve": f"結算價累積法（{mode}）",
        "daily_pct": round(daily, 4), "weekly_pct": round(weekly, 4) if weekly is not None else None,
        "last_date": settle_date.isoformat(), "last_close": settle_val,
        "prev_date": "結算鏈", "prev_close": None,
    }


def _parse_kline_rows(rows: list[str]) -> dict[_date, float]:
    closes: dict[_date, float] = {}
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
        closes[_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = close
    return closes


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
        plan: dict[str, tuple[str, str, str]] = {}   # key -> (exch, code, 說明)
        resolve_failed: dict[str, str] = {}          # key -> 原因
        for key, (exch, hot) in FUTURES_HOT.items():
            code = _hot_mapped_code(catalog, hot)
            if code and code in catalog:
                plan[key] = (exch, code, f"HOT {hot} → {code}")
            else:
                resolve_failed[key] = (f"HOT {hot} 映射失敗"
                                       f"（order_code={catalog.get(hot, {}).get('order_code')}）")
                print(f"   ⚠️ {key}: {resolve_failed[key]}")
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
        chain_plan: dict[str, tuple[str, str]] = {}
        for key, (exch, root) in SETTLE_CHAIN.items():
            code = _chain_front_contract(catalog, root, as_of)
            if code:
                chain_plan[key] = (exch, code)
            else:
                resolve_failed[key] = f"{root} 無可用月份（SETTLE_CHAIN）"
                print(f"   ⚠️ {key}: {resolve_failed[key]}")

        # 快照訂閱（結算價鏈 + SPOT_INDEX 混合法都要）：
        # 🔴 user 拍板（2026-08-26 第五輪）：**全期貨改結算價鏈**——每檔期貨的快照 nRef
        # ＝正式結算價，逐日存狀態檔；鏈未接上（冷啟動/換約日）退回同合約最後成交鏈
        # 並在 resolve 註明。FX 現貨無結算概念（nRef=NY 17:00 昨收＝KLine 同口徑）維持
        # KLine；SPOT_INDEX 維持混合法（現貨收盤口徑）。
        futures_keys = {k for k in plan if k in FUTURES_HOT}
        snap_codes = {c for k, (_e, c, _n) in plan.items() if k in futures_keys}
        snap_codes |= {c for _e, c in spot_index_plan.values()}
        snap_codes |= {c for _e, c in chain_plan.values()}
        if snap_codes:
            code2exch = {c: e for k, (e, c, _n) in plan.items()}
            code2exch.update({c: e for e, c in spot_index_plan.values()})
            code2exch.update({c: e for e, c in chain_plan.values()})
            nos = "#".join(f"{code2exch[c]},{c}" for c in sorted(snap_codes))
            page, rc = os_lib.SKOSQuoteLib_RequestStocks(-1, nos)
            print(f"📸 快照訂閱 {len(snap_codes)} 檔 rc={rc} page={page}")
            t0 = time.time()
            while time.time() - t0 < 15 and not snap_codes <= set(state.quotes):
                pump(0.5)
            missing = snap_codes - set(state.quotes)
            print(f"   快照到位 {len(snap_codes) - len(missing)}/{len(snap_codes)}"
                  + (f"，未到：{sorted(missing)}" if missing else ""))

        print(f"📈 逐檔抓日K（{len(plan) + len(spot_index_plan)} 檔）…")
        start_d = (as_of - timedelta(days=args.days)).strftime("%Y%m%d")
        end_d = as_of.strftime("%Y%m%d")
        kline_targets = dict(plan)
        for key, (exch, code) in spot_index_plan.items():
            kline_targets[key] = (exch, code, "spot_index(週基準/前日收)")
        for key, (exch, code, note) in kline_targets.items():
            rc = os_lib.SKOSQuoteLib_RequestKLineByDate(f"{exch},{code}", 1, start_d, end_d, 1)
            t0 = time.time()
            # 等這一檔的資料到齊（idle 2s）再抓下一檔，避免事件交錯時難定位缺漏
            while time.time() - t0 < 20:
                pump(0.5)
                if code in state.kline and state.kline_last_ts and time.time() - state.kline_last_ts > 2:
                    break
            n = len(state.kline.get(code, []))
            print(f"   {key:<14} {exch},{code:<9} rc={rc} rows={n}  ({note})")

        prices: dict[str, dict] = {}
        problems: list[str] = []
        settle_state = _load_settle_state()
        for key, (exch, code, note) in plan.items():
            series = f"{exch},{code}"
            closes = _parse_kline_rows(state.kline.get(code, []))
            cc = _changes_from_closes(closes, as_of)   # 同合約最後成交鏈（fallback/週過渡）

            if key in futures_keys:
                se = _settle_chain_changes(key, code, state.quotes.get(code), as_of,
                                           settle_state, series)
                if se["daily_pct"] is not None:
                    # 結算鏈為主；週漲跌：結算歷史滿 7 天前用最後成交鏈過渡
                    weekly = se["weekly_pct"]
                    wk_src = "結算鏈"
                    if weekly is None and cc is not None:
                        weekly = cc["weekly_pct"]
                        wk_src = "最後成交鏈(過渡)"
                    prices[key] = {
                        "series": series,
                        "resolve": f"{note}；日=結算鏈、週={wk_src}",
                        "daily_pct": se["daily_pct"], "weekly_pct": weekly,
                        "last_date": se["last_date"], "last_close": se["last_close"],
                        "prev_date": "結算鏈", "prev_close": None,
                    }
                    continue
                # 鏈未接上（冷啟動/換約日）→ 同合約最後成交鏈 fallback（resolve 註明）
                if cc is not None:
                    prices[key] = {
                        "series": series,
                        "resolve": f"{note}；結算鏈未接上（{se['resolve'][:60]}）"
                                   "→ 本日用同合約最後成交鏈",
                        **cc,
                    }
                    continue
                problems.append(f"{key}（{series}：結算鏈未接上且 bar 不足）")
                prices[key] = {"daily_pct": None, "weekly_pct": None, "series": series,
                               "resolve": f"{note}；結算鏈未接上且 bar 不足 → 留空"}
                continue

            # FX 現貨：維持 KLine 最後成交鏈（nRef=NY 17:00 昨收，同口徑）
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
        for key, (exch, code) in chain_plan.items():
            entry = _settle_chain_changes(key, code, state.quotes.get(code), as_of,
                                          settle_state, f"{exch},{code}")
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
            "source": "capital-api SKOSQuoteLib dump_bfw_price_changes（映射合約自身日K；"
                      "close=最後成交非結算）",
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
