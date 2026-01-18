"""
報價管理模組

提供即時報價訂閱功能
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Any

import comtypes.client

from .client import CapitalClient
from .constants import MarketNo
from .exceptions import QuoteError, CapitalAPIError
from .skcom import create_quote_lib, get_sk_module

logger = logging.getLogger(__name__)


@dataclass
class StockQuote:
    """股票報價資料"""
    stock_no: str          # 股票代號
    stock_name: str        # 股票名稱
    open_price: float      # 開盤價
    close_price: float     # 成交價 (最新價)
    high_price: float      # 最高價
    low_price: float       # 最低價
    up_limit: float        # 漲停價
    down_limit: float      # 跌停價
    buy_count: int         # 外盤量
    sell_count: int        # 內盤量
    total_qty: int         # 總量
    ref_price: float       # 昨收 (參考價)
    yesterday_qty: int     # 昨量
    bid_price: float | str # 買價
    bid_qty: int           # 買量
    ask_price: float | str # 賣價
    ask_qty: int           # 賣量


@dataclass
class Best5:
    """五檔報價"""
    bid_prices: list[float]   # 買價 1-5 檔
    bid_qtys: list[int]       # 買量 1-5 檔
    ask_prices: list[float]   # 賣價 1-5 檔
    ask_qtys: list[int]       # 賣量 1-5 檔
    is_simulated: bool        # 是否為試算揭示


@dataclass
class QuoteManager:
    """
    報價管理器

    使用方式:
        client = CapitalClient()
        client.login(...)

        quote = QuoteManager(client)
        quote.connect()
        quote.subscribe("2330")  # 訂閱台積電

        # 設定報價回調
        quote.on_quote = lambda q: print(f"{q.stock_no}: {q.close_price}")
    """
    client: CapitalClient

    # 內部狀態
    _quote: object = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)
    _subscribed: set[str] = field(default_factory=set, init=False, repr=False)

    # 報價回調
    on_quote: Callable[[StockQuote], None] | None = field(
        default=None, init=False, repr=False
    )
    on_best5: Callable[[str, Best5], None] | None = field(
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
            def OnConnection(self, kind: int, code: int):
                msg = manager.client.get_return_message(code)
                logger.info(f"報價連線狀態: kind={kind}, code={code}, msg={msg}")
                if manager.on_connection:
                    manager.on_connection(kind, code)

            def OnNotifyQuoteLONG(self, market_no: int, index: int):
                """收到報價通知"""
                try:
                    stock = sk.SKSTOCKLONG()
                    stock, code = manager._quote.SKQuoteLib_GetStockByIndexLONG(
                        market_no, index, stock
                    )

                    market_price = manager._quote.SKQuoteLib_GetMarketPriceTS()

                    bid_price = (
                        "市價" if stock.nBid == market_price
                        else stock.nBid / 100.0
                    )
                    ask_price = (
                        "市價" if stock.nAsk == market_price
                        else stock.nAsk / 100.0
                    )

                    quote = StockQuote(
                        stock_no=stock.bstrStockNo,
                        stock_name=stock.bstrStockName,
                        open_price=stock.nOpen / 100.0,
                        close_price=stock.nClose / 100.0,
                        high_price=stock.nHigh / 100.0,
                        low_price=stock.nLow / 100.0,
                        up_limit=stock.nUp / 100.0,
                        down_limit=stock.nDown / 100.0,
                        buy_count=stock.nTBc,
                        sell_count=stock.nTAc,
                        total_qty=stock.nTQty,
                        ref_price=stock.nRef / 100.0,
                        yesterday_qty=stock.nYQty,
                        bid_price=bid_price,
                        bid_qty=stock.nBc,
                        ask_price=ask_price,
                        ask_qty=stock.nAc,
                    )

                    if manager.on_quote:
                        manager.on_quote(quote)

                except Exception as e:
                    logger.error(f"處理報價時發生錯誤: {e}")

            def OnNotifyBest5LONG(
                self, market_no, index,
                bid1, bidq1, bid2, bidq2, bid3, bidq3, bid4, bidq4, bid5, bidq5,
                ext_bid, ext_bidq,
                ask1, askq1, ask2, askq2, ask3, askq3, ask4, askq4, ask5, askq5,
                ext_ask, ext_askq,
                simulated
            ):
                """收到五檔報價"""
                try:
                    best5 = Best5(
                        bid_prices=[
                            bid1/100.0, bid2/100.0, bid3/100.0, bid4/100.0, bid5/100.0
                        ],
                        bid_qtys=[bidq1, bidq2, bidq3, bidq4, bidq5],
                        ask_prices=[
                            ask1/100.0, ask2/100.0, ask3/100.0, ask4/100.0, ask5/100.0
                        ],
                        ask_qtys=[askq1, askq2, askq3, askq4, askq5],
                        is_simulated=(simulated == 1),
                    )

                    # 需要從 index 取得股票代號
                    # 這裡先傳 index 作為 stock_no
                    if manager.on_best5:
                        manager.on_best5(str(index), best5)

                except Exception as e:
                    logger.error(f"處理五檔報價時發生錯誤: {e}")

        self._quote_event = QuoteLibEvent()
        self._quote_handler = comtypes.client.GetEvents(
            self._quote, self._quote_event
        )

    def connect(self) -> bool:
        """
        連線到報價伺服器

        Returns:
            bool: 是否成功發起連線
        """
        if not self.client.is_logged_in:
            raise CapitalAPIError("請先登入")

        code = self._quote.SKQuoteLib_EnterMonitor()
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
            logger.info("報價連線已中斷")

    def subscribe(self, stock_no: str, market: MarketNo = MarketNo.TSE) -> bool:
        """
        訂閱股票報價

        Args:
            stock_no: 股票代號 (如 "2330")
            market: 市場別 (TSE=上市, OTC=上櫃)

        Returns:
            bool: 是否成功
        """
        if not self._connected:
            raise CapitalAPIError("請先連線到報價伺服器")

        page_no = 1  # 報價頁號
        code = self._quote.SKQuoteLib_RequestStocks(
            page_no,
            f"{int(market)}{stock_no}"  # 格式: 市場別 + 股票代號
        )

        if code == 0:
            self._subscribed.add(stock_no)
            logger.info(f"訂閱報價: {stock_no}")
            return True
        else:
            message = self.client.get_return_message(code)
            logger.error(f"訂閱報價失敗: {message}")
            return False

    def subscribe_many(
        self,
        stock_nos: list[str],
        market: MarketNo = MarketNo.TSE
    ) -> int:
        """
        批次訂閱多檔股票

        Args:
            stock_nos: 股票代號列表
            market: 市場別

        Returns:
            int: 成功訂閱的數量
        """
        if not self._connected:
            raise CapitalAPIError("請先連線到報價伺服器")

        # 群益 API 支援一次訂閱多檔，用逗號分隔
        stocks_str = ",".join(f"{int(market)}{no}" for no in stock_nos)

        page_no = 1
        code = self._quote.SKQuoteLib_RequestStocks(page_no, stocks_str)

        if code == 0:
            self._subscribed.update(stock_nos)
            logger.info(f"批次訂閱報價: {len(stock_nos)} 檔")
            return len(stock_nos)
        else:
            message = self.client.get_return_message(code)
            logger.error(f"批次訂閱報價失敗: {message}")
            return 0

    def unsubscribe_all(self):
        """取消所有訂閱"""
        self._subscribed.clear()
        logger.info("已取消所有訂閱")

    @property
    def is_connected(self) -> bool:
        """是否已連線"""
        return self._connected

    @property
    def subscribed_stocks(self) -> set[str]:
        """已訂閱的股票"""
        return self._subscribed.copy()

    def __enter__(self) -> QuoteManager:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
