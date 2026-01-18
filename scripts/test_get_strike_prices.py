"""
測試取得選擇權履約價清單
"""

import os
import sys
import time
from pathlib import Path

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

import comtypes.client
from capitalapi import CapitalClient
from capitalapi.skcom import create_quote_lib, get_sk_module

# 全域變數儲存回調結果
strike_prices_data = []


def test_get_strike_prices():
    """測試取得選擇權履約價清單"""
    print("=" * 60)
    print("測試取得選擇權履約價清單")
    print("=" * 60)

    USER_ID = os.getenv("CAPITAL_USER_ID", "")
    PASSWORD = os.getenv("CAPITAL_PASSWORD", "")

    if not USER_ID or not PASSWORD:
        print("\n⚠️  請在 .env 檔案填入帳號密碼!")
        return False

    client = CapitalClient()

    try:
        # 登入
        masked_id = USER_ID[:3] + "*" * (len(USER_ID) - 6) + USER_ID[-3:]
        print(f"\n📡 正在登入... ({masked_id})")
        client.login(USER_ID, PASSWORD)
        print("✅ 登入成功!")

        time.sleep(1)

        # 建立報價元件
        print("\n📊 建立報價連線...")
        quote = create_quote_lib()

        # 設定事件處理
        class QuoteLibEvent:
            def OnConnection(self, nKind, nCode):
                msg = client.get_return_message(nCode)
                print(f"   連線事件: kind={nKind}, code={nCode}, msg={msg}")

            def OnNotifyStrikePrices(self, bstrOptionData):
                """選擇權履約價回調"""
                print(f"\n📋 收到選擇權資料:")
                # 資料格式通常是用逗號或換行分隔
                strike_prices_data.append(bstrOptionData)

                # 只顯示前 500 字元
                if len(bstrOptionData) > 500:
                    print(f"   {bstrOptionData[:500]}...")
                    print(f"   (共 {len(bstrOptionData)} 字元)")
                else:
                    print(f"   {bstrOptionData}")

        event = QuoteLibEvent()
        handler = comtypes.client.GetEvents(quote, event)

        # 連線
        code = quote.SKQuoteLib_EnterMonitorLONG()
        if code != 0:
            print(f"❌ 連線失敗: {client.get_return_message(code)}")
            return False
        print("✅ 報價連線成功!")

        # 等待連線完成
        print("   等待連線穩定...")
        for _ in range(30):
            pythoncom.PumpWaitingMessages()
            time.sleep(0.1)

        # 取得選擇權履約價
        print("\n📈 請求選擇權履約價清單...")
        code = quote.SKQuoteLib_GetStrikePrices()
        if code != 0:
            print(f"❌ 請求失敗: {client.get_return_message(code)}")
        else:
            print("✅ 請求已發送")

        # 等待回調
        print("\n⏳ 等待回調資料 (10 秒)...")
        for i in range(100):
            pythoncom.PumpWaitingMessages()
            time.sleep(0.1)
            if (i + 1) % 10 == 0:
                print(f"   {(i+1)//10}/10 秒...")

        # 顯示結果
        if strike_prices_data:
            print(f"\n✅ 收到 {len(strike_prices_data)} 筆資料")
        else:
            print("\n⚠️  未收到選擇權資料")

        # 斷開連線
        quote.SKQuoteLib_LeaveMonitor()
        client.logout()
        print("\n📴 已登出")

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
    test_get_strike_prices()
