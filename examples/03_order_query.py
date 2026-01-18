"""
範例 03: 查詢委託與成交回報

執行前請確認：
1. 已安裝群益 API 元件 (SKCOM.dll)
2. 已申請群益期貨帳號
3. 已讀取憑證

使用方式：
    python 03_order_query.py
"""

import logging

# 設定 logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from capitalapi import CapitalClient, OrderManager
from capitalapi.constants import Environment, MarketType, OrderReportType


def main():
    # 請替換成您的帳號密碼
    USER_ID = "YOUR_USER_ID"
    PASSWORD = "YOUR_PASSWORD"

    client = CapitalClient(environment=Environment.TEST)

    try:
        # 登入
        print("登入中...")
        client.login(USER_ID, PASSWORD)
        print("登入成功!")

        # 顯示帳號
        print(f"\n交易帳號:")
        for acc in client.accounts:
            print(f"  - {acc.full_account} ({acc.account_type})")

        # 讀取憑證
        print("\n讀取憑證...")
        if client.read_certificate():
            print("憑證讀取成功")
        else:
            print("憑證讀取失敗，部分功能可能無法使用")

        # 建立下單管理器
        order = OrderManager(client)

        # 解鎖下單 (查詢也需要)
        print("\n解鎖下單功能...")
        order.unlock(MarketType.TS)

        # 查詢委託回報
        print("\n查詢委託回報 (全部):")
        report = order.get_order_report(report_type=OrderReportType.ALL)
        print(report if report else "  (無資料)")

        # 查詢成交回報
        print("\n查詢成交回報 (全部):")
        report = order.get_fulfill_report()
        print(report if report else "  (無資料)")

    except Exception as e:
        print(f"錯誤: {e}")

    finally:
        client.logout()
        print("\n已登出")


if __name__ == "__main__":
    main()
