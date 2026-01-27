"""
台灣選擇權報價管理模組

使用 SKQuoteLib 取得台指選擇權 (TXO) 報價
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

import comtypes.client

from .client import CapitalClient
from .exceptions import QuoteError, CapitalAPIError
from .options_chain import OptionQuote, OptionType, OptionsChain
from .skcom import create_quote_lib, get_sk_module

logger = logging.getLogger(__name__)


# 市場別代號
MARKET_STOCK = 0      # 上市
MARKET_OTC = 1        # 上櫃
MARKET_FUTURES = 2    # 期貨
MARKET_OPTIONS = 3    # 選擇權
MARKET_EMERGING = 4   # 興櫃


@dataclass
class TwOptionsQuoteManager:
    """
    台灣選擇權報價管理器

    使用 SKQuoteLib 取得台指選擇權 (TXO) 報價

    使用方式:
        client = CapitalClient()
        client.login(...)

        options = TwOptionsQuoteManager(client)
        options.connect()  # 會自動請求選擇權商品清單

        # 訂閱選擇權
        options.subscribe("TXO23000A6")  # TXO 23000 Call 1月 2026年

    商品代碼格式 (共10碼):
        {商品代碼}{5位履約價}{月份代碼}{年份尾碼}
        - 商品代碼: TXO (月選), TX1/TX2/TX4/TX5 (週三週選), TXU/TXV/TXX/TXY/TXZ (週五週選)
        - 履約價: 5位數字 (不足補零)
        - 月份代碼: A-L (Call 1-12月), M-X (Put 1-12月)
        - 年份尾碼: 西元年最後一位數字

        例如:
        - TXO23000A6 = 月選 23000 Call 1月 2026年
        - TXO23000M6 = 月選 23000 Put 1月 2026年
        - TX423000V8 = 週選(第4週) 23000 Put 10月 2028年
    """
    client: CapitalClient

    # 內部狀態
    _quote: object = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)
    _subscribed: set[str] = field(default_factory=set, init=False, repr=False)
    _page_no: int = field(default=1, init=False, repr=False)

    # 選擇權鏈快取
    _chains: Dict[str, OptionsChain] = field(default_factory=dict, init=False, repr=False)

    # 報價回調
    on_quote: Callable[[OptionQuote], None] | None = field(
        default=None, init=False, repr=False
    )
    on_connection: Callable[[int, int], None] | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self):
        """初始化報價元件"""
        self._quote = create_quote_lib()
        self._setup_events()

    def _setup_events(self):
        """設定事件處理器"""
        manager = self
        sk = get_sk_module()

        class QuoteLibEvent:
            def OnConnection(self, nKind: int, nCode: int):
                """連線狀態回調"""
                msg = manager.client.get_return_message(nCode)
                logger.info(f"報價連線: kind={nKind}, code={nCode}, msg={msg}")
                if manager.on_connection:
                    manager.on_connection(nKind, nCode)

            def OnNotifyQuoteLONG(self, sMarketNo: int, nIndex: int):
                """收到報價通知"""
                # 只處理選擇權市場
                if sMarketNo != MARKET_OPTIONS:
                    return

                try:
                    stock = sk.SKSTOCKLONG()
                    stock, code = manager._quote.SKQuoteLib_GetStockByIndexLONG(
                        sMarketNo, nIndex, stock
                    )

                    if code != 0:
                        return

                    # 解析選擇權類型 (從商品代號判斷)
                    symbol = stock.bstrStockNo
                    option_type = manager._parse_option_type(symbol)

                    # 價格需要除以 100 (API 傳回的是乘以 100 的整數)
                    divisor = 100.0

                    quote = OptionQuote(
                        symbol=symbol,
                        name=stock.bstrStockName,
                        option_type=option_type,
                        strike_price=manager._parse_strike_price(symbol),
                        decimal_places=2,
                        # 價格
                        close_price=stock.nClose / divisor,
                        open_price=stock.nOpen / divisor,
                        high_price=stock.nHigh / divisor,
                        low_price=stock.nLow / divisor,
                        ref_price=stock.nRef / divisor,
                        # 買賣報價
                        bid_price=stock.nBid / divisor,
                        bid_qty=stock.nBc,
                        ask_price=stock.nAsk / divisor,
                        ask_qty=stock.nAc,
                        # 成交
                        volume=stock.nTQty,
                    )

                    # 更新選擇權鏈快取
                    manager._update_chain(quote)

                    if manager.on_quote:
                        manager.on_quote(quote)

                except Exception as e:
                    logger.error(f"處理選擇權報價時發生錯誤: {e}")

        self._quote_event = QuoteLibEvent()
        self._quote_handler = comtypes.client.GetEvents(
            self._quote, self._quote_event
        )

    def _parse_option_type(self, symbol: str) -> OptionType:
        """從商品代號解析選擇權類型"""
        # TXO 代碼格式: TXO{履約價}{月份代碼}{週別}
        # Call 月份代碼: A-L (1-12月)
        # Put 月份代碼: M-X (1-12月)
        if len(symbol) < 4:
            return OptionType.CALL

        # 找到月份代碼 (履約價後的第一個字母)
        for i, c in enumerate(symbol[3:], 3):
            if c.isalpha():
                month_code = c.upper()
                # A-L = Call, M-X = Put
                if month_code in "ABCDEFGHIJKL":
                    return OptionType.CALL
                elif month_code in "MNOPQRSTUVWX":
                    return OptionType.PUT
                break

        return OptionType.CALL

    def _parse_strike_price(self, symbol: str) -> float:
        """從商品代號解析履約價"""
        # TXO19000L4 -> 19000
        if not symbol.startswith("TXO"):
            return 0.0

        strike_str = ""
        for c in symbol[3:]:
            if c.isdigit():
                strike_str += c
            else:
                break

        return float(strike_str) if strike_str else 0.0

    def _update_chain(self, quote: OptionQuote):
        """更新選擇權鏈快取"""
        underlying = "TXO"

        if underlying not in self._chains:
            self._chains[underlying] = OptionsChain(underlying=underlying)

        self._chains[underlying].add_quote(quote)

    def connect(self) -> bool:
        """
        連線到報價伺服器

        Note:
            連線後需要等待 OnConnection 事件，確認連線成功後再呼叫
            request_stock_list() 和 get_strike_prices()

        Returns:
            bool: 是否成功發起連線
        """
        if not self.client.is_logged_in:
            raise CapitalAPIError("請先登入")

        # SKQuoteLib_EnterMonitorLONG 不需要參數
        code = self._quote.SKQuoteLib_EnterMonitorLONG()
        if code == 0:
            self._connected = True
            logger.info("報價連線發起成功")
            return True
        else:
            message = self.client.get_return_message(code)
            logger.error(f"報價連線失敗: {message}")
            raise QuoteError(message, code)

    def disconnect(self):
        """中斷報價連線"""
        if self._connected:
            self._quote.SKQuoteLib_LeaveMonitor()
            self._connected = False
            self._subscribed.clear()
            self._chains.clear()
            logger.info("報價連線已中斷")

    def request_stock_list(self, market_no: int = MARKET_OPTIONS) -> bool:
        """
        請求指定市場的商品清單 (必須在訂閱報價前呼叫)

        Args:
            market_no: 市場別代號 (預設 3=選擇權)
                      0=上市, 1=上櫃, 2=期貨, 3=選擇權, 4=興櫃

        Returns:
            bool: 是否成功
        """
        if not self._connected:
            raise CapitalAPIError("請先連線到報價伺服器")

        code = self._quote.SKQuoteLib_RequestStockList(market_no)
        if code == 0:
            logger.info(f"請求市場 {market_no} 商品清單成功")
            return True
        else:
            message = self.client.get_return_message(code)
            logger.error(f"請求市場 {market_no} 商品清單失敗: {message}")
            return False

    def get_strike_prices(self) -> bool:
        """
        取得選擇權履約價清單

        Returns:
            bool: 是否成功
        """
        if not self._connected:
            raise CapitalAPIError("請先連線到報價伺服器")

        code = self._quote.SKQuoteLib_GetStrikePrices()
        if code == 0:
            logger.info("請求選擇權履約價清單")
            return True
        else:
            message = self.client.get_return_message(code)
            logger.error(f"取得選擇權履約價清單失敗: {message}")
            return False

    def subscribe(self, symbol: str) -> bool:
        """
        訂閱選擇權報價

        Args:
            symbol: 商品代號 (如 "TXO19000L4")

        Returns:
            bool: 是否成功
        """
        if not self._connected:
            raise CapitalAPIError("請先連線到報價伺服器")

        # SKQuoteLib_RequestStocks(pageNo, stockNos)
        self._page_no, code = self._quote.SKQuoteLib_RequestStocks(
            self._page_no, symbol
        )

        if code == 0:
            self._subscribed.add(symbol)
            logger.info(f"訂閱選擇權報價: {symbol}")
            return True
        else:
            message = self.client.get_return_message(code)
            logger.error(f"訂閱選擇權報價失敗: {message}")
            return False

    def subscribe_many(self, symbols: list[str]) -> int:
        """
        批次訂閱多檔選擇權

        Args:
            symbols: 商品代號列表

        Returns:
            int: 成功訂閱的數量
        """
        if not self._connected:
            raise CapitalAPIError("請先連線到報價伺服器")

        # 用逗號分隔多檔商品
        symbols_str = ",".join(symbols)
        self._page_no, code = self._quote.SKQuoteLib_RequestStocks(
            self._page_no, symbols_str
        )

        if code == 0:
            self._subscribed.update(symbols)
            logger.info(f"批次訂閱選擇權報價: {len(symbols)} 檔")
            return len(symbols)
        else:
            message = self.client.get_return_message(code)
            logger.error(f"批次訂閱選擇權報價失敗: {message}")
            return 0

    def get_quote(self, symbol: str) -> Optional[OptionQuote]:
        """
        主動查詢單一選擇權報價 (可用於非盤中時間取得收盤資料)

        Args:
            symbol: 商品代號 (如 "TXO23000A5")

        Returns:
            OptionQuote 或 None
        """
        if not self._connected:
            raise CapitalAPIError("請先連線到報價伺服器")

        try:
            sk = get_sk_module()
            stock = sk.SKSTOCKLONG()

            # 使用 GetStockByNoLONG 主動查詢
            stock, code = self._quote.SKQuoteLib_GetStockByNoLONG(symbol, stock)

            if code != 0:
                message = self.client.get_return_message(code)
                logger.warning(f"查詢報價失敗 {symbol}: {message}")
                return None

            # 解析選擇權類型
            option_type = self._parse_option_type(symbol)

            # 取得小數位數
            decimal = stock.sDecimal if hasattr(stock, 'sDecimal') and stock.sDecimal > 0 else 2
            divisor = 10 ** decimal

            quote = OptionQuote(
                symbol=symbol,
                name=stock.bstrStockName,
                option_type=option_type,
                strike_price=self._parse_strike_price(symbol),
                decimal_places=decimal,
                # 價格
                close_price=stock.nClose / divisor,
                open_price=stock.nOpen / divisor,
                high_price=stock.nHigh / divisor,
                low_price=stock.nLow / divisor,
                ref_price=stock.nRef / divisor,
                # 買賣報價
                bid_price=stock.nBid / divisor,
                bid_qty=stock.nBc,
                ask_price=stock.nAsk / divisor,
                ask_qty=stock.nAc,
                # 成交
                volume=stock.nTQty,
            )

            # 更新選擇權鏈快取
            self._update_chain(quote)

            return quote

        except Exception as e:
            logger.error(f"查詢選擇權報價時發生錯誤: {e}")
            return None

    def get_chain(self, underlying: str = "TXO") -> Optional[OptionsChain]:
        """
        取得選擇權鏈

        Args:
            underlying: 標的代號 (預設 "TXO")

        Returns:
            OptionsChain 或 None
        """
        return self._chains.get(underlying)

    @property
    def is_connected(self) -> bool:
        """是否已連線"""
        return self._connected

    @property
    def subscribed_options(self) -> set[str]:
        """已訂閱的選擇權"""
        return self._subscribed.copy()

    def __enter__(self) -> TwOptionsQuoteManager:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
