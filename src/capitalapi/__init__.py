"""
Capital API - 群益期貨 API Python 封裝

提供簡化的介面來操作群益期貨 API，包括：
- 登入/登出管理
- 即時報價訂閱 (股票、期貨、選擇權)
- 選擇權鏈資料結構
- 下單功能 (預留)

注意：此套件僅支援 Windows 平台，需要先安裝群益 API 元件 (SKCOM.dll)
"""

from .client import CapitalClient
from .quote import QuoteManager
from .order import OrderManager
from .options_quote import OptionsQuoteManager  # 海外選擇權
from .tw_options_quote import TwOptionsQuoteManager  # 台灣選擇權 (TXO)
from .options_chain import OptionQuote, OptionType, OptionStrike, OptionsChain
from .exceptions import (
    CapitalAPIError,
    LoginError,
    ConnectionError,
    OrderError,
    QuoteError,
)

__version__ = "0.1.0"
__all__ = [
    # 核心
    "CapitalClient",
    # 股票/期貨報價
    "QuoteManager",
    # 選擇權報價
    "OptionsQuoteManager",      # 海外選擇權
    "TwOptionsQuoteManager",    # 台灣選擇權 (TXO)
    "OptionQuote",
    "OptionType",
    "OptionStrike",
    "OptionsChain",
    # 下單 (預留)
    "OrderManager",
    # 例外
    "CapitalAPIError",
    "LoginError",
    "ConnectionError",
    "OrderError",
    "QuoteError",
]
