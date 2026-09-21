# -*- coding: utf-8 -*-
"""唯讀探針：印出國內報價快照的原始欄位，回答「nTradingDay 什麼時候滾到下一個交易日」。

**不寫 `data/bfw_settle_state.json`、不產價格檔、不改任何檔案。** 只登入、讀、印、登出。

為什麼需要它（2026-09-21）：台指期的日漲跌幅每天慢一個交易日，根因是
`_domestic_snapshot()` 只拿得到 `nRef`（＝`nTradingDay` 前一交易日的結算），
而排程在台股開盤前跑 ⇒ 鏈永遠補不到最後一個交易日。
修法「傍晚多跑一次餵鏈」成不成立，取決於一件**還沒有人實測過**的事：

    台股 15:00 夜盤開盤後，群益的 nTradingDay 會不會滾到下一個交易日？

會滾 ⇒ 那時的 nRef ＝**當日**結算 ⇒ 傍晚跑一次就補得上。
不會滾 ⇒ 傍晚跑拿到的仍是前一交易日 ⇒ 這個修法無效，要改抓期交所官方行情。

⚠️ 盤前實測（2026-09-21 06:32）：nTradingDay=20260918、nRef=46459（＝09-17 結算）。
   拿這個時點的觀察去推論 15:00 之後的行為是**沒有根據的**，所以才有這支探針。
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

# cp950 主控台印不出 emoji 會整支當掉（2026-09-02 rotate_gemini_key.py 前例）。
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import comtypes.client  # noqa: E402
import pythoncom  # noqa: E402

from capitalapi import CapitalClient  # noqa: E402
from capitalapi.skcom import create_quote_lib, get_sk_module  # noqa: E402

CODES = [c for c in (sys.argv[1:] or ["TX10AM", "TX11AM"])]


def _pump(seconds: float) -> None:
    # 與 dump 用同一種泵法（pythoncom.PumpWaitingMessages），不要另立第二種。
    end = time.time() + seconds
    while time.time() < end:
        pythoncom.PumpWaitingMessages()
        time.sleep(0.05)


def main() -> int:
    user_id = os.getenv("CAPITAL_USER_ID", "")
    password = os.getenv("CAPITAL_PASSWORD", "")
    if not user_id or not password:
        print("❌ .env 缺 CAPITAL_USER_ID / CAPITAL_PASSWORD")
        return 1

    client = CapitalClient()
    q_lib = None
    connected = {"ok": False}
    try:
        print(f"⏱  本機時間 {datetime.now().isoformat(timespec='seconds')}（台北）")
        client.login(user_id, password)
        q_lib = create_quote_lib()
        sk = get_sk_module()

        class _Ev:
            def OnConnection(self, nKind, nCode):            # noqa: N802
                if int(nKind) == 3003:
                    connected["ok"] = True

            def OnNotifyStockList(self, sMarketNo, bstrStockData):  # noqa: N802
                pass

            def OnNotifyQuoteLONG(self, sMarketNo, nIndex):  # noqa: N802
                pass

        handler = comtypes.client.GetEvents(q_lib, _Ev())    # noqa: F841
        rc = q_lib.SKQuoteLib_EnterMonitorLONG()
        print(f"EnterMonitorLONG rc={rc}")
        t0 = time.time()
        while time.time() - t0 < 60 and not connected["ok"]:
            _pump(1.0)
        if not connected["ok"]:
            print("❌ 60 秒內沒連上")
            return 1

        q_lib.SKQuoteLib_RequestStockList(2)
        _pump(3.0)

        for code in CODES:
            stock = sk.SKSTOCKLONG()
            res = q_lib.SKQuoteLib_GetStockByNoLONG(code, stock)
            if isinstance(res, (tuple, list)):
                stock, r = res[0], res[-1]
            else:
                r = res
            if r != 0:
                print(f"  {code}: rc={r}（取不到）")
                continue
            dec = int(getattr(stock, "sDecimal", 0) or 0)
            sc = 10 ** dec if dec else 1
            fields = {}
            for name in ("nTradingDay", "nRef", "nClose", "nOpen", "nHigh", "nLow",
                         "nSettlePrice", "nTBid", "nTAsk", "nTQty", "nYQty"):
                raw = getattr(stock, name, None)
                fields[name] = raw
            print(f"\n  ── {code}  {getattr(stock, 'bstrStockName', '')} "
                  f"(sDecimal={dec})")
            for name, raw in fields.items():
                if raw is None:
                    print(f"     {name:<14} （此欄不存在）")
                elif name.startswith("n") and name not in ("nTradingDay", "nTQty", "nYQty"):
                    print(f"     {name:<14} raw={raw!r}  ÷10^{dec} = {raw / sc if isinstance(raw,(int,float)) else '—'}")
                else:
                    print(f"     {name:<14} raw={raw!r}")
        return 0
    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"❌ {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1
    finally:
        try:
            if q_lib is not None:
                q_lib.SKQuoteLib_LeaveMonitor()
        except Exception:  # noqa: BLE001
            pass
        if client.is_logged_in:
            client.logout()
        print("\n📴 已結束（本次未寫入任何檔案）。")


if __name__ == "__main__":
    raise SystemExit(main())
