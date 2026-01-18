"""
SKCOM DLL 載入與初始化

此模組負責載入群益 API 的 COM 元件
"""

import os
import sys
from pathlib import Path
from typing import Any, Optional

# 檢查平台
if sys.platform != "win32":
    raise ImportError("Capital API 僅支援 Windows 平台")

import comtypes.client


# 全域變數：SKCOM 模組參照
_sk_module = None

# SKCOM.dll 預設搜尋路徑
_SKCOM_SEARCH_PATHS = [
    # 2.13.57 版本
    r"E:\CapitalFuturesAPI\CapitalAPI_2.13.57_PythonExample\元件\x64",
    # 2.13.52 版本
    r"E:\CapitalFuturesAPI\CapitalAPI_2.13.52_PythonExample\CapitalAPI_2.13.52_PythonExample\元件\x64",
    # 常見安裝路徑
    r"C:\Program Files\Capital\SKCOM",
    r"C:\Capital\x64",
]


def find_skcom_dll() -> Optional[Path]:
    """搜尋 SKCOM.dll 路徑"""
    for search_path in _SKCOM_SEARCH_PATHS:
        dll_path = Path(search_path) / "SKCOM.dll"
        if dll_path.exists():
            return dll_path
    return None


def _load_skcom():
    """載入 SKCOM.dll 並回傳模組"""
    global _sk_module
    if _sk_module is None:
        # 找到 DLL 路徑
        dll_path = find_skcom_dll()
        if dll_path is None:
            raise FileNotFoundError(
                "找不到 SKCOM.dll，請確認群益 API 已安裝並註冊。\n"
                f"搜尋路徑: {_SKCOM_SEARCH_PATHS}"
            )

        # 將 DLL 目錄加入 PATH (讓相依 DLL 也能載入)
        dll_dir = str(dll_path.parent)
        if dll_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")

        # 載入類型庫
        comtypes.client.GetModule(str(dll_path))
        import comtypes.gen.SKCOMLib as sk
        _sk_module = sk
    return _sk_module


def get_sk_module():
    """取得 SKCOMLib 模組"""
    return _load_skcom()


def create_center_lib() -> Any:
    """建立 SKCenterLib 物件"""
    sk = get_sk_module()
    return comtypes.client.CreateObject(
        sk.SKCenterLib,
        interface=sk.ISKCenterLib
    )


def create_quote_lib() -> Any:
    """建立 SKQuoteLib 物件"""
    sk = get_sk_module()
    return comtypes.client.CreateObject(
        sk.SKQuoteLib,
        interface=sk.ISKQuoteLib
    )


def create_order_lib() -> Any:
    """建立 SKOrderLib 物件"""
    sk = get_sk_module()
    return comtypes.client.CreateObject(
        sk.SKOrderLib,
        interface=sk.ISKOrderLib
    )


def create_reply_lib() -> Any:
    """建立 SKReplyLib 物件"""
    sk = get_sk_module()
    return comtypes.client.CreateObject(
        sk.SKReplyLib,
        interface=sk.ISKReplyLib
    )


def create_os_quote_lib() -> Any:
    """建立 SKOSQuoteLib 物件 (複委託報價)"""
    sk = get_sk_module()
    return comtypes.client.CreateObject(
        sk.SKOSQuoteLib,
        interface=sk.ISKOSQuoteLib
    )


def create_oo_quote_lib() -> Any:
    """建立 SKOOQuoteLib 物件 (海外期貨選擇權報價)"""
    sk = get_sk_module()
    return comtypes.client.CreateObject(
        sk.SKOOQuoteLib,
        interface=sk.ISKOOQuoteLib
    )
