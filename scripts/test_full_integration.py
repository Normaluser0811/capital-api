"""
Capital API 完整整合測試腳本

測試登入 → 報價 → 輸出格式化資料 (供 Dashboard 使用)
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime
from dataclasses import asdict

# 加入 src 路徑
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# 載入 .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from capitalapi import CapitalClient, OptionsQuoteManager
from capitalapi.options_chain import OptionQuote, OptionsChain, OptionType


def format_for_dashboard(chain: OptionsChain) -> dict:
    """
    將選擇權鏈格式化為 Dashboard 可用的格式

    Returns:
        dict: {strike: {"C": quote_dict, "P": quote_dict}}
    """
    result = {}

    for strike, option_strike in chain.strikes.items():
        result[strike] = {}

        if option_strike.call:
            call = option_strike.call
            result[strike]["C"] = {
                "symbol": call.symbol,
                "strike": call.strike_price,
                "bid": call.bid_price,
                "ask": call.ask_price,
                "last": call.close_price,
                "volume": getattr(call, 'volume', 0),
                "iv": getattr(call, 'iv', 0.2),
            }

        if option_strike.put:
            put = option_strike.put
            result[strike]["P"] = {
                "symbol": put.symbol,
                "strike": put.strike_price,
                "bid": put.bid_price,
                "ask": put.ask_price,
                "last": put.close_price,
                "volume": getattr(put, 'volume', 0),
                "iv": getattr(put, 'iv', 0.2),
            }

    return result


def run_integration_test():
    """執行整合測試"""
    print("=" * 70)
    print("Capital API 完整整合測試")
    print("=" * 70)

    # 從環境變數讀取帳密
    USER_ID = os.getenv("CAPITAL_USER_ID", "")
    PASSWORD = os.getenv("CAPITAL_PASSWORD", "")
    OUTPUT_FILE = Path(__file__).parent / "options_data.json"

    if not USER_ID or not PASSWORD:
        print("\n⚠️  請在 .env 檔案填入帳號密碼!")
        return False

    client = CapitalClient()
    options = None

    try:
        # Step 1: 登入
        print("\n[Step 1/5] 登入")
        print("-" * 70)
        masked_id = USER_ID[:3] + "*" * (len(USER_ID) - 6) + USER_ID[-3:]
        print(f"   帳號: {masked_id}")
        client.login(USER_ID, PASSWORD)
        print("✅ 登入成功")

        time.sleep(1)

        # Step 2: 建立報價連線
        print("\n[Step 2/5] 建立報價連線")
        print("-" * 70)
        options = OptionsQuoteManager(client)
        options.connect()
        print("✅ 報價連線成功")

        time.sleep(1)

        # Step 3: 訂閱選擇權
        print("\n[Step 3/5] 訂閱選擇權")
        print("-" * 70)

        # 假設目前指數約 23000，訂閱上下 500 點
        atm_strike = 23000
        strike_range = range(atm_strike - 500, atm_strike + 600, 100)

        subscribed = 0
        for strike in strike_range:
            options.subscribe(f"TXO{strike}C")
            options.subscribe(f"TXO{strike}P")
            subscribed += 2

        print(f"✅ 已訂閱 {subscribed} 檔選擇權 ({len(list(strike_range))} 個履約價)")

        # Step 4: 等待並收集報價
        print("\n[Step 4/5] 收集報價資料")
        print("-" * 70)

        wait_seconds = 15
        print(f"⏳ 等待 {wait_seconds} 秒收集報價...")

        for i in range(wait_seconds):
            time.sleep(1)
            sys.stdout.write(f"\r   進度: {i+1}/{wait_seconds} 秒")
            sys.stdout.flush()
        print()

        # 取得選擇權鏈
        chain = options.get_chain("TXO")

        if chain and chain.strikes:
            print(f"✅ 取得 {len(chain.strikes)} 個履約價")

            # 顯示選擇權鏈
            print("\n選擇權鏈報價:")
            print("-" * 70)
            print(f"{'履約價':>8} │ {'Call Bid':>9} {'Call Ask':>9} │ "
                  f"{'Put Bid':>9} {'Put Ask':>9}")
            print("-" * 70)

            for strike in chain.get_sorted_strikes():
                os = chain.strikes[strike]
                c = os.call
                p = os.put

                cb = f"{c.bid_price:.1f}" if c else "-"
                ca = f"{c.ask_price:.1f}" if c else "-"
                pb = f"{p.bid_price:.1f}" if p else "-"
                pa = f"{p.ask_price:.1f}" if p else "-"

                # 標記 ATM
                atm_marker = " ◀" if strike == chain.get_atm_strike(atm_strike) else ""
                print(f"{strike:>8.0f} │ {cb:>9} {ca:>9} │ {pb:>9} {pa:>9}{atm_marker}")

            print("-" * 70)

            # Step 5: 輸出 JSON
            print("\n[Step 5/5] 輸出資料")
            print("-" * 70)

            dashboard_data = format_for_dashboard(chain)

            output = {
                "timestamp": datetime.now().isoformat(),
                "underlying": "TXO",
                "atm_strike": atm_strike,
                "chain": dashboard_data,
            }

            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            print(f"✅ 已輸出至: {OUTPUT_FILE}")
            print(f"   資料筆數: {len(dashboard_data)} 個履約價")

        else:
            print("⚠️  未取得報價資料 (可能非盤中時間)")

        return True

    except Exception as e:
        print(f"\n❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # 清理連線
        if options:
            try:
                options.disconnect()
            except:
                pass

        if client.is_logged_in:
            client.logout()
            print("\n📴 已登出")


if __name__ == "__main__":
    print(f"\n執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    success = run_integration_test()

    print("\n" + "=" * 70)
    print(f"整合測試結果: {'✅ 通過' if success else '❌ 失敗'}")
    print("=" * 70)
