"""Phase 0 現場探勘 spike：群益海外選擇權欄位 / 商品清單 / symbol 格式調查。

這是「探勘腳本」(spike)，不是生產程式，也不入庫 / 不寫 Excel——對 DB 唯讀（其實完全不碰 DB）。
目的：登入群益 → 抓海外選擇權商品清單 → 訂閱一條鏈 → dump 每筆 SKFOREIGNLONG 的
**全部原生欄位**（用 ctypes `_fields_` 列舉，連 wrapper 目前沒解析的欄位都抓得到），
以便確認：

  1. symbol 字串格式（root / 到期年月 / 履約價 / Call·Put 的位置與編碼）
  2. 到期日(LTD) 來源——群益是否直接回傳？或只給到期年月需另推？
  3. 標的期貨代碼與選擇權 root 的關係（Black-76 的 F 從哪來）
  4. 報價更新頻率（決定串流 flush 秒數）
  5. 單帳號訂閱檔數上限（MVP 多商品擴展前要知道）

執行前提（重要）：
  - **僅 Windows + 群益 COM 元件已安裝**（SKCOM.dll）。
  - **需登入**：在專案根目錄 .env 填 CAPITAL_USER_ID / CAPITAL_PASSWORD。
  - **盤中跑**：海外選擇權是事件驅動快照，非盤中可能收不到報價（商品清單通常仍可取得）。
  - **建議先 `pip install pywin32`**（pythoncom 訊息泵）；沒裝會退回 comtypes 的 PumpEvents。

用法：
  # 第一步：只抓商品清單（先看有哪些海外選擇權、確認流動性好的標的）
  python scripts/spike_overseas_options.py --products-only

  # 第二步：用上一步看到的 symbol 訂閱一條鏈，dump 原生欄位（盤中）
  python scripts/spike_overseas_options.py --symbols "<symbol1>,<symbol2>,..." --seconds 60

產出：
  docs/overseas_options_field_survey.md   （自動：商品清單 raw dump + 報價原生欄位樣本 + 自動觀察）
  docs/symbol_format_spec.md              （若不存在則建立 scaffold，供人工依 capture 填寫）
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

# UTF-8 輸出（Windows cp950 會亂碼）
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import comtypes.client  # noqa: E402

from capitalapi import CapitalClient  # noqa: E402
from capitalapi.skcom import create_oo_quote_lib, get_sk_module  # noqa: E402

DOCS = ROOT / "docs"


# --------------------------------------------------------------------------- #
# COM 訊息泵：優先 pythoncom（與既有腳本一致），無 pywin32 則退回 comtypes
# --------------------------------------------------------------------------- #
def _make_pump():
    try:
        import pythoncom

        def pump(seconds: float):
            end = time.time() + seconds
            while time.time() < end:
                pythoncom.PumpWaitingMessages()
                time.sleep(0.05)

        return pump, "pythoncom"
    except ImportError:
        def pump(seconds: float):
            try:
                comtypes.client.PumpEvents(seconds)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:  # noqa: BLE001
                # 不靜默退化成純 sleep（那段時間不泵訊息＝收不到報價卻看似在等）
                print(f"[pump] PumpEvents 例外（改 sleep，期間不泵 COM 訊息）: {exc}")
                time.sleep(seconds)

        return pump, "comtypes.PumpEvents"


# --------------------------------------------------------------------------- #
# 事件處理：dump 原生 SKFOREIGNLONG 欄位
# --------------------------------------------------------------------------- #
class _SpikeState:
    def __init__(self):
        self.products: list[str] = []          # OnProducts 收到的原始字串
        self.quote_samples: "OrderedDict[str, dict]" = OrderedDict()  # symbol -> 原生欄位
        self.quote_counts: dict[str, int] = {}  # symbol -> 收到次數（估更新頻率）
        self.first_quote_ts: float | None = None
        self.last_quote_ts: float | None = None
        self.connect_code: int | None = None


def _build_event_class(oo_lib, sk, client, state: _SpikeState):
    class OOQuoteSpikeEvent:
        def OnConnect(self, code: int, socket_code: int):
            state.connect_code = code
            msg = client.get_return_message(code)
            print(f"[OnConnect] code={code} socket={socket_code} msg={msg}")

        def OnProducts(self, value: str):
            # 群益會分批回傳；累積所有片段
            state.products.append(value)
            preview = value if len(value) <= 120 else value[:120] + "..."
            print(f"[OnProducts] +{len(value)} chars: {preview}")

        def OnNotifyQuoteLONG(self, index: int):
            try:
                stock = sk.SKFOREIGNLONG()
                stock, code = oo_lib.SKOOQuoteLib_GetStockByIndexLONG(index, stock)
                if code != 0:
                    return
                # 用 ctypes _fields_ 列舉「全部」原生欄位（含 wrapper 沒解析的）
                raw = OrderedDict()
                for fname, _ftype in getattr(stock, "_fields_", []):
                    try:
                        raw[fname] = getattr(stock, fname)
                    except Exception as exc:  # noqa: BLE001
                        raw[fname] = f"<讀取失敗: {exc}>"
                symbol = str(raw.get("bstrStockNo", f"idx{index}"))
                now = time.time()
                if state.first_quote_ts is None:
                    state.first_quote_ts = now
                state.last_quote_ts = now
                state.quote_counts[symbol] = state.quote_counts.get(symbol, 0) + 1
                # 每個 symbol 留第一筆原生樣本即可
                if symbol not in state.quote_samples:
                    state.quote_samples[symbol] = raw
                    print(f"[Quote] {symbol}  ({len(raw)} 欄)")
            except Exception as exc:  # noqa: BLE001
                print(f"[OnNotifyQuoteLONG] 解析失敗: {exc}")

        def OnNotifyTicksLONG(self, *args):
            pass

        def OnNotifyBest5LONG(self, *args):
            pass

        def OnNotifyBest10LONG(self, *args):
            pass

    return OOQuoteSpikeEvent()


# --------------------------------------------------------------------------- #
# 輸出
# --------------------------------------------------------------------------- #
def _write_field_survey(state: _SpikeState, pump_name: str, args) -> Path:
    DOCS.mkdir(parents=True, exist_ok=True)
    out = DOCS / "overseas_options_field_survey.md"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = []
    lines.append("# 海外選擇權 欄位調查（Phase 0 spike 自動產出）")
    lines.append("")
    lines.append(f"> 產生時間：{ts}　訊息泵：{pump_name}　連線碼 OnConnect={state.connect_code}")
    lines.append(f"> 參數：--symbols={args.symbols!r} --seconds={args.seconds} "
                 f"--products-only={args.products_only}")
    lines.append("")

    # 1) 商品清單
    lines.append("## 1. 商品清單（OnProducts 原始字串）")
    lines.append("")
    if state.products:
        joined = "".join(state.products)
        lines.append(f"- 片段數：{len(state.products)}；合併總長：{len(joined)} chars")
        lines.append("")
        lines.append("```")
        lines.append(joined)
        lines.append("```")
    else:
        lines.append("_（未收到 OnProducts；確認已連線且盤中，或加長等待秒數）_")
    lines.append("")

    # 2) 報價原生欄位樣本
    lines.append("## 2. 報價原生欄位樣本（SKFOREIGNLONG._fields_ 全欄）")
    lines.append("")
    if state.quote_samples:
        lines.append(f"- 收到報價的 symbol 數：{len(state.quote_samples)}")
        # 更新頻率估計
        if state.first_quote_ts and state.last_quote_ts and state.last_quote_ts > state.first_quote_ts:
            span = state.last_quote_ts - state.first_quote_ts
            total = sum(state.quote_counts.values())
            lines.append(f"- 報價更新：{span:.1f}s 內共 {total} 筆 "
                         f"（約 {total / span:.2f} 筆/秒）→ 串流 flush 秒數參考")
        lines.append("")
        for symbol, raw in state.quote_samples.items():
            cnt = state.quote_counts.get(symbol, 0)
            lines.append(f"### `{symbol}`　（本次收到 {cnt} 筆）")
            lines.append("")
            lines.append("| 欄位 | 原始值 |")
            lines.append("|---|---|")
            for fname, val in raw.items():
                sval = str(val).replace("|", "\\|")
                lines.append(f"| `{fname}` | `{sval}` |")
            lines.append("")
    else:
        lines.append("_（未收到任何報價；非盤中或 symbol 未訂閱成功）_")
    lines.append("")

    # 3) 自動觀察 / 待人工確認
    lines.append("## 3. 待人工判讀（依上方 capture 填 symbol_format_spec.md）")
    lines.append("")
    lines.append("- [ ] symbol 字串如何拆？root / 到期年月 / 履約價 / Call·Put 位置與編碼")
    lines.append("- [ ] 是否有「到期日 / 合約日」原生欄位？（看 §2 是否出現 date 類欄位；")
    lines.append("      若只有到期年月 → LTD 需靠交易所行事曆 / contract_specs.ltd_rule 推）")
    lines.append("- [ ] 標的期貨代碼與選擇權 root 對應（Black-76 的 F）")
    lines.append("- [ ] `sDecimal` 與 `nStrikePrice`/各價格的 divisor 解碼是否正確（價格 = 整數 / 10^sDecimal）")
    lines.append("- [ ] `bstrMarketNo` / `bstrExchangeNo` / `bstrExchangeName` 值 → 對照 margin_root_xref / contract_specs")
    lines.append("- [ ] 單帳號訂閱檔數上限（逐步加訂閱量測）")
    lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _write_spec_scaffold() -> Path | None:
    DOCS.mkdir(parents=True, exist_ok=True)
    out = DOCS / "symbol_format_spec.md"
    if out.exists():
        return None  # 不覆蓋人工已填內容
    content = """# 海外選擇權 symbol 格式規格（人工依 field_survey capture 填寫）

> 來源：scripts/spike_overseas_options.py 的 docs/overseas_options_field_survey.md。
> 這份是 Phase 3 `symbol_parser.py` 的依據；**填妥並 PASS 才進 Phase 2+。**

## 1. symbol 拆解規則

| 區段 | 範例字元 | 含義 | 備註 |
|---|---|---|---|
| root | | 商品代碼 | 對照 margin_root_xref → contract_specs.root |
| 到期 | | 年月 / 合約月碼 | |
| 履約價 | | strike | 是否含 divisor？ |
| 買賣權 | | C / P | 編碼位置 |

範例：`<填一個實際 symbol> = <逐段標註>`

## 2. 到期日(LTD) 來源

- [ ] 群益是否回傳到期/合約日原生欄位？欄位名＝______
- [ ] 若否：用哪個規則推 LTD（交易所行事曆 / contract_specs.ltd_rule）？

## 3. 標的期貨對應（Black-76 的 F）

- 選擇權 root → 取哪個到期月期貨當 F：______

## 4. 訂閱 / 連線限制

- 單帳號訂閱檔數上限：______
- 報價更新頻率 → 建議 flush 秒數：______

## 5. PASS 判定

- [ ] symbol 可確定性拆解
- [ ] 選定 MVP 標的 root 已知且已對映 contract_specs
- [ ] 到期日來源已定
- [ ] flush 秒數有依據
"""
    out.write_text(content, encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="群益海外選擇權 Phase 0 探勘 spike")
    parser.add_argument("--symbols", default="",
                        help="要訂閱的海外選擇權 symbol，逗號分隔（留空＝只抓商品清單）")
    parser.add_argument("--seconds", type=int, default=30,
                        help="訂閱後接收報價的秒數（盤中）")
    parser.add_argument("--products-only", action="store_true",
                        help="只抓商品清單後結束（建議第一次跑）")
    parser.add_argument("--products-wait", type=int, default=8,
                        help="等待 OnProducts 的秒數")
    args = parser.parse_args()

    user_id = os.getenv("CAPITAL_USER_ID", "")
    password = os.getenv("CAPITAL_PASSWORD", "")
    if not user_id or not password:
        print("❌ 請在 .env 設定 CAPITAL_USER_ID / CAPITAL_PASSWORD")
        return 1

    pump, pump_name = _make_pump()
    print(f"訊息泵：{pump_name}")

    state = _SpikeState()
    client = CapitalClient()
    oo_lib = None
    handler = None
    try:
        masked = user_id[:2] + "*" * max(len(user_id) - 4, 0) + user_id[-2:]
        print(f"📡 登入中… ({masked})")
        client.login(user_id, password)
        print("✅ 登入成功")

        sk = get_sk_module()
        oo_lib = create_oo_quote_lib()
        event = _build_event_class(oo_lib, sk, client, state)
        handler = comtypes.client.GetEvents(oo_lib, event)

        print("📊 連線報價伺服器（EnterMonitorLONG）…")
        code = oo_lib.SKOOQuoteLib_EnterMonitorLONG()
        print(f"   EnterMonitorLONG rc={code}")
        pump(3)  # 等 OnConnect
        if state.connect_code is None:
            print("ℹ️  尚未收到 OnConnect（部分環境僅在訂閱後才回）；仍續試 RequestProducts")
        elif state.connect_code != 0:
            print(f"⚠️  OnConnect code={state.connect_code} 非成功碼，可能取不到商品檔/報價")

        print("📋 請求商品清單（RequestProducts）…")
        rc = oo_lib.SKOOQuoteLib_RequestProducts()
        print(f"   RequestProducts rc={rc}")
        pump(args.products_wait)

        if not args.products_only and args.symbols.strip():
            symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
            print(f"📈 訂閱 {len(symbols)} 檔：{symbols}")
            page = 0
            page, rc = oo_lib.SKOOQuoteLib_RequestStocks(page, ",".join(symbols))
            print(f"   RequestStocks rc={rc} page={page}")
            print(f"⏳ 接收報價 {args.seconds}s …")
            pump(args.seconds)
        elif not args.products_only:
            print("ℹ️  未給 --symbols，僅抓商品清單。看完 §1 後用 --symbols 再跑一次。")

        survey = _write_field_survey(state, pump_name, args)
        spec = _write_spec_scaffold()
        print(f"\n📝 已寫出：{survey}")
        if spec:
            print(f"📝 已建立 scaffold：{spec}")
        print("\n— 下一步：依 field_survey 填 symbol_format_spec.md；PASS 後才進 Phase 2+。")
        return 0

    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"\n❌ 錯誤：{exc}")
        traceback.print_exc()
        # 即使出錯也盡量把已收到的資料寫出
        try:
            _write_field_survey(state, pump_name, args)
        except Exception:
            pass
        return 1
    finally:
        try:
            if oo_lib is not None:
                oo_lib.SKOOQuoteLib_LeaveMonitor()
        except Exception:
            pass
        handler = None  # noqa: F841  釋放事件
        if client.is_logged_in:
            client.logout()
        print("📴 已結束。")


if __name__ == "__main__":
    raise SystemExit(main())
