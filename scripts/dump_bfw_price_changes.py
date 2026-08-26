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
}
FUTURES_FRONT: dict[str, tuple[str, str]] = {
    "aluminum": ("NYM", "ALI"),      # 無 HOT，逐月自選近月
}
SPOT: dict[str, tuple[str, str]] = {
    "jpy": ("FX", "SUSDJPY"),
    "gbp": ("FX", "SGBPUSD"),
    "eur": ("FX", "SEURUSD"),
    "chf": ("FX", "SUSDCHF"),
    "cad": ("FX", "SUSDCAD"),
    "aud": ("FX", "SAUDUSD"),
    "nikkei": ("INDEX", "NI225"),
    "kospi": ("INDEX", "KOSPI"),
    "hang_seng": ("INDEX", "HHHSI"),
}
# 群益無同口徑來源（sp500/dow/taiex 走 scraper DB fallback；恆科/A50 本來就留空）
UNCOVERED = ("sp500", "dow", "taiex", "hang_seng_tech", "ftse_a50")

_STALE_DAYS = 7


class _State:
    def __init__(self):
        self.detail: list[str] = []
        self.detail_done = False
        self.last_frag_ts: float | None = None
        self.kline: dict[str, list[str]] = {}
        self.kline_last_ts: float | None = None


def _make_pump():
    import pythoncom

    def pump(seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            pythoncom.PumpWaitingMessages()
            time.sleep(0.05)

    return pump


def _build_event(state: _State):
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

        def OnNotifyQuoteLONG(self, *a):
            pass

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


def _front_month_code(catalog: dict[str, dict], root: str, as_of: _date) -> str | None:
    """無 HOT 的商品：挑「LTD >= as_of 的最近月份」（跳過價差單）。"""
    best: tuple[str, str] | None = None
    for code, rec in catalog.items():
        if not re.fullmatch(re.escape(root) + r"\d{4}", code):
            continue
        ltd = rec.get("ltd", "")
        if not re.fullmatch(r"\d{8}", ltd) or ltd in ("0", "99991231"):
            continue
        if _date(int(ltd[:4]), int(ltd[4:6]), int(ltd[6:])) < as_of:
            continue
        if best is None or ltd < best[0]:
            best = (ltd, code)
    return best[1] if best else None


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
        get_sk_module()
        handler = comtypes.client.GetEvents(os_lib, _build_event(state))

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

        # 解每個 key 要抓的（exch, 具體代碼）
        plan: dict[str, tuple[str, str, str]] = {}   # key -> (exch, code, 說明)
        for key, (exch, hot) in FUTURES_HOT.items():
            code = _hot_mapped_code(catalog, hot)
            if code and code in catalog:
                plan[key] = (exch, code, f"HOT {hot} → {code}")
            else:
                print(f"   ⚠️ {key}: HOT {hot} 映射失敗（order_code={catalog.get(hot, {}).get('order_code')}）")
        for key, (exch, root) in FUTURES_FRONT.items():
            code = _front_month_code(catalog, root, as_of)
            if code:
                plan[key] = (exch, code, f"front-month {root} → {code}")
            else:
                print(f"   ⚠️ {key}: 找不到 {root} 近月")
        for key, (exch, code) in SPOT.items():
            if code in catalog:
                plan[key] = (exch, code, "spot")
            else:
                print(f"   ⚠️ {key}: {exch},{code} 不在商品檔")

        print(f"📈 逐檔抓日K（{len(plan)} 檔）…")
        start_d = (as_of - timedelta(days=args.days)).strftime("%Y%m%d")
        end_d = as_of.strftime("%Y%m%d")
        for key, (exch, code, note) in plan.items():
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
        for key, (exch, code, note) in plan.items():
            closes = _parse_kline_rows(state.kline.get(code, []))
            result = _changes_from_closes(closes, as_of)
            if result is None:
                problems.append(f"{key}（{exch},{code}：bar 不足或過期）")
                continue
            entry = {"series": f"{exch},{code}", "resolve": note, **result}
            prices[key] = entry

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
            print(f"  {key:<14} 日 {d:>8} 週 {w:>8}  {e['series']:<15} "
                  f"{e['prev_date']}→{e['last_date']} {e['prev_close']}→{e['last_close']}")
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
