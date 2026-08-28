"""
選擇權鏈資料結構

定義選擇權報價和選擇權鏈的資料模型
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict, List, Optional


class OptionType(str, Enum):
    """選擇權類型"""
    CALL = "C"
    PUT = "P"


@dataclass
class OptionQuote:
    """
    單一選擇權報價資料

    包含履約價、買賣價、成交價等完整報價資訊
    """
    # 基本資訊
    symbol: str                    # 商品代號 (如 TXO22000C4)
    name: str                      # 商品名稱
    option_type: OptionType        # Call 或 Put
    strike_price: float            # 履約價
    expiry_date: Optional[date] = None  # 到期日

    # 價格資訊
    close_price: float = 0.0       # 成交價 (最新價)
    open_price: float = 0.0        # 開盤價
    high_price: float = 0.0        # 最高價
    low_price: float = 0.0         # 最低價
    ref_price: float = 0.0         # 昨收/參考價
    settle_price: float = 0.0      # 結算價

    # 買賣報價
    bid_price: float = 0.0         # 買價 (Bid)
    bid_qty: int = 0               # 買量
    ask_price: float = 0.0         # 賣價 (Ask)
    ask_qty: int = 0               # 賣量

    # 成交資訊
    volume: int = 0                # 成交量
    tick_qty: int = 0              # 單量

    # 五檔報價 (可選)
    best_bids: List[tuple[float, int]] = field(default_factory=list)  # [(價格, 量), ...]
    best_asks: List[tuple[float, int]] = field(default_factory=list)

    # 交易所資訊
    market_no: str = ""            # 市場代碼
    exchange_no: str = ""          # 交易所代號
    exchange_name: str = ""        # 交易所名稱
    trading_day: int = 0           # 交易日 (YYYYMMDD)

    # 小數位數
    decimal_places: int = 2        # 報價小數位數 (sDecimal；解碼 price = raw / 10^decimal_places)
    denominator: int = 1           # nDenominator (美債 32 分數制可能 != 1)

    # 原始整數值（忠於 SKFOREIGNLONG，供下游 raw 層忠實入庫；不可變鐵律＝raw 存整數）
    # 解碼留消費端：price = raw_* / 10^decimal_places（raw_strike 不除，已是最終單位）
    raw_open: int = 0
    raw_high: int = 0
    raw_low: int = 0
    raw_close: int = 0
    raw_settle: int = 0
    raw_ref: int = 0
    raw_bid: int = 0
    raw_ask: int = 0
    raw_strike: int = 0            # nStrikePrice 原始整數（不除）

    @property
    def mid_price(self) -> float:
        """買賣中價"""
        if self.bid_price > 0 and self.ask_price > 0:
            return (self.bid_price + self.ask_price) / 2
        return self.close_price

    @property
    def spread(self) -> float:
        """買賣價差"""
        if self.bid_price > 0 and self.ask_price > 0:
            return self.ask_price - self.bid_price
        return 0.0

    @property
    def spread_pct(self) -> float:
        """買賣價差百分比"""
        if self.mid_price > 0:
            return self.spread / self.mid_price * 100
        return 0.0

    def is_call(self) -> bool:
        return self.option_type == OptionType.CALL

    def is_put(self) -> bool:
        return self.option_type == OptionType.PUT


@dataclass
class OptionStrike:
    """
    同一履約價的 Call 和 Put 配對

    用於顯示選擇權鏈時的單一列
    """
    strike_price: float
    call: Optional[OptionQuote] = None
    put: Optional[OptionQuote] = None

    @property
    def has_both(self) -> bool:
        """是否同時有 Call 和 Put 報價"""
        return self.call is not None and self.put is not None


@dataclass
class OptionsChain:
    """
    選擇權鏈

    包含同一標的、同一到期日的所有履約價選擇權
    """
    underlying: str                           # 標的 (如 TX, MTX)
    expiry_date: Optional[date] = None        # 到期日
    expiry_code: str = ""                     # 到期月份代碼 (如 "202401")

    # 按履約價排序的選擇權
    strikes: Dict[float, OptionStrike] = field(default_factory=dict)

    # 標的現貨/期貨價格 (用於計算價內/價外)
    underlying_price: float = 0.0

    def add_quote(self, quote: OptionQuote):
        """加入一筆選擇權報價"""
        strike = quote.strike_price

        if strike not in self.strikes:
            self.strikes[strike] = OptionStrike(strike_price=strike)

        if quote.is_call():
            self.strikes[strike].call = quote
        else:
            self.strikes[strike].put = quote

    def get_sorted_strikes(self) -> List[float]:
        """取得排序後的履約價列表"""
        return sorted(self.strikes.keys())

    def get_atm_strike(self) -> Optional[float]:
        """
        取得最接近價平 (ATM) 的履約價

        需要先設定 underlying_price
        """
        if self.underlying_price <= 0 or not self.strikes:
            return None

        strikes = self.get_sorted_strikes()
        return min(strikes, key=lambda x: abs(x - self.underlying_price))

    def get_calls(self) -> List[OptionQuote]:
        """取得所有 Call 選擇權 (按履約價排序)"""
        calls = []
        for strike in self.get_sorted_strikes():
            if self.strikes[strike].call:
                calls.append(self.strikes[strike].call)
        return calls

    def get_puts(self) -> List[OptionQuote]:
        """取得所有 Put 選擇權 (按履約價排序)"""
        puts = []
        for strike in self.get_sorted_strikes():
            if self.strikes[strike].put:
                puts.append(self.strikes[strike].put)
        return puts

    def get_itm_calls(self) -> List[OptionQuote]:
        """取得價內 Call (履約價 < 標的價格)"""
        if self.underlying_price <= 0:
            return []
        return [c for c in self.get_calls() if c.strike_price < self.underlying_price]

    def get_otm_calls(self) -> List[OptionQuote]:
        """取得價外 Call (履約價 > 標的價格)"""
        if self.underlying_price <= 0:
            return []
        return [c for c in self.get_calls() if c.strike_price > self.underlying_price]

    def get_itm_puts(self) -> List[OptionQuote]:
        """取得價內 Put (履約價 > 標的價格)"""
        if self.underlying_price <= 0:
            return []
        return [p for p in self.get_puts() if p.strike_price > self.underlying_price]

    def get_otm_puts(self) -> List[OptionQuote]:
        """取得價外 Put (履約價 < 標的價格)"""
        if self.underlying_price <= 0:
            return []
        return [p for p in self.get_puts() if p.strike_price < self.underlying_price]

    def __len__(self) -> int:
        return len(self.strikes)
