"""
範例 05: 選擇權鏈顯示

訂閱多檔選擇權後，以選擇權鏈格式顯示

執行前請確認：
1. 已安裝群益 API 元件 (SKCOM.dll)
2. 已申請群益期貨帳號

使用方式：
    python 05_options_chain.py
"""

import logging
import time

# 設定 logging
logging.basicConfig(
    level=logging.WARNING,  # 減少輸出
    format="%(asctime)s [%(levelname)s] %(message)s"
)

from capitalapi import CapitalClient
from capitalapi.constants import Environment
from capitalapi.options_quote import OptionsQuoteManager
from capitalapi.options_chain import OptionQuote, OptionsChain


def print_chain(chain: OptionsChain):
    """顯示選擇權鏈"""
    print("\n" + "=" * 80)
    print(f"選擇權鏈: {chain.underlying}")
    if chain.underlying_price > 0:
        print(f"標的價格: {chain.underlying_price:.2f}")
    print("=" * 80)

    # 表頭
    header = (
        f"{'Call Bid':>10} {'Call Ask':>10} {'Call 成交':>10} | "
        f"{'履約價':^10} | "
        f"{'Put 成交':>10} {'Put Bid':>10} {'Put Ask':>10}"
    )
    print(header)
    print("-" * 80)

    # 資料列
    for strike in chain.get_sorted_strikes():
        option_strike = chain.strikes[strike]
        call = option_strike.call
        put = option_strike.put

        # Call 資料
        if call:
            call_bid = f"{call.bid_price:.2f}" if call.bid_price > 0 else "-"
            call_ask = f"{call.ask_price:.2f}" if call.ask_price > 0 else "-"
            call_close = f"{call.close_price:.2f}" if call.close_price > 0 else "-"
        else:
            call_bid = call_ask = call_close = "-"

        # Put 資料
        if put:
            put_bid = f"{put.bid_price:.2f}" if put.bid_price > 0 else "-"
            put_ask = f"{put.ask_price:.2f}" if put.ask_price > 0 else "-"
            put_close = f"{put.close_price:.2f}" if put.close_price > 0 else "-"
        else:
            put_bid = put_ask = put_close = "-"

        row = (
            f"{call_bid:>10} {call_ask:>10} {call_close:>10} | "
            f"{strike:^10.0f} | "
            f"{put_close:>10} {put_bid:>10} {put_ask:>10}"
        )
        print(row)

    print("=" * 80)
    print(f"共 {len(chain)} 個履約價\n")


def main():
    # 請替換成您的帳號密碼
    USER_ID = "YOUR_USER_ID"
    PASSWORD = "YOUR_PASSWORD"

    # 建立多檔選擇權訂閱清單
    # 這裡示範訂閱多個履約價的 Call 和 Put
    BASE_STRIKE = 22000
    EXPIRY = "4"  # 月份代碼
    STRIKES = [21500, 21750, 22000, 22250, 22500, 22750, 23000]

    OPTIONS = []
    for strike in STRIKES:
        OPTIONS.append(f"TXO{strike}C{EXPIRY}")  # Call
        OPTIONS.append(f"TXO{strike}P{EXPIRY}")  # Put

    client = CapitalClient(environment=Environment.TEST)
    options = None
    last_print_time = 0

    def on_quote(quote: OptionQuote):
        """報價回調 - 定期顯示選擇權鏈"""
        nonlocal last_print_time

        # 每 5 秒顯示一次選擇權鏈
        current_time = time.time()
        if current_time - last_print_time >= 5:
            chain = options.get_chain("TXO")
            if chain and len(chain) > 0:
                print_chain(chain)
            last_print_time = current_time

    try:
        # 登入
        print("登入中...")
        client.login(USER_ID, PASSWORD)
        print("登入成功!")

        # 建立選擇權報價管理器
        options = OptionsQuoteManager(client)
        options.on_quote = on_quote

        # 連線報價伺服器
        print("\n連線選擇權報價伺服器...")
        options.connect()

        # 訂閱選擇權
        print(f"\n訂閱 {len(OPTIONS)} 檔選擇權...")
        options.subscribe_many(OPTIONS)

        # 持續接收報價 (按 Ctrl+C 停止)
        print("等待報價中... (每 5 秒更新一次，按 Ctrl+C 停止)\n")

        import pythoncom
        while True:
            pythoncom.PumpWaitingMessages()
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n\n使用者中斷")

        # 最後顯示一次選擇權鏈
        if options:
            chain = options.get_chain("TXO")
            if chain and len(chain) > 0:
                print_chain(chain)

    except Exception as e:
        print(f"錯誤: {e}")
        import traceback
        traceback.print_exc()

    finally:
        if options:
            options.disconnect()
        client.logout()
        print("已登出")


if __name__ == "__main__":
    main()
