"""
Capital API 例外定義
"""


class CapitalAPIError(Exception):
    """Capital API 基礎例外"""

    def __init__(self, message: str, code: int | None = None):
        self.message = message
        self.code = code
        super().__init__(self.message)


class LoginError(CapitalAPIError):
    """登入相關錯誤"""
    pass


class ConnectionError(CapitalAPIError):
    """連線相關錯誤"""
    pass


class OrderError(CapitalAPIError):
    """下單相關錯誤"""
    pass


class QuoteError(CapitalAPIError):
    """報價相關錯誤"""
    pass
