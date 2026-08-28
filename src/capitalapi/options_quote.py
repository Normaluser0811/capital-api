"""
選擇權報價管理模組

提供台灣期貨選擇權和海外選擇權的即時報價訂閱
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

import comtypes.client

from .client import CapitalClient
from .exceptions import QuoteError, CapitalAPIError
from .options_chain import OptionQuote, OptionType, OptionsChain
from .skcom import create_oo_quote_lib, get_sk_module

logger = logging.getLogger(__name__)


def build_option_quote(stock) -> OptionQuote:
    """從 SKFOREIGNLONG 結構建 OptionQuote（純函式、可單測、不碰 COM）。

    `raw_*` 欄存原始整數（忠實 raw 層、不可變鐵律）；解碼便利值 = raw / 10^decimal_places，
    `strike` 不除（已是最終單位、與解碼後報價同單位）。

    三個解碼正確性要點（修自舊版 inline bug）：
    - `sDecimal` 可為 0（HSI/JNI divisor=1），不可硬塞 2。
    - 履約價 `nStrikePrice` 不除 divisor。
    - 保留 `nDenominator`（美債 32 分數制可能 != 1）。
    """
    decimal = int(stock.sDecimal) if stock.sDecimal >= 0 else 0
    divisor = 10 ** decimal

    call_put = str(stock.bstrCallPut).upper()
    option_type = OptionType.CALL if call_put == "C" else OptionType.PUT

    return OptionQuote(
        symbol=stock.bstrStockNo,
        name=stock.bstrStockName,
        option_type=option_type,
        strike_price=float(stock.nStrikePrice),
        decimal_places=decimal,
        denominator=int(stock.nDenominator),
        # 價格（解碼後便利值；忠實 raw 整數見 raw_* 欄）
        close_price=stock.nClose / divisor,
        open_price=stock.nOpen / divisor,
        high_price=stock.nHigh / divisor,
        low_price=stock.nLow / divisor,
        ref_price=stock.nRef / divisor,
        settle_price=stock.nSettlePrice / divisor,
        bid_price=stock.nBid / divisor,
        bid_qty=stock.nBc,
        ask_price=stock.nAsk / divisor,
        ask_qty=stock.nAc,
        volume=stock.nTQty,
        tick_qty=stock.nTickQty,
        market_no=stock.bstrMarketNo,
        exchange_no=stock.bstrExchangeNo,
        exchange_name=stock.bstrExchangeName,
        trading_day=stock.nTradingDay,
        # 原始整數（供 raw 層忠實入庫，免受解碼影響）
        raw_open=int(stock.nOpen),
        raw_high=int(stock.nHigh),
        raw_low=int(stock.nLow),
        raw_close=int(stock.nClose),
        raw_settle=int(stock.nSettlePrice),
        raw_ref=int(stock.nRef),
        raw_bid=int(stock.nBid),
        raw_ask=int(stock.nAsk),
        raw_strike=int(stock.nStrikePrice),
    )


@dataclass
class OptionsQuoteManager:
    """
    選擇權報價管理器

    支援台灣期貨選擇權 (TXO) 和海外選擇權報價

    使用方式:
        client = CapitalClient()
        client.login(...)

        options = OptionsQuoteManager(client)
        options.connect()

        # 設定報價回調
        options.on_quote = lambda q: print(f"{q.symbol}: {q.close_price}")

        # 訂閱選擇權
        options.subscribe("TXO", "202501", 22000, OptionType.CALL)

    注意：
        群益的選擇權報價使用 SKOOQuoteLib (海外期貨選擇權)
        台灣選擇權 (TXO) 的報價方式需要確認 API 文件
    """
    client: CapitalClient
    server: int = 0  # 報價伺服器 0:預設, 1:備援

    # 內部狀態
    _oo_quote: object = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)
    _subscribed: set[str] = field(default_factory=set, init=False, repr=False)

    # 選擇權鏈快取
    _chains: Dict[str, OptionsChain] = field(default_factory=dict, init=False, repr=False)

    # 報價頁面編號（群益 API：psPageNo 官方固定帶 1；page 0 不推送報價）
    _page_no: int = field(default=1, init=False, repr=False)

    # 報價回調
    on_quote: Callable[[OptionQuote], None] | None = field(
        default=None, init=False, repr=False
    )
    on_best5: Callable[[str, list], None] | None = field(
        default=None, init=False, repr=False
    )
    on_connection: Callable[[int, int], None] | None = field(
        default=None, init=False, repr=False
    )
    on_products: Callable[[str], None] | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self):
        """初始化報價元件"""
        self._oo_quote = create_oo_quote_lib()
        self._setup_events()

    def _setup_events(self):
        """設定事件處理器"""
        manager = self
        sk = get_sk_module()

        class OOQuoteLibEvent:
            def OnConnect(self, code: int, socket_code: int):
                """連線狀態回調"""
                msg = manager.client.get_return_message(code)
                logger.info(f"選擇權報價連線: code={code}, socket={socket_code}, msg={msg}")
                if manager.on_connection:
                    manager.on_connection(code, socket_code)

            def OnProducts(self, value: str):
                """商品清單回調"""
                logger.debug(f"商品清單: {value}")
                if manager.on_products:
                    manager.on_products(value)

            def OnNotifyQuoteLONG(self, index: int):
                """收到報價通知"""
                try:
                    stock = sk.SKFOREIGNLONG()
                    stock, code = manager._oo_quote.SKOOQuoteLib_GetStockByIndexLONG(
                        index, stock
                    )

                    quote = build_option_quote(stock)

                    # 更新選擇權鏈快取
                    manager._update_chain(quote)

                    if manager.on_quote:
                        manager.on_quote(quote)

                except Exception as e:
                    logger.error(f"處理選擇權報價時發生錯誤: {e}")

            def OnNotifyTicksLONG(self, *args):
                """逐筆成交回調。

                ⚠ 必須用 *args：固定參數簽章會破壞 comtypes 對 SK 事件介面的
                vtable 事件接收器建構，導致其後的事件（OnNotifyQuoteLONG）靜默不觸發
                （OnConnect/OnProducts 在前面 slot 仍會收到，故症狀為「有商品清單、無報價」）。
                """
                pass

            def OnNotifyBest5LONG(self, *args):
                """五檔報價回調（*args；index 為首參，其後 10 對 bid/qty + 10 對 ask/qty）。"""
                if not manager.on_best5:
                    return
                try:
                    idx = args[0]
                    nums = args[1:21]
                    bids = [(nums[i] / 100, nums[i + 1]) for i in range(0, 10, 2)]
                    asks = [(nums[i] / 100, nums[i + 1]) for i in range(10, 20, 2)]
                    manager.on_best5(str(idx), {"bids": bids, "asks": asks})
                except Exception as e:  # noqa: BLE001
                    logger.error(f"處理五檔報價時發生錯誤: {e}")

            def OnNotifyBest10LONG(self, *args):
                """十檔報價回調"""
                pass

        self._oo_quote_event = OOQuoteLibEvent()
        self._oo_quote_handler = comtypes.client.GetEvents(
            self._oo_quote, self._oo_quote_event
        )

    def _update_chain(self, quote: OptionQuote):
        """更新選擇權鏈快取"""
        # 從商品代號解析標的 (簡易版，實際可能需要更複雜的解析)
        # 例如: TXO22000C4 -> underlying=TXO
        symbol = quote.symbol
        underlying = symbol[:3] if len(symbol) > 3 else symbol

        if underlying not in self._chains:
            self._chains[underlying] = OptionsChain(underlying=underlying)

        self._chains[underlying].add_quote(quote)

    def connect(self) -> bool:
        """
        連線到選擇權報價伺服器

        Returns:
            bool: 是否成功發起連線
        """
        if not self.client.is_logged_in:
            raise CapitalAPIError("請先登入")

        # SKOOQuoteLib_EnterMonitorLONG 不需要參數
        code = self._oo_quote.SKOOQuoteLib_EnterMonitorLONG()
        if code == 0:
            self._connected = True
            logger.info("選擇權報價連線發起成功")
            return True
        else:
            message = self.client.get_return_message(code)
            logger.error(f"選擇權報價連線失敗: {message}")
            raise QuoteError(message, code)

    def disconnect(self):
        """中斷報價連線"""
        if self._connected:
            self._oo_quote.SKOOQuoteLib_LeaveMonitor()
            self._connected = False
            self._subscribed.clear()
            self._chains.clear()
            logger.info("選擇權報價連線已中斷")

    def get_products(self) -> bool:
        """
        取得海外選擇權商品清單

        Returns:
            bool: 是否成功
        """
        if not self._connected:
            raise CapitalAPIError("請先連線到報價伺服器")

        code = self._oo_quote.SKOOQuoteLib_RequestProducts()
        if code == 0:
            logger.info("請求海外選擇權商品清單")
            return True
        else:
            message = self.client.get_return_message(code)
            logger.error(f"取得商品清單失敗: {message}")
            return False

    def subscribe(self, symbol: str) -> bool:
        """
        訂閱選擇權報價

        Args:
            symbol: 商品代號 (如海外選擇權格式)

        Returns:
            bool: 是否成功
        """
        if not self._connected:
            raise CapitalAPIError("請先連線到報價伺服器")

        # 官方文件：psPageNo「固定帶 1」（page 0 rc=0 但不推送報價）
        self._page_no, code = self._oo_quote.SKOOQuoteLib_RequestStocks(1, symbol)
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

        # 多檔以 "#" 區隔（每檔須為「交易所,代碼」；逗號併接會得 3023 商品代碼無效）
        symbols_str = "#".join(symbols)
        # 官方文件：psPageNo「固定帶 1」。page 0 會 rc=0 但**不推送報價**（OnNotifyQuoteLONG 不觸發）。
        self._page_no, code = self._oo_quote.SKOOQuoteLib_RequestStocks(1, symbols_str)

        if code == 0:
            self._subscribed.update(symbols)
            logger.info(f"批次訂閱選擇權報價: {len(symbols)} 檔")
            return len(symbols)
        else:
            message = self.client.get_return_message(code)
            logger.error(f"批次訂閱選擇權報價失敗: {message}")
            return 0

    def get_chain(self, underlying: str) -> Optional[OptionsChain]:
        """
        取得選擇權鏈

        Args:
            underlying: 標的代號 (如 "TXO")

        Returns:
            OptionsChain 或 None
        """
        return self._chains.get(underlying)

    def get_all_chains(self) -> Dict[str, OptionsChain]:
        """取得所有選擇權鏈"""
        return self._chains.copy()

    @property
    def is_connected(self) -> bool:
        """是否已連線"""
        return self._connected

    @property
    def subscribed_options(self) -> set[str]:
        """已訂閱的選擇權"""
        return self._subscribed.copy()

    def __enter__(self) -> OptionsQuoteManager:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
