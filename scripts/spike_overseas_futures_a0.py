"""Phase A0 盤中 spike：群益海期（SKOSQuoteLib）價格源探勘。

這是「探勘腳本」(spike)，不是生產程式——不入庫、不碰 DB。
目的＝回答 BFW 日報群益價格源計畫（bfw-daily-report-capital-price-and-commodity-expansion.md）
Phase A0 的五個待答問題：

  Q1 線上商品檔複驗（官方 xlsx 是 2025-03 vintage）＋ FX 現貨頁/INDEX 頁可訂性
  Q2 海期歷史日K API（SKOSQuoteLib_RequestKLineByDate → OnKLineData）有無/格式
  Q3 nRef/nClose/nTradingDay 的交易日語意（逐交易所記錄，供對照交易所正式結算）
  Q4 HOT `{root}0000` 訂閱 + 當下映射的具體合約（OnOverseaProductsDetail 的下單代碼）
  Q5 登入併發（--hold 兩行程對測）＋ GetQuoteStatus 連線數資訊

官方依據（SKCOM_APIManual_V2.13.52.docx §4-5）：
  - RequestStocks(psPageNo, bstrStockNos)：psPageNo=-1 自動配號；
    bstrStockNos = "交易所,代碼#交易所,代碼…"（例 CBOT,ZB1712#HKEx,HSI1712）。
  - OnOverseaProducts：[交易所代碼],[交易所名稱],[商品報價代碼],[商品名稱],[最後交易日],[第一通知日]；
    全部回傳完畢會來一筆以「##」開頭的內容。最後交易日 0/99991231＝指數匯率等不可交易商品。
  - OnOverseaProductsDetail（GetOverseaProductDetail(1) 觸發）：多 [交易所下單代碼],[商品下單代碼]。
  - RequestKLineByDate(bstrStockNo, sKLineType, YYYYMMDD, YYYYMMDD, sMinuteNumber)：
    bstrStockNo 例 "CME,ES1609"；type 1=日線；資料走 OnKLineData（[日期],[開],[高],[低],[收],[量]）。
  - 報價事件只有 pythoncom.PumpWaitingMessages 泵得到（comtypes.PumpEvents 收不到，2026-06-16 教訓）。

用法（都要盤中、capital-api venv）：
  python scripts/spike_overseas_futures_a0.py --products-only          # Q1：抓兩份商品檔 + 目標代碼盤點
  python scripts/spike_overseas_futures_a0.py --symbols "CBOT,C0000,CBOT,C2512" --seconds 30   # Q3/Q4
  python scripts/spike_overseas_futures_a0.py --kline "CBOT,C0000" --kline-days 10             # Q2
  python scripts/spike_overseas_futures_a0.py --hold 90                # Q5：先開這個，再開第二個行程觀察互踢

產出：docs/overseas_futures_spike_a0_capture_*.md（自動 dump，gitignored）；
結論人工彙整到 docs/overseas_futures_spike_a0.md。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import OrderedDict
from datetime import datetime, timedelta
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

DOCS = ROOT / "docs"

# 計畫檔（bfw-daily-report v2）要複驗的目標代碼：{(交易所猜測, HOT/現貨代碼): 用途}
# 交易所欄只是「xlsx 盤點時的認知」，實際以線上商品檔為準（本 spike 的目的之一）。
TARGET_CODES: dict[str, str] = {
    # 既有 29 檔會用到的期貨
    "B0000": "布蘭特原油(ICEEU)", "CL0000": "西德州原油(NYM)",
    "W0000": "小麥(CBOT)", "C0000": "玉米(CBOT)", "S0000": "黃豆(CBOT)",
    "BO0000": "黃豆油(CBOT)", "O0000": "燕麥(CBOT)", "RR0000": "粗米(CBOT)",
    "HG0000": "紐約銅(NYM/COMEX)", "GC0000": "黃金(NYM/COMEX)", "SI0000": "白銀(NYM/COMEX)",
    "SB0000": "11號糖(ICEUS)", "KC0000": "咖啡(ICEUS)", "CC0000": "可可(ICEUS)",
    "CT0000": "棉花(ICEUS)", "OJF0000": "橘子汁(ICEUS)",
    "LC0000": "活牛(CME)", "LH0000": "瘦豬(CME)",
    "DX0000": "美元指數(ICEUS)", "TY0000": "十年債(CBOT)",
    # 新增 13 檔
    "ALI0000": "鋁(NYM/COMEX)", "PA0000": "鈀金(NYM)", "PL0000": "白金(NYM)",
    "HO0000": "燃油(NYM)", "NG0000": "天然氣(NYM)", "RB0000": "無鉛汽油(NYM)",
    "FC0000": "肉牛(CME)",
    # FX 現貨頁 + CME 匯率期貨備援
    "SUSDJPY": "日圓現貨(FX頁)", "SGBPUSD": "英鎊現貨(FX頁)", "SEURUSD": "歐元現貨(FX頁)",
    "SUSDCHF": "瑞郎現貨(FX頁)", "SUSDCAD": "加幣現貨(FX頁)", "SAUDUSD": "澳幣現貨(FX頁)",
    "JY0000": "日圓期貨(CME)", "BP0000": "英鎊期貨(CME)", "EC0000": "歐元期貨(CME)",
    "SF0000": "瑞郎期貨(CME)", "CD0000": "加幣期貨(CME)", "AD0000": "澳幣期貨(CME)",
    # 橡膠（拍板⑦ SGX TSR20 為主、OSE 東京膠參考）
    "STF0000": "TSR20橡膠(SGX)", "JRU0000": "東京橡膠(OSE)",
    # INDEX 現貨頁（延遲；日報指數備援）
    "NI225": "日經225現貨(INDEX頁)", "KOSPI": "KOSPI現貨(INDEX頁)",
}


def _make_pump():
    """報價事件只有 pythoncom 泵得到（2026-06-16 海選 spike 根因），缺 pywin32 直接失敗。"""
    import pythoncom

    def pump(seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            pythoncom.PumpWaitingMessages()
            time.sleep(0.05)

    return pump


class _State:
    def __init__(self):
        self.connect_events: list[tuple] = []
        self.products: list[str] = []            # OnOverseaProducts 片段
        self.products_done = False               # 收到 ## 結尾
        self.detail: list[str] = []              # OnOverseaProductsDetail 片段
        self.detail_done = False
        self.last_frag_ts: float | None = None
        self.quote_samples: "OrderedDict[str, dict]" = OrderedDict()   # symbol -> 最新原生欄位
        self.quote_first: "OrderedDict[str, dict]" = OrderedDict()     # symbol -> 第一筆
        self.quote_counts: dict[str, int] = {}
        self.first_quote_ts: float | None = None
        self.last_quote_ts: float | None = None
        self.kline_rows: "OrderedDict[str, list[str]]" = OrderedDict()  # stock_no -> 資料列
        self.kline_last_ts: float | None = None


def _dump_fields(stock) -> "OrderedDict[str, object]":
    raw = OrderedDict()
    for fname, _ftype in getattr(stock, "_fields_", []):
        try:
            raw[fname] = getattr(stock, fname)
        except Exception as exc:  # noqa: BLE001
            raw[fname] = f"<讀取失敗: {exc}>"
    return raw


def _build_event(os_lib, sk, client, state: _State):
    class OSQuoteSpikeEvent:
        def OnConnect(self, code: int, socket_code: int):
            msg = client.get_return_message(code)
            state.connect_events.append((datetime.now().strftime("%H:%M:%S"),
                                         int(code), int(socket_code), msg))
            print(f"[OnConnect] code={code} socket={socket_code} msg={msg}")

        def OnOverseaProducts(self, value: str):
            state.products.append(value)
            state.last_frag_ts = time.time()
            if value.startswith("##"):
                state.products_done = True
            n = len(state.products)
            if n <= 3 or n % 2000 == 0 or value.startswith("##"):
                preview = value if len(value) <= 120 else value[:120] + "..."
                print(f"[OnOverseaProducts #{n}] {preview}")

        def OnOverseaProductsDetail(self, value: str):
            state.detail.append(value)
            state.last_frag_ts = time.time()
            if value.startswith("##"):
                state.detail_done = True
            n = len(state.detail)
            if n <= 3 or n % 2000 == 0 or value.startswith("##"):
                preview = value if len(value) <= 120 else value[:120] + "..."
                print(f"[OnOverseaProductsDetail #{n}] {preview}")

        def OnNotifyQuoteLONG(self, index: int):
            try:
                stock = sk.SKFOREIGNLONG()
                stock, code = os_lib.SKOSQuoteLib_GetStockByIndexLONG(index, stock)
                if code != 0:
                    return
                raw = _dump_fields(stock)
                symbol = str(raw.get("bstrStockNo", f"idx{index}"))
                now = time.time()
                if state.first_quote_ts is None:
                    state.first_quote_ts = now
                state.last_quote_ts = now
                state.quote_counts[symbol] = state.quote_counts.get(symbol, 0) + 1
                raw["_captured_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if symbol not in state.quote_first:
                    state.quote_first[symbol] = raw
                    print(f"[Quote 首筆] {symbol}  close={raw.get('nClose')} ref={raw.get('nRef')} "
                          f"settle={raw.get('nSettlePrice')} day={raw.get('nTradingDay')} "
                          f"dec={raw.get('sDecimal')}")
                state.quote_samples[symbol] = raw
            except Exception as exc:  # noqa: BLE001
                print(f"[OnNotifyQuoteLONG] 解析失敗: {exc}")

        def OnKLineData(self, stock_no: str, data: str):
            state.kline_rows.setdefault(str(stock_no), []).append(str(data))
            state.kline_last_ts = time.time()
            rows = state.kline_rows[str(stock_no)]
            if len(rows) <= 5 or len(rows) % 50 == 0:
                print(f"[OnKLineData] {stock_no} #{len(rows)}: {data}")

        # 明確不處理的事件（避免 comtypes 印 unhandled 警告洗版）
        def OnNotifyTicksNineDigitLONG(self, *args):
            pass

        def OnNotifyBest5NineDigitLONG(self, *args):
            pass

        def OnNotifyBest10NineDigitLONG(self, *args):
            pass

        def OnNotifyHistoryTicksNineDigitLONG(self, *args):
            pass

    return OSQuoteSpikeEvent()


def _parse_products(fragments: list[str]) -> dict[str, dict]:
    """商品檔片段 → {code: {exch, exch_name, name, ltd, first_notice}}。
    片段可能一片多列（換行分隔），逐列 CSV 拆。"""
    out: dict[str, dict] = {}
    for frag in fragments:
        for line in str(frag).replace("\r", "\n").split("\n"):
            line = line.strip()
            if not line or line.startswith("##"):
                continue
            parts = line.split(",")
            if len(parts) < 4:
                continue
            exch, exch_name, code, name = parts[0], parts[1], parts[2], parts[3]
            rec = {"exch": exch, "exch_name": exch_name, "name": name,
                   "ltd": parts[4] if len(parts) > 4 else "",
                   "rest": ",".join(parts[4:])}
            out[code] = rec
    return out


def _wait_fragments(pump, state: _State, done_flag: str, idle_s: int, max_s: int, label: str):
    start = time.time()
    while True:
        pump(1.0)
        now = time.time()
        if getattr(state, done_flag):
            print(f"   ✅ {label}：收到 ## 結束標記")
            break
        idle = now - (state.last_frag_ts or start)
        buf = state.products if "products" in done_flag else state.detail
        if buf and idle >= idle_s:
            print(f"   ⚠️ {label}：idle {idle_s}s 視為完成（沒看到 ## 標記）")
            break
        if now - start >= max_s:
            print(f"   ⏱️ {label}：達上限 {max_s}s")
            break


def _write_capture(state: _State, args, tag: str) -> Path:
    DOCS.mkdir(parents=True, exist_ok=True)
    out = DOCS / f"overseas_futures_spike_a0_capture_{tag}.md"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    lines.append(f"# 海期 A0 spike 自動 capture（{tag}）")
    lines.append("")
    lines.append(f"> 產生時間：{ts}　參數：{vars(args)}")
    lines.append(f"> OnConnect 事件：{state.connect_events or '（未收到）'}")
    lines.append("")

    if state.products:
        joined = "".join(state.products)
        lines.append(f"## 商品檔 OnOverseaProducts（{len(state.products)} 片段、{len(joined):,} chars、"
                     f"done={state.products_done}）")
        lines.append("")
        lines.append("```")
        lines.append(joined)
        lines.append("```")
        lines.append("")
    if state.detail:
        joined = "".join(state.detail)
        lines.append(f"## 商品檔含下單代碼 OnOverseaProductsDetail（{len(state.detail)} 片段、"
                     f"{len(joined):,} chars、done={state.detail_done}）")
        lines.append("")
        lines.append("```")
        lines.append(joined)
        lines.append("```")
        lines.append("")

    if state.quote_first:
        lines.append(f"## 報價樣本（{len(state.quote_first)} symbol）")
        if state.first_quote_ts and state.last_quote_ts and state.last_quote_ts > state.first_quote_ts:
            span = state.last_quote_ts - state.first_quote_ts
            total = sum(state.quote_counts.values())
            lines.append(f"- 更新頻率：{span:.1f}s 內 {total} 筆（{total / span:.2f} 筆/秒）")
        lines.append("")
        for symbol in state.quote_first:
            first = state.quote_first[symbol]
            last = state.quote_samples.get(symbol, {})
            cnt = state.quote_counts.get(symbol, 0)
            lines.append(f"### `{symbol}`（收到 {cnt} 筆）")
            lines.append("")
            lines.append("| 欄位 | 首筆 | 末筆 |")
            lines.append("|---|---|---|")
            for fname, val in first.items():
                sval = str(val).replace("|", "\\|")
                lval = str(last.get(fname, "")).replace("|", "\\|")
                lines.append(f"| `{fname}` | `{sval}` | `{lval}` |")
            lines.append("")

    if state.kline_rows:
        lines.append("## KLine（OnKLineData）")
        lines.append("")
        for stock_no, rows in state.kline_rows.items():
            lines.append(f"### `{stock_no}`（{len(rows)} 列）")
            lines.append("")
            lines.append("```")
            lines.extend(rows[:400])
            if len(rows) > 400:
                lines.append(f"...（共 {len(rows)} 列，截前 400）")
            lines.append("```")
            lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="群益海期 Phase A0 探勘 spike")
    parser.add_argument("--products-only", action="store_true", help="Q1：抓兩份商品檔 + 目標代碼盤點")
    parser.add_argument("--symbols", default="", help="訂閱清單：交易所,代碼 以 # 或 ; 分隔（Q3/Q4）")
    parser.add_argument("--seconds", type=int, default=30, help="訂閱後接收秒數")
    parser.add_argument("--kline", default="", help="Q2：日K 查詢目標（交易所,代碼），多筆 # 分隔")
    parser.add_argument("--kline-days", type=int, default=10, help="日K 往回天數")
    parser.add_argument("--kline-type", type=int, default=1, help="0分/1日/2週/3月")
    parser.add_argument("--hold", type=int, default=0, help="Q5：登入+連線後持有 N 秒，印 IsConnected（開兩行程對測）")
    parser.add_argument("--tag", default="", help="capture 檔名後綴（預設依模式）")
    parser.add_argument("--idle", type=int, default=5, help="商品檔 idle 完成門檻秒數")
    parser.add_argument("--max-wait", type=int, default=120, help="商品檔等待上限秒數")
    args = parser.parse_args()

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
    tag = args.tag or ("products" if args.products_only else
                       "hold" if args.hold else
                       "kline" if args.kline else "quotes")
    try:
        masked = user_id[:2] + "*" * max(len(user_id) - 4, 0) + user_id[-2:]
        print(f"📡 登入中… ({masked})  pid={os.getpid()}")
        client.login(user_id, password)
        print(f"✅ 登入成功  {datetime.now():%H:%M:%S}")

        sk = get_sk_module()
        os_lib = create_os_quote_lib()
        event = _build_event(os_lib, sk, client, state)
        handler = comtypes.client.GetEvents(os_lib, event)

        print("📊 連線海期報價伺服器（SKOSQuoteLib_EnterMonitorLONG）…")
        rc = os_lib.SKOSQuoteLib_EnterMonitorLONG()
        print(f"   EnterMonitorLONG rc={rc}（{client.get_return_message(rc)}）")

        connected = False
        deadline = time.time() + 20
        while time.time() < deadline:
            pump(0.5)
            try:
                if int(os_lib.SKOSQuoteLib_IsConnected()) == 1:
                    connected = True
                    break
            except Exception:  # noqa: BLE001
                pass
        print(f"   IsConnected={'1 ✅' if connected else '≠1 ⚠️（非盤中或無海期報價權限？）'}")

        # 連線數資訊（Q5 佐證）；[in,out] 參數 comtypes 會回傳
        try:
            status = os_lib.SKOSQuoteLib_GetQuoteStatus(0, False)
            print(f"   GetQuoteStatus → {status}")
        except Exception as exc:  # noqa: BLE001
            print(f"   GetQuoteStatus 呼叫失敗：{exc}")

        # 官方：避免在 OnConnect 直接 RequestStocks，等商品檔下載完。先等幾秒讓元件載完。
        pump(3.0)

        if args.hold:
            print(f"⏳ Q5 hold 模式：持有連線 {args.hold}s，每 5s 印 IsConnected 與時戳。")
            print("   → 另開第二個行程跑同樣指令，觀察本行程是否被踢（IsConnected 變化 / OnConnect 事件）。")
            end = time.time() + args.hold
            while time.time() < end:
                pump(5.0)
                try:
                    alive = int(os_lib.SKOSQuoteLib_IsConnected())
                except Exception as exc:  # noqa: BLE001
                    alive = f"exc:{exc}"
                print(f"   [{datetime.now():%H:%M:%S}] pid={os.getpid()} IsConnected={alive} "
                      f"connect_events={len(state.connect_events)}")
            _write_capture(state, args, tag)
            return 0

        if args.products_only:
            print("📋 RequestOverseaProducts（線上商品檔）…")
            rc = os_lib.SKOSQuoteLib_RequestOverseaProducts()
            print(f"   rc={rc}（{client.get_return_message(rc)}）")
            _wait_fragments(pump, state, "products_done", args.idle, args.max_wait, "商品檔")

            print("📋 GetOverseaProductDetail(1)（含下單代碼）…")
            state.last_frag_ts = None
            rc = os_lib.SKOSQuoteLib_GetOverseaProductDetail(1)
            print(f"   rc={rc}（{client.get_return_message(rc)}）")
            _wait_fragments(pump, state, "detail_done", args.idle, args.max_wait, "商品檔(下單代碼)")

            # 目標代碼盤點
            catalog = _parse_products(state.products)
            print(f"\n===== Q1 目標代碼盤點（線上商品檔共 {len(catalog)} 檔） =====")
            missing = []
            for code, why in TARGET_CODES.items():
                rec = catalog.get(code)
                if rec:
                    print(f"  ✅ {code:<9} {why:<22} → {rec['exch']},{code}  {rec['name']}  ltd={rec['ltd']}")
                else:
                    missing.append((code, why))
                    print(f"  ❌ {code:<9} {why:<22} → 線上商品檔查無")
            if missing:
                print(f"\n  查無 {len(missing)} 檔：{[c for c, _ in missing]}")
                print("  → 用 root 前綴掃相近代碼：")
                for code, _why in missing:
                    root = code.replace("0000", "")[:4]
                    near = [f"{c}({catalog[c]['exch']} {catalog[c]['name']})"
                            for c in catalog if c.startswith(root)][:8]
                    print(f"     {code}: {near}")
            out = _write_capture(state, args, tag)
            print(f"\n📝 已寫出：{out}")
            return 0

        if args.kline:
            targets = [s.strip() for s in args.kline.replace(";", "#").split("#") if s.strip()]
            end_d = datetime.now().strftime("%Y%m%d")
            start_d = (datetime.now() - timedelta(days=args.kline_days)).strftime("%Y%m%d")
            for t in targets:
                print(f"📈 RequestKLineByDate({t!r}, type={args.kline_type}, {start_d}→{end_d})")
                rc = os_lib.SKOSQuoteLib_RequestKLineByDate(t, args.kline_type, start_d, end_d, 1)
                print(f"   rc={rc}（{client.get_return_message(rc)}）")
                # 等資料：idle 3s 或上限 30s
                t0 = time.time()
                while time.time() - t0 < 30:
                    pump(1.0)
                    if state.kline_last_ts and time.time() - state.kline_last_ts > 3:
                        break
            for stock_no, rows in state.kline_rows.items():
                print(f"   ← {stock_no}: {len(rows)} 列（首列 {rows[0] if rows else '—'}；"
                      f"末列 {rows[-1] if rows else '—'}）")
            if not state.kline_rows:
                print("   ⚠️ 未收到任何 OnKLineData")
            out = _write_capture(state, args, tag)
            print(f"\n📝 已寫出：{out}")
            return 0

        if args.symbols.strip():
            items = [s.strip() for s in args.symbols.replace(";", "#").split("#") if s.strip()]
            nos = "#".join(items)
            print(f"📈 訂閱 {len(items)} 檔（psPageNo=-1 自動配號）：{items}")
            page, rc = os_lib.SKOSQuoteLib_RequestStocks(-1, nos)
            print(f"   RequestStocks rc={rc}（{client.get_return_message(rc)}） page={page}")
            if rc != 0:
                print("   ⚠️ 訂閱未成功（3023=含無效商品代碼；整批會被拒收）")
            print(f"⏳ 接收報價 {args.seconds}s …")
            pump(args.seconds)
            print(f"   收到報價 symbol 數：{len(state.quote_first)}／訂閱 {len(items)}")
            silent = [i for i in items if i.split(",")[-1] not in state.quote_first]
            if silent:
                print(f"   無推播（休市或無變動）：{silent}")
                print("   → 逐檔 GetStockByNoLONG 拉快照補測：")
                for it in silent:
                    code_only = it.split(",")[-1]
                    try:
                        stock = sk.SKFOREIGNLONG()
                        stock, rc2 = os_lib.SKOSQuoteLib_GetStockByNoLONG(code_only, stock)
                        raw = _dump_fields(stock)
                        raw["_captured_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        raw["_via"] = "GetStockByNoLONG(pull)"
                        if rc2 == 0:
                            state.quote_first.setdefault(code_only, raw)
                            state.quote_samples[code_only] = raw
                            print(f"      {code_only}: rc=0 close={raw.get('nClose')} "
                                  f"ref={raw.get('nRef')} day={raw.get('nTradingDay')}")
                        else:
                            print(f"      {code_only}: rc={rc2}（{client.get_return_message(rc2)}）")
                    except Exception as exc:  # noqa: BLE001
                        print(f"      {code_only}: 例外 {exc}")
            out = _write_capture(state, args, tag)
            print(f"\n📝 已寫出：{out}")
            return 0

        print("ℹ️ 未指定模式：--products-only / --symbols / --kline / --hold 擇一。")
        return 0

    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"\n❌ 錯誤：{exc}")
        traceback.print_exc()
        try:
            _write_capture(state, args, tag)
        except Exception:  # noqa: BLE001
            pass
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
