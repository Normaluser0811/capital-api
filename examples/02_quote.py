"""
範例 02: 即時報價

執行前請確認：
1. 已安裝群益 API 元件 (SKCOM.dll)
2. 已申請群益期貨帳號

使用方式：
    python 02_quote.py
"""

import logging
import time

# 設定 logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from capitalapi import CapitalClient, QuoteManager
from capitalapi.constants import Environment, MarketNo
from capitalapi.quote import StockQuote


def on_quote(quote: StockQuote):
    """報價回調"""
    print(
        f"[報價] {quote.stock_no} {quote.stock_name}: "
        f"開={quote.open_price:.2f} "
        f"高={quote.high_price:.2f} "
        f"低={quote.low_price:.2f} "
        f"收={quote.close_price:.2f} "
        f"量={quote.total_qty}"
    )


def main():
    # 請替換成您的帳號密碼
    USER_ID = "YOUR_USER_ID"
    PASSWORD = "YOUR_PASSWORD"

    # 要訂閱的股票
    STOCKS = ["2330", "2317", "2454"]  # 台積電、鴻海、聯發科

    client = CapitalClient(environment=Environment.TEST)

    try:
        # 登入
        print("登入中...")
        client.login(USER_ID, PASSWORD)
        print("登入成功!")

        # 建立報價管理器
        quote = QuoteManager(client)
        quote.on_quote = on_quote

        # 連線報價伺服器
        print("\n連線報價伺服器...")
        quote.connect()

        # 訂閱股票
        print(f"\n訂閱股票: {STOCKS}")
        quote.subscribe_many(STOCKS, MarketNo.TSE)

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

    finally:
        # 清理
        if 'quote' in dir():
            quote.disconnect()
        client.logout()
        print("已登出")


if __name__ == "__main__":
    main()
