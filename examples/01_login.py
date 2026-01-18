"""
範例 01: 登入測試

執行前請確認：
1. 已安裝群益 API 元件 (SKCOM.dll)
2. 已申請群益期貨帳號

使用方式：
    python 01_login.py
"""

import logging

# 設定 logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from capitalapi import CapitalClient
from capitalapi.constants import Environment


def main():
    # 請替換成您的帳號密碼
    USER_ID = "YOUR_USER_ID"
    PASSWORD = "YOUR_PASSWORD"

    # 建立客戶端 (使用測試環境)
    # 正式環境請改為 Environment.PRODUCTION
    client = CapitalClient(environment=Environment.TEST)

    print(f"API 版本: {client.get_api_version()}")

    try:
        # 登入
        print(f"\n嘗試登入: {USER_ID}")
        client.login(USER_ID, PASSWORD)

        print(f"登入成功!")
        print(f"已登入: {client.is_logged_in}")
        print(f"使用者: {client.user_id}")

        # 顯示帳號
        print(f"\n交易帳號:")
        for acc in client.accounts:
            print(f"  - {acc.full_account} ({acc.account_type})")

    except Exception as e:
        print(f"錯誤: {e}")

    finally:
        # 登出
        client.logout()
        print("\n已登出")


if __name__ == "__main__":
    main()
