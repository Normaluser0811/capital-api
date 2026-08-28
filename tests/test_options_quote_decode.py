"""build_option_quote 解碼 / raw 欄位映射單元測試（不碰 COM，用假 stock 結構）。

鎖定三個曾經的 inline 解碼 bug 不再回歸：
1. sDecimal=0 時 divisor 必為 1（HSI/JNI），不可硬塞 2。
2. 履約價 nStrikePrice 不除 divisor。
3. nDenominator 保留（美債 32 分數制）。
並驗證 raw_* 欄忠實存原始整數（供 raw 層入庫）。
"""
from types import SimpleNamespace

import pytest

from capitalapi.options_quote import build_option_quote
from capitalapi.options_chain import OptionType


def _fake_stock(**over):
    """SKFOREIGNLONG-like 假結構，預設玉米 put（CBOT，sDecimal=3）。"""
    base = dict(
        nStockIdx=0,
        sDecimal=3,
        nDenominator=1,
        bstrMarketNo="W",
        bstrExchangeNo="CBOT",
        bstrExchangeName="芝加哥期貨交易所",
        bstrStockNo="C00448S6",
        bstrStockName="玉米2607P 448 P",
        bstrCallPut="P",
        nOpen=34000,
        nHigh=35000,
        nLow=32000,
        nClose=33000,
        nSettlePrice=33000,
        nTickQty=1,
        nRef=33500,
        nBid=32900,
        nBc=5,
        nAsk=33100,
        nAc=7,
        nTQty=120,
        nStrikePrice=448,
        nTradingDay=20260616,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_corn_decode_and_raw():
    q = build_option_quote(_fake_stock())
    # 解碼便利值 = raw / 10^3
    assert q.close_price == pytest.approx(33.0)
    assert q.settle_price == pytest.approx(33.0)
    assert q.bid_price == pytest.approx(32.9)
    assert q.ask_price == pytest.approx(33.1)
    assert q.decimal_places == 3
    assert q.denominator == 1
    # 履約價不除 divisor（spec 鐵律）
    assert q.strike_price == 448.0
    assert q.raw_strike == 448
    # raw_* 忠實原始整數
    assert q.raw_open == 34000
    assert q.raw_close == 33000
    assert q.raw_settle == 33000
    assert q.raw_bid == 32900
    assert q.raw_ask == 33100
    # 量 / 交易所 / 日期
    assert q.bid_qty == 5 and q.ask_qty == 7 and q.volume == 120
    assert q.option_type == OptionType.PUT
    assert q.exchange_no == "CBOT"
    assert q.trading_day == 20260616


def test_hsi_sdecimal_zero_divisor_is_one():
    # HSI sDecimal=0 → divisor 1（舊 bug 會塞 decimal=2 → /100 錯）
    q = build_option_quote(
        _fake_stock(
            sDecimal=0, bstrExchangeNo="HKEx", bstrStockNo="HSI28000L6",
            bstrCallPut="C", nClose=2451, nSettlePrice=2451, nStrikePrice=28000,
        )
    )
    assert q.decimal_places == 0
    assert q.close_price == 2451.0   # 不被 /100
    assert q.settle_price == 2451.0
    assert q.strike_price == 28000.0
    assert q.raw_close == 2451
    assert q.option_type == OptionType.CALL


def test_denominator_preserved_for_treasuries():
    q = build_option_quote(_fake_stock(nDenominator=32, bstrStockNo="TN12400X6"))
    assert q.denominator == 32   # 32 分數制資訊不可丟


def test_call_put_normalization():
    assert build_option_quote(_fake_stock(bstrCallPut="c")).option_type == OptionType.CALL
    assert build_option_quote(_fake_stock(bstrCallPut="P")).option_type == OptionType.PUT
