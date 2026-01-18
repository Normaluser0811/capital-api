"""
Capital API 台灣選擇權報價測試腳本

測試取得台指選擇權 (TXO) 即時報價
使用 TwOptionsQuoteManager (SKQuoteLib)
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime

import pythoncom

# 設定輸出編碼
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# 加入 src 路徑
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# 載入 .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from capitalapi import CapitalClient, TwOptionsQuoteManager, OptionQuote


def on_quote_received(quote: OptionQuote):
    """報價回調函數"""
    opt_type = "Call" if quote.option_type.value == "C" else "Put"
    print(f"  📈 {quote.symbol}: {opt_type} "
          f"履約價={quote.strike_price:.0f} "
          f"Bid={quote.bid_price:.1f} "
          f"Ask={quote.ask_price:.1f} "
          f"Last={quote.close_price:.1f}")


def test_options_quote():
    """測試選擇權報價"""
    print("=" * 60)
    print("Capital API 台灣選擇權報價測試 (TXO)")
    print("=" * 60)

    # 檢查是否盤中
    now = datetime.now()
    market_open = now.replace(hour=8, minute=45, second=0)
    market_close = now.replace(hour=13, minute=45, second=0)
    is_market_hours = market_open <= now <= market_close

    if not is_market_hours:
        print(f"\n⚠️  目前非盤中時間 ({now.strftime('%H:%M')})")
        print("   盤中時間: 08:45 - 13:45")
        print("   非盤中可能無法取得即時報價\n")

    # 從環境變數讀取帳密
    USER_ID = os.getenv("CAPITAL_USER_ID", "")
    PASSWORD = os.getenv("CAPITAL_PASSWORD", "")

    if not USER_ID or not PASSWORD:
        print("\n⚠️  請在 .env 檔案填入帳號密碼!")
        return False

    client = CapitalClient()

    try:
        # 隱藏部分帳號
        masked_id = USER_ID[:3] + "*" * (len(USER_ID) - 6) + USER_ID[-3:]
        print(f"\n📡 正在登入... ({masked_id})")
        client.login(USER_ID, PASSWORD)
        print("✅ 登入成功!")

        time.sleep(1)

        # 建立台灣選擇權報價管理器
        print("\n📊 建立選擇權報價連線...")
        options = TwOptionsQuoteManager(client)
        options.on_quote = on_quote_received

        # 連線報價伺服器
        options.connect()
        print("✅ 報價連線發起成功!")

        # 等待連線完成 (需要處理 COM 事件)
        print("   等待連線完成...")
        for _ in range(30):  # 最多等待 3 秒
            pythoncom.PumpWaitingMessages()
            time.sleep(0.1)
        print("✅ 報價連線完成!")

        # 訂閱台指選擇權
        print("\n📈 訂閱台指選擇權 (TXO)...")

        # TXO 商品代碼格式: TXO{履約價}{月份代碼}{年份末碼}
        # Call 月份代碼: A-L (1-12月)
        # Put 月份代碼: M-X (1-12月)
        # 年份末碼: 2026 → 6
        # 例如: TXO23000A6 = 23000 Call 2026年1月
        #       TXO23000M6 = 23000 Put 2026年1月

        # 取得目前月份和年份
        current_month = now.month
        year_code = now.year % 10  # 取年份最後一位 (2026 → 6)
        call_month = chr(ord('A') + current_month - 1)  # A=1月, B=2月...
        put_month = chr(ord('M') + current_month - 1)   # M=1月, N=2月...

        # 訂閱價平附近的選擇權
        atm_strike = 23000  # 假設目前指數約 23000
        strikes = [atm_strike - 200, atm_strike - 100, atm_strike,
                   atm_strike + 100, atm_strike + 200]

        print(f"   月份代碼: Call={call_month}{year_code}, Put={put_month}{year_code}")

        subscribed = 0
        for strike in strikes:
            # 訂閱 Call (月選)
            call_symbol = f"TXO{strike}{call_month}{year_code}"
            if options.subscribe(call_symbol):
                subscribed += 1

            # 訂閱 Put (月選)
            put_symbol = f"TXO{strike}{put_month}{year_code}"
            if options.subscribe(put_symbol):
                subscribed += 1

        print(f"   已訂閱 {len(strikes) * 2} 檔選擇權")

        # 等待接收報價 (需要持續處理 COM 事件)
        print("\n⏳ 等待報價資料 (10 秒)...")
        print("-" * 60)

        for i in range(10):
            # 每秒處理 10 次 COM 訊息
            for _ in range(10):
                pythoncom.PumpWaitingMessages()
                time.sleep(0.1)
            print(f"   {i+1}/10 秒...")

        print("-" * 60)

        # 取得選擇權鏈 (透過即時報價回調)
        print("\n📋 取得選擇權鏈 (即時報價)...")
        chain = options.get_chain("TXO")

        if chain and chain.strikes:
            print(f"✅ 取得 {len(chain.strikes)} 個履約價 (即時)")
        else:
            print("⚠️  未收到即時報價 (可能非盤中)")

        # 嘗試主動查詢報價 (非盤中也可取得收盤資料)
        print("\n📋 主動查詢報價 (get_quote)...")
        print("-" * 60)
        print(f"{'履約價':>10} | {'Call Bid':>10} {'Call Ask':>10} {'Call Last':>10} | "
              f"{'Put Bid':>10} {'Put Ask':>10} {'Put Last':>10}")
        print("-" * 60)

        queried_count = 0
        for strike in strikes:
            call_symbol = f"TXO{strike}{call_month}{year_code}"
            put_symbol = f"TXO{strike}{put_month}{year_code}"

            # 主動查詢報價
            call = options.get_quote(call_symbol)
            put = options.get_quote(put_symbol)

            if call or put:
                queried_count += 1

            call_bid = f"{call.bid_price:.1f}" if call else "-"
            call_ask = f"{call.ask_price:.1f}" if call else "-"
            call_last = f"{call.close_price:.1f}" if call else "-"
            put_bid = f"{put.bid_price:.1f}" if put else "-"
            put_ask = f"{put.ask_price:.1f}" if put else "-"
            put_last = f"{put.close_price:.1f}" if put else "-"

            print(f"{strike:>10.0f} | {call_bid:>10} {call_ask:>10} {call_last:>10} | "
                  f"{put_bid:>10} {put_ask:>10} {put_last:>10}")

        print("-" * 60)
        if queried_count > 0:
            print(f"✅ 成功查詢 {queried_count} 個履約價的報價")
        else:
            print("⚠️  未能查詢到報價資料")

        # 斷開連線
        print("\n📴 斷開報價連線...")
        options.disconnect()

        # 登出
        client.logout()
        print("✅ 測試完成!")

        return True

    except Exception as e:
        print(f"\n❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        if client.is_logged_in:
            client.logout()


if __name__ == "__main__":
    success = test_options_quote()
    print("\n" + "=" * 60)
    print(f"測試結果: {'通過' if success else '失敗'}")
    print("=" * 60)
