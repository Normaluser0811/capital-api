"""
Capital API 常數定義
"""

from enum import IntEnum


class Environment(IntEnum):
    """連線環境"""
    PRODUCTION = 0       # 正式環境
    PRODUCTION_SGX = 1   # 正式環境 SGX
    TEST = 2             # 測試環境
    TEST_SGX = 3         # 測試環境 SGX


class MarketType(IntEnum):
    """市場類型"""
    TS = 0   # 台股證券
    TF = 1   # 台灣期貨
    TO = 2   # 台灣選擇權
    OS = 3   # 複委託
    OF = 4   # 海外期貨
    OO = 5   # 海外選擇權


class MarketNo(IntEnum):
    """市場別代號"""
    TSE = 0   # 上市
    OTC = 1   # 上櫃


class OrderReportType(IntEnum):
    """委託回報查詢類型"""
    ALL = 1              # 全部
    VALID = 2            # 有效
    CANCELLABLE = 3      # 可消
    CANCELLED = 4        # 已消
    FILLED = 5           # 已成
    FAILED = 6           # 失敗
    MERGED_PRICE = 7     # 合併同價格
    MERGED_PRODUCT = 8   # 合併同商品
    RESERVED = 9         # 預約


class FulfillReportType(IntEnum):
    """成交回報查詢類型"""
    ALL = 1              # 全部
    MERGED_SEQNO = 2     # 合併同書號
    MERGED_PRICE = 3     # 合併同價格
    MERGED_PRODUCT = 4   # 合併同商品
    T_PLUS_ONE = 5       # T+1成交回報


# 連線狀態代碼
CONNECTION_STATUS = {
    3001: "連線中",
    3002: "連線成功",
    3003: "連線失敗",
    3021: "斷線",
}
