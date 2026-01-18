"""
Capital API 主客戶端

提供登入、登出等核心功能
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import comtypes.client

from .constants import Environment
from .exceptions import LoginError, CapitalAPIError
from .skcom import (
    create_center_lib,
    create_order_lib,
    create_reply_lib,
    get_sk_module,
)

logger = logging.getLogger(__name__)


@dataclass
class Account:
    """交易帳號資訊"""
    broker_id: str      # 券商代號 (4碼)
    account_no: str     # 帳號 (7碼)
    account_type: str   # 帳號類型 (S:證券, F:期貨, H:海期)

    @property
    def full_account(self) -> str:
        """完整帳號 (券商代號+帳號)"""
        return f"{self.broker_id}{self.account_no}"


@dataclass
class CapitalClient:
    """
    群益 API 主客戶端

    使用方式:
        client = CapitalClient()
        client.login("your_id", "your_password")
        # ... 執行操作 ...
        client.logout()

    或使用 context manager:
        with CapitalClient() as client:
            client.login("your_id", "your_password")
            # ... 執行操作 ...
    """
    environment: Environment = Environment.PRODUCTION
    log_path: str | None = None

    # 內部狀態
    _center: object = field(default=None, init=False, repr=False)
    _order: object = field(default=None, init=False, repr=False)
    _reply: object = field(default=None, init=False, repr=False)
    _logged_in: bool = field(default=False, init=False, repr=False)
    _user_id: str | None = field(default=None, init=False, repr=False)
    _accounts: list[Account] = field(default_factory=list, init=False, repr=False)

    # 事件回調
    _on_reply_message: Callable[[str, str], int] | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self):
        """初始化 COM 元件"""
        self._center = create_center_lib()
        self._order = create_order_lib()
        self._reply = create_reply_lib()

        # 設定環境
        self._center.SKCenterLib_SetAuthority(int(self.environment))

        # 設定 LOG 路徑
        if self.log_path:
            self._center.SKCenterLib_SetLogPath(self.log_path)

        # 註冊事件處理
        self._setup_events()

    def _setup_events(self):
        """設定事件處理器"""
        client = self  # 供內部類別使用

        class ReplyLibEvent:
            def OnReplyMessage(self, user_id: str, message: str) -> int:
                logger.info(f"系統公告: {user_id} - {message}")
                if client._on_reply_message:
                    return client._on_reply_message(user_id, message)
                return -1  # 不自動確認

        class OrderLibEvent:
            def OnAccount(self, login_id: str, account_data: str):
                logger.debug(f"帳號資訊: {login_id} - {account_data}")
                client._parse_account(login_id, account_data)

            def OnProxyStatus(self, user_id: str, code: int):
                msg = client._center.SKCenterLib_GetReturnCodeMessage(code)
                logger.info(f"Proxy 狀態: {user_id} - {msg}")

        self._reply_event = ReplyLibEvent()
        self._reply_handler = comtypes.client.GetEvents(
            self._reply, self._reply_event
        )

        self._order_event = OrderLibEvent()
        self._order_handler = comtypes.client.GetEvents(
            self._order, self._order_event
        )

    def _parse_account(self, login_id: str, account_data: str):
        """解析帳號資料"""
        # 格式: 市場,券商ID,分公司,帳號,身份證,...
        parts = account_data.split(",")
        if len(parts) >= 4:
            account = Account(
                broker_id=parts[1],
                account_no=parts[3],
                account_type=parts[0],
            )
            # 避免重複
            if account.full_account not in [a.full_account for a in self._accounts]:
                self._accounts.append(account)
                logger.info(f"取得帳號: {account.full_account} ({account.account_type})")

    def login(self, user_id: str, password: str) -> bool:
        """
        登入群益 API

        Args:
            user_id: 使用者 ID
            password: 密碼

        Returns:
            bool: 登入是否成功

        Raises:
            LoginError: 登入失敗
        """
        code = self._center.SKCenterLib_Login(user_id, password)
        message = self._center.SKCenterLib_GetReturnCodeMessage(code)

        if code == 0:
            self._logged_in = True
            self._user_id = user_id
            logger.info(f"登入成功: {user_id}")

            # 初始化下單物件並取得帳號
            self._order.SKOrderLib_Initialize()
            self._order.GetUserAccount()

            return True
        else:
            logger.error(f"登入失敗: {message} (code={code})")
            raise LoginError(message, code)

    def logout(self):
        """登出"""
        if self._logged_in:
            # 群益 API 沒有明確的登出函式，
            # 但可以中斷 Proxy 連線
            if self._user_id:
                try:
                    self._order.ProxyDisconnectByID(self._user_id)
                except Exception:
                    pass
            self._logged_in = False
            self._user_id = None
            self._accounts.clear()
            logger.info("已登出")

    @property
    def is_logged_in(self) -> bool:
        """是否已登入"""
        return self._logged_in

    @property
    def user_id(self) -> str | None:
        """目前登入的使用者 ID"""
        return self._user_id

    @property
    def accounts(self) -> list[Account]:
        """取得所有交易帳號"""
        return self._accounts.copy()

    def get_account(self, market_type: str = "S") -> Account | None:
        """
        取得指定市場類型的帳號

        Args:
            market_type: S=證券, F=期貨, H=海期

        Returns:
            Account 或 None
        """
        for account in self._accounts:
            if account.account_type == market_type:
                return account
        return None

    def get_api_version(self) -> str:
        """取得 API 版本資訊"""
        return self._center.SKCenterLib_GetSKAPIVersionAndBit("")

    def get_return_message(self, code: int) -> str:
        """取得錯誤代碼對應的訊息"""
        return self._center.SKCenterLib_GetReturnCodeMessage(code)

    def read_certificate(self) -> bool:
        """
        讀取憑證

        Returns:
            bool: 是否成功
        """
        if not self._user_id:
            raise CapitalAPIError("尚未登入")

        code = self._order.ReadCertByID(self._user_id)
        if code == 0:
            logger.info("憑證讀取成功")
            return True
        else:
            message = self.get_return_message(code)
            logger.error(f"憑證讀取失敗: {message}")
            return False

    def init_proxy(self) -> bool:
        """
        初始化 Proxy 連線

        Returns:
            bool: 是否成功
        """
        if not self._user_id:
            raise CapitalAPIError("尚未登入")

        code = self._order.SKOrderLib_InitialProxyByID(self._user_id)
        if code == 0:
            logger.info("Proxy 初始化成功")
            return True
        else:
            message = self.get_return_message(code)
            logger.error(f"Proxy 初始化失敗: {message}")
            return False

    def set_on_reply_message(self, callback: Callable[[str, str], int]):
        """
        設定系統公告回調函式

        Args:
            callback: 回調函式，參數為 (user_id, message)，回傳確認碼
        """
        self._on_reply_message = callback

    def __enter__(self) -> CapitalClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logout()
