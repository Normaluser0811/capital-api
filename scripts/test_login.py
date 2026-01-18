"""
Capital API 登入測試腳本

測試與群益期貨伺服器的連線和登入功能
"""

import os
import sys
import time
from pathlib import Path

# 加入 src 路徑
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# 載入 .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from capitalapi import CapitalClient
from capitalapi.exceptions import LoginError, ConnectionError


def test_login():
    """測試登入功能"""
    print("=" * 50)
    print("Capital API 登入測試")
    print("=" * 50)

    # 從環境變數讀取帳密
    USER_ID = os.getenv("CAPITAL_USER_ID", "")
    PASSWORD = os.getenv("CAPITAL_PASSWORD", "")

    if not USER_ID or not PASSWORD:
        print("\n⚠️  請在 .env 檔案填入帳號密碼!")
        print("   CAPITAL_USER_ID=你的身分證字號")
        print("   CAPITAL_PASSWORD=你的密碼")
        return False

    # 建立 client
    client = CapitalClient()

    try:
        # 隱藏部分帳號 (只顯示前3後3)
        masked_id = USER_ID[:3] + "*" * (len(USER_ID) - 6) + USER_ID[-3:]
        print(f"\n📡 正在連線...")
        print(f"   帳號: {masked_id}")

        # 執行登入
        result = client.login(USER_ID, PASSWORD)

        if result:
            print("\n✅ 登入成功!")
            print(f"   登入狀態: {client.is_logged_in}")

            # 等待一下讓連線穩定
            time.sleep(2)

            # 登出
            print("\n📴 正在登出...")
            client.logout()
            print("✅ 登出成功!")

            return True
        else:
            print("\n❌ 登入失敗!")
            return False

    except LoginError as e:
        print(f"\n❌ 登入錯誤: {e}")
        return False
    except ConnectionError as e:
        print(f"\n❌ 連線錯誤: {e}")
        return False
    except Exception as e:
        print(f"\n❌ 未預期錯誤: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_login()
    print("\n" + "=" * 50)
    print(f"測試結果: {'通過' if success else '失敗'}")
    print("=" * 50)
