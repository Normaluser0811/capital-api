"""
範例 04: 選擇權報價

取得選擇權即時報價，包含履約價、買賣價、成交價等

執行前請確認：
1. 已安裝群益 API 元件 (SKCOM.dll)
2. 已申請群益期貨帳號
3. 帳號有選擇權報價權限

使用方式：
    python 04_options_quote.py
"""

import logging
import time

# 設定 logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from capitalapi import CapitalClient
from capitalapi.constants import Environment
from capitalapi.options_quote import OptionsQuoteManager
from capitalapi.options_chain import OptionQuote, OptionType


def on_quote(quote: OptionQuote):
    """報價回調"""
    type_str = "Call" if quote.is_call() else "Put"
    print(
        f"[{type_str}] {quote.symbol} "
        f"履約價={quote.strike_price:.0f} "
        f"成交={quote.close_price:.2f} "
        f"Bid={quote.bid_price:.2f}({quote.bid_qty}) "
        f"Ask={quote.ask_price:.2f}({quote.ask_qty}) "
        f"量={quote.volume}"
    )


def on_products(value: str):
    """商品清單回調"""
    print(f"[商品] {value}")


def main():
    # 請替換成您的帳號密碼
    USER_ID = "YOUR_USER_ID"
    PASSWORD = "YOUR_PASSWORD"

    # 要訂閱的選擇權 (格式需確認群益 API 文件)
    # 範例: 台指選擇權
    OPTIONS = [
        "TXO22000C4",  # 台指選 22000 Call 4月
        "TXO22000P4",  # 台指選 22000 Put 4月
        "TXO22500C4",  # 台指選 22500 Call 4月
        "TXO22500P4",  # 台指選 22500 Put 4月
    ]

    client = CapitalClient(environment=Environment.TEST)

    try:
        # 登入
        print("登入中...")
        client.login(USER_ID, PASSWORD)
        print("登入成功!")

        # 建立選擇權報價管理器
        options = OptionsQuoteManager(client)
        options.on_quote = on_quote
        options.on_products = on_products

        # 連線報價伺服器
        print("\n連線選擇權報價伺服器...")
        options.connect()

        # 取得商品清單 (可選)
        # options.get_products()

        # 訂閱選擇權
        print(f"\n訂閱選擇權: {OPTIONS}")
        options.subscribe_many(OPTIONS)

        # 持續接收報價 (按 Ctrl+C 停止)
        print("\n開始接收報價 (按 Ctrl+C 停止)...\n")

        import pythoncom
        while True:
            # Windows COM 需要 pump messages
            pythoncom.PumpWaitingMessages()
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n\n使用者中斷")

    except Exception as e:
        print(f"錯誤: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # 清理
        if 'options' in dir():
            options.disconnect()
        client.logout()
        print("已登出")


if __name__ == "__main__":
    main()
