"""
下單管理模組

提供下單、查詢委託/成交回報等功能
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from .client import CapitalClient, Account
from .constants import MarketType, OrderReportType, FulfillReportType
from .exceptions import OrderError, CapitalAPIError

logger = logging.getLogger(__name__)


@dataclass
class OrderManager:
    """
    下單管理器

    使用方式:
        client = CapitalClient()
        client.login(...)

        order = OrderManager(client)
        order.unlock(MarketType.TS)  # 解鎖證券下單

        # 查詢委託
        reports = order.get_order_report()
    """
    client: CapitalClient

    def __post_init__(self):
        """檢查 client 狀態"""
        if not self.client._order:
            raise CapitalAPIError("Client 尚未初始化")

    @property
    def _order(self):
        return self.client._order

    @property
    def _center(self):
        return self.client._center

    def unlock(self, market: MarketType = MarketType.TS) -> bool:
        """
        解鎖下單功能

        首次下單前必須先解鎖

        Args:
            market: 市場類型

        Returns:
            bool: 是否成功
        """
        if not self.client.is_logged_in:
            raise CapitalAPIError("請先登入")

        code = self._order.UnlockOrder(int(market))
        if code == 0:
            logger.info(f"下單解鎖成功: {market.name}")
            return True
        else:
            message = self.client.get_return_message(code)
            logger.error(f"下單解鎖失敗: {message}")
            return False

    def get_order_report(
        self,
        account: Account | None = None,
        report_type: OrderReportType = OrderReportType.ALL
    ) -> str:
        """
        查詢委託回報

        Args:
            account: 交易帳號 (預設使用第一個證券帳號)
            report_type: 查詢類型

        Returns:
            str: 委託回報資料
        """
        if not self.client.is_logged_in:
            raise CapitalAPIError("請先登入")

        if account is None:
            account = self.client.get_account("S")
            if account is None:
                raise CapitalAPIError("找不到證券帳號")

        result = self._order.GetOrderReport(
            self.client.user_id,
            account.full_account,
            int(report_type)
        )
        return result

    def get_fulfill_report(
        self,
        account: Account | None = None,
        report_type: FulfillReportType = FulfillReportType.ALL
    ) -> str:
        """
        查詢成交回報

        Args:
            account: 交易帳號 (預設使用第一個證券帳號)
            report_type: 查詢類型

        Returns:
            str: 成交回報資料
        """
        if not self.client.is_logged_in:
            raise CapitalAPIError("請先登入")

        if account is None:
            account = self.client.get_account("S")
            if account is None:
                raise CapitalAPIError("找不到證券帳號")

        result = self._order.GetFulfillReport(
            self.client.user_id,
            account.full_account,
            int(report_type)
        )
        return result

    def set_max_qty(self, market: MarketType, max_qty: int) -> bool:
        """
        設定每秒委託量限制

        Args:
            market: 市場類型
            max_qty: 最大委託量

        Returns:
            bool: 是否成功
        """
        code = self._order.SetMaxQty(int(market), max_qty)
        if code == 0:
            logger.info(f"設定每秒委託量限制: {market.name} = {max_qty}")
            return True
        else:
            message = self.client.get_return_message(code)
            logger.error(f"設定每秒委託量限制失敗: {message}")
            return False

    def set_max_count(self, market: MarketType, max_count: int) -> bool:
        """
        設定每秒委託筆數限制

        Args:
            market: 市場類型
            max_count: 最大委託筆數

        Returns:
            bool: 是否成功
        """
        code = self._order.SetMaxCount(int(market), max_count)
        if code == 0:
            logger.info(f"設定每秒委託筆數限制: {market.name} = {max_count}")
            return True
        else:
            message = self.client.get_return_message(code)
            logger.error(f"設定每秒委託筆數限制失敗: {message}")
            return False

    def ping_test(self) -> bool:
        """
        Ping 測試 API 主機

        Returns:
            bool: 是否成功
        """
        code = self._order.SKOrderLib_PingandTracertTest()
        return code == 0

    def telnet_test(self) -> bool:
        """
        Telnet 測試 API 主機

        Returns:
            bool: 是否成功
        """
        code = self._order.SKOrderLib_TelnetTest()
        return code == 0
