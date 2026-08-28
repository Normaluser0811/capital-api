"""Black-76 期貨選擇權定價 / Greeks / 隱含波動率 單元測試。

策略：
- 理論價：put-call parity（結構恆等式）+ 一個離線算出的文獻錨點值。
- Greeks：全部用「中央有限差分」驗證封閉解（與實作公式無關，能抓出符號錯誤，
  例如計畫原稿 theta 的 r·Call 符號）。
- 隱含波動率：round-trip（價格 → IV → 價格）+ 邊界（到期 / 低於內含價）。

純標準庫，無 numpy/scipy 依賴（Black-76 此處為純量數學）。
"""

from __future__ import annotations

import math
from enum import Enum
from statistics import NormalDist

import pytest

from capitalapi.pricing import (
    OptionGreeks,
    _d1,
    _d2,
    black76_call,
    black76_price,
    black76_put,
    calc_all_greeks,
    delta_call,
    delta_put,
    gamma,
    implied_vol,
    rho_call,
    rho_put,
    theta_call,
    theta_put,
    vega,
)

# 獨立 CDF（stdlib NormalDist，與實作的 math.erfc 不同程式路徑）→ 交叉驗證理論價
_NCDF = NormalDist().cdf


def _ref_call(F, K, T, r, sigma):
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return math.exp(-r * T) * (F * _NCDF(d1) - K * _NCDF(d2))


def _ref_put(F, K, T, r, sigma):
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return math.exp(-r * T) * (K * _NCDF(-d2) - F * _NCDF(-d1))


# (F, K, T, r, sigma) —涵蓋 ITM / ATM / OTM、不同年期與利率
PARAM_SETS = [
    (2050.0, 2000.0, 0.25, 0.04, 0.20),   # 黃金近月，輕微 ITM call
    (2000.0, 2000.0, 0.50, 0.03, 0.25),   # ATM
    (1900.0, 2100.0, 0.10, 0.05, 0.35),   # OTM call / ITM put
    (100.0, 100.0, 1.00, 0.05, 0.20),     # 文獻錨點
    (5000.0, 4800.0, 0.75, 0.02, 0.18),   # 股指
]


def _price(F, K, T, r, sigma, is_call):
    return black76_call(F, K, T, r, sigma) if is_call else black76_put(F, K, T, r, sigma)


# --------------------------------------------------------------------------- #
# 理論價
# --------------------------------------------------------------------------- #
def test_put_call_parity():
    """Call - Put == e^{-rT} (F - K)（Black-76 結構恆等式）。"""
    for F, K, T, r, sigma in PARAM_SETS:
        lhs = black76_call(F, K, T, r, sigma) - black76_put(F, K, T, r, sigma)
        rhs = math.exp(-r * T) * (F - K)
        assert math.isclose(lhs, rhs, rel_tol=1e-10, abs_tol=1e-9)


def test_atm_call_equals_put():
    """F == K 時，parity 給出 Call == Put。"""
    c = black76_call(2000.0, 2000.0, 0.5, 0.03, 0.25)
    p = black76_put(2000.0, 2000.0, 0.5, 0.03, 0.25)
    assert math.isclose(c, p, rel_tol=1e-12)


def test_call_literature_anchor_atm():
    """高精度真值錨：Black-76 ATM call F=K=100,T=1,r=5%,σ=20% = 7.5770821301（三法驗證）。"""
    c = black76_call(100.0, 100.0, 1.0, 0.05, 0.20)
    assert math.isclose(c, 7.5770821301, abs_tol=1e-7)


def test_call_literature_anchor_hull():
    """Hull 教科書 Black-76 值：F=K=20,T=1/3,r=9%,σ=25% ≈ 1.1166（跨來源 pin scaling/discount）。"""
    c = black76_call(20.0, 20.0, 1.0 / 3.0, 0.09, 0.25)
    assert math.isclose(c, 1.1166, abs_tol=1e-3)


def test_price_matches_independent_cdf_reference():
    """理論價對照獨立 CDF（stdlib NormalDist）+ 顯式公式 → 抓 d1/d2 結構、折現、F/K、符號錯誤。

    含 ITM/OTM（d1≠−d2）情形；parity 對 d1/d2 結構免疫，故此項才是價格公式正確性的真校驗。
    """
    for F, K, T, r, sigma in PARAM_SETS:
        assert math.isclose(black76_call(F, K, T, r, sigma),
                            _ref_call(F, K, T, r, sigma), rel_tol=1e-12, abs_tol=1e-12)
        assert math.isclose(black76_put(F, K, T, r, sigma),
                            _ref_put(F, K, T, r, sigma), rel_tol=1e-12, abs_tol=1e-12)


def test_d1_d2_have_no_rate_drift():
    """Black-76 的 d1/d2 不含 r 漂移（_d1/_d2 簽章無 r 參數即結構保證）：ATM → d1=σ√T/2。"""
    F = K = 100.0
    T, sigma = 1.0, 0.20
    assert math.isclose(_d1(F, K, T, sigma), 0.5 * sigma * math.sqrt(T), rel_tol=1e-12)
    assert math.isclose(_d2(F, K, T, sigma), -0.5 * sigma * math.sqrt(T), rel_tol=1e-12)


def test_call_monotonic_increasing_in_forward():
    """Call 對標的價 F 單調遞增。"""
    base = black76_call(2000.0, 2000.0, 0.5, 0.03, 0.25)
    higher = black76_call(2100.0, 2000.0, 0.5, 0.03, 0.25)
    assert higher > base


def test_call_monotonic_decreasing_in_strike():
    """Call 對履約價 K 單調遞減。"""
    low_k = black76_call(2000.0, 1900.0, 0.5, 0.03, 0.25)
    high_k = black76_call(2000.0, 2100.0, 0.5, 0.03, 0.25)
    assert low_k > high_k


def test_intrinsic_at_expiry():
    """T <= 0：價格回到（折現因子=1 的）內含價。"""
    assert math.isclose(black76_call(2050.0, 2000.0, 0.0, 0.04, 0.2), 50.0, abs_tol=1e-9)
    assert math.isclose(black76_put(2050.0, 2000.0, 0.0, 0.04, 0.2), 0.0, abs_tol=1e-9)
    assert math.isclose(black76_call(1950.0, 2000.0, 0.0, 0.04, 0.2), 0.0, abs_tol=1e-9)
    assert math.isclose(black76_put(1950.0, 2000.0, 0.0, 0.04, 0.2), 50.0, abs_tol=1e-9)


def test_deep_itm_call_approaches_discounted_intrinsic():
    """深價內 call → e^{-rT}(F-K)（時間價值趨近 0）。"""
    F, K, T, r, sigma = 3000.0, 1000.0, 0.25, 0.04, 0.20
    c = black76_call(F, K, T, r, sigma)
    assert math.isclose(c, math.exp(-r * T) * (F - K), rel_tol=2e-3)


# --------------------------------------------------------------------------- #
# Greeks — 中央有限差分驗證
# --------------------------------------------------------------------------- #
def test_delta_matches_finite_difference():
    for F, K, T, r, sigma in PARAM_SETS:
        h = F * 1e-4
        for is_call, fn in ((True, delta_call), (False, delta_put)):
            fd = (_price(F + h, K, T, r, sigma, is_call)
                  - _price(F - h, K, T, r, sigma, is_call)) / (2 * h)
            assert math.isclose(fn(F, K, T, r, sigma), fd, rel_tol=1e-5, abs_tol=1e-7)


def test_delta_bounds():
    """Call delta ∈ (0, e^{-rT}); Put delta ∈ (-e^{-rT}, 0)。"""
    for F, K, T, r, sigma in PARAM_SETS:
        df = math.exp(-r * T)
        dc = delta_call(F, K, T, r, sigma)
        dp = delta_put(F, K, T, r, sigma)
        assert 0.0 < dc < df
        assert -df < dp < 0.0


def test_gamma_matches_second_difference():
    for F, K, T, r, sigma in PARAM_SETS:
        h = F * 1e-3
        fd = (black76_call(F + h, K, T, r, sigma)
              - 2 * black76_call(F, K, T, r, sigma)
              + black76_call(F - h, K, T, r, sigma)) / (h * h)
        assert math.isclose(gamma(F, K, T, r, sigma), fd, rel_tol=1e-3)


def test_gamma_same_for_call_and_put():
    """Gamma 與 vega 對 call/put 相同（透過二階差分對 put 再驗一次）。"""
    F, K, T, r, sigma = 2050.0, 2000.0, 0.25, 0.04, 0.20
    h = F * 1e-3
    fd_put = (black76_put(F + h, K, T, r, sigma)
              - 2 * black76_put(F, K, T, r, sigma)
              + black76_put(F - h, K, T, r, sigma)) / (h * h)
    assert math.isclose(gamma(F, K, T, r, sigma), fd_put, rel_tol=1e-3)


def test_vega_matches_finite_difference():
    """Vega = ∂Price/∂σ（每 1.0 vol）。"""
    for F, K, T, r, sigma in PARAM_SETS:
        h = 1e-4
        fd = (black76_call(F, K, T, r, sigma + h)
              - black76_call(F, K, T, r, sigma - h)) / (2 * h)
        assert math.isclose(vega(F, K, T, r, sigma), fd, rel_tol=1e-5, abs_tol=1e-6)


def test_theta_matches_finite_difference():
    """Theta = ∂Price/∂t = -∂Price/∂T（每年）。能抓出計畫稿 r·Call 符號錯誤。"""
    for F, K, T, r, sigma in PARAM_SETS:
        h = 1e-4
        for is_call, fn in ((True, theta_call), (False, theta_put)):
            fd = -(_price(F, K, T + h, r, sigma, is_call)
                   - _price(F, K, T - h, r, sigma, is_call)) / (2 * h)
            assert math.isclose(fn(F, K, T, r, sigma), fd, rel_tol=1e-4, abs_tol=1e-5)


def test_theta_sign_correction():
    """明確鎖定 theta = r·Price - decay（正號 r·Price），而非計畫稿的 -r·Call。"""
    F, K, T, r, sigma = 2050.0, 2000.0, 0.25, 0.04, 0.20
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    npdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    decay = F * math.exp(-r * T) * npdf * sigma / (2 * math.sqrt(T))
    expected_call = r * black76_call(F, K, T, r, sigma) - decay
    expected_put = r * black76_put(F, K, T, r, sigma) - decay
    assert math.isclose(theta_call(F, K, T, r, sigma), expected_call, rel_tol=1e-10)
    assert math.isclose(theta_put(F, K, T, r, sigma), expected_put, rel_tol=1e-10)


def test_rho_matches_finite_difference():
    for F, K, T, r, sigma in PARAM_SETS:
        h = 1e-5
        for is_call, fn in ((True, rho_call), (False, rho_put)):
            fd = (_price(F, K, T, r + h, sigma, is_call)
                  - _price(F, K, T, r - h, sigma, is_call)) / (2 * h)
            assert math.isclose(fn(F, K, T, r, sigma), fd, rel_tol=1e-5, abs_tol=1e-6)


def test_rho_equals_neg_T_times_price():
    """Black-76：d1/d2 不含 r → Rho_Call = -T·Call, Rho_Put = -T·Put。"""
    for F, K, T, r, sigma in PARAM_SETS:
        assert math.isclose(rho_call(F, K, T, r, sigma),
                            -T * black76_call(F, K, T, r, sigma), rel_tol=1e-10)
        assert math.isclose(rho_put(F, K, T, r, sigma),
                            -T * black76_put(F, K, T, r, sigma), rel_tol=1e-10)


def test_greeks_zero_at_expiry():
    """T <= 0：gamma/vega/theta/rho 為 0。"""
    assert gamma(2050.0, 2000.0, 0.0, 0.04, 0.2) == 0.0
    assert vega(2050.0, 2000.0, 0.0, 0.04, 0.2) == 0.0
    assert theta_call(2050.0, 2000.0, 0.0, 0.04, 0.2) == 0.0
    assert rho_put(2050.0, 2000.0, 0.0, 0.04, 0.2) == 0.0


# --------------------------------------------------------------------------- #
# calc_all_greeks 聚合
# --------------------------------------------------------------------------- #
def test_calc_all_greeks_matches_individual():
    F, K, T, r, sigma = 2050.0, 2000.0, 0.25, 0.04, 0.20
    g = calc_all_greeks(F, K, T, r, sigma, "call")
    assert isinstance(g, OptionGreeks)
    assert math.isclose(g.price, black76_call(F, K, T, r, sigma), rel_tol=1e-12)
    assert math.isclose(g.delta, delta_call(F, K, T, r, sigma), rel_tol=1e-12)
    assert math.isclose(g.gamma, gamma(F, K, T, r, sigma), rel_tol=1e-12)
    assert math.isclose(g.vega, vega(F, K, T, r, sigma), rel_tol=1e-12)
    assert math.isclose(g.theta, theta_call(F, K, T, r, sigma), rel_tol=1e-12)
    assert math.isclose(g.rho, rho_call(F, K, T, r, sigma), rel_tol=1e-12)


def test_calc_all_greeks_put_branch():
    F, K, T, r, sigma = 2050.0, 2000.0, 0.25, 0.04, 0.20
    g = calc_all_greeks(F, K, T, r, sigma, "P")
    assert math.isclose(g.price, black76_put(F, K, T, r, sigma), rel_tol=1e-12)
    assert math.isclose(g.delta, delta_put(F, K, T, r, sigma), rel_tol=1e-12)


def test_option_type_normalization_variants():
    """接受 'C'/'call'/'P'/'put'（大小寫不拘）。"""
    F, K, T, r, sigma = 2050.0, 2000.0, 0.25, 0.04, 0.20
    for variant in ("C", "c", "Call", "CALL"):
        assert math.isclose(calc_all_greeks(F, K, T, r, sigma, variant).price,
                            black76_call(F, K, T, r, sigma), rel_tol=1e-12)
    for variant in ("P", "p", "Put", "PUT"):
        assert math.isclose(calc_all_greeks(F, K, T, r, sigma, variant).price,
                            black76_put(F, K, T, r, sigma), rel_tol=1e-12)


def test_invalid_option_type_raises():
    with pytest.raises(ValueError):
        calc_all_greeks(2050.0, 2000.0, 0.25, 0.04, 0.20, "banana")


# --------------------------------------------------------------------------- #
# 隱含波動率
# --------------------------------------------------------------------------- #
def test_implied_vol_round_trip_call():
    for F, K, T, r, sigma in PARAM_SETS:
        price = black76_call(F, K, T, r, sigma)
        iv = implied_vol(price, F, K, T, r, "call")
        assert iv is not None
        assert math.isclose(iv, sigma, abs_tol=1e-4)


def test_implied_vol_round_trip_put():
    for F, K, T, r, sigma in PARAM_SETS:
        price = black76_put(F, K, T, r, sigma)
        iv = implied_vol(price, F, K, T, r, "put")
        assert iv is not None
        assert math.isclose(iv, sigma, abs_tol=1e-4)


def test_implied_vol_deep_otm_round_trip():
    """深價外（Newton 易發散）也要能 round-trip（需 bisection 後備）。"""
    F, K, T, r, sigma = 2000.0, 3000.0, 0.10, 0.04, 0.45
    price = black76_call(F, K, T, r, sigma)
    iv = implied_vol(price, F, K, T, r, "call")
    assert iv is not None
    assert math.isclose(iv, sigma, abs_tol=1e-3)


def test_implied_vol_high_vol_round_trip():
    F, K, T, r, sigma = 2000.0, 2000.0, 0.5, 0.03, 1.20
    price = black76_call(F, K, T, r, sigma)
    iv = implied_vol(price, F, K, T, r, "call")
    assert iv is not None
    assert math.isclose(iv, sigma, abs_tol=1e-3)


def test_implied_vol_expired_returns_none():
    assert implied_vol(10.0, 2050.0, 2000.0, 0.0, 0.04, "call") is None


def test_implied_vol_below_intrinsic_returns_none():
    """市價低於折現內含價 → 無解。"""
    F, K, T, r = 2050.0, 2000.0, 0.25, 0.04
    intrinsic = math.exp(-r * T) * (F - K)
    assert implied_vol(intrinsic - 5.0, F, K, T, r, "call") is None


def test_implied_vol_at_lower_bound():
    """真實 σ 恰在下界 1e-3（bisection 端點 f_lo==0）必須回 ~1e-3，而非災難性回上界 5.0。"""
    F, K, T, r, sigma = 100.0, 100.0, 0.5, 0.02, 1e-3
    for otype, price_fn in (("call", black76_call), ("put", black76_put)):
        price = price_fn(F, K, T, r, sigma)
        iv = implied_vol(price, F, K, T, r, otype)
        assert iv is not None
        assert math.isclose(iv, sigma, abs_tol=1e-4), f"{otype}: got {iv}"


def test_implied_vol_nonpositive_price_returns_none():
    """市價 <= 0 → 無解（直接 None，不進 solver）。"""
    assert implied_vol(0.0, 2050.0, 2000.0, 0.25, 0.04, "call") is None
    assert implied_vol(-1.0, 2050.0, 2000.0, 0.25, 0.04, "call") is None


def test_implied_vol_unreachable_price_returns_none():
    """市價高於 σ 上界 5.0 對應的模型價（區間內無變號）→ bisection 回 None。"""
    F, K, T, r = 2000.0, 2000.0, 0.5, 0.03
    unreachable = 0.99 * math.exp(-r * T) * F  # 逼近理論上限 df·F，σ<=5 達不到
    assert implied_vol(unreachable, F, K, T, r, "call") is None


# --------------------------------------------------------------------------- #
# 退化分支覆蓋（sigma <= 0、T = 0 的 delta、dispatcher、enum）
# --------------------------------------------------------------------------- #
def test_zero_vol_degenerate_price_and_greeks():
    """sigma <= 0（T > 0）：價格 = 折現內含價；gamma/vega/theta = 0；delta = df 或 0。"""
    F, K, T, r = 2050.0, 2000.0, 0.25, 0.04
    df = math.exp(-r * T)
    for sigma in (0.0, -0.1):
        assert math.isclose(black76_call(F, K, T, r, sigma), df * (F - K), rel_tol=1e-12)
        assert math.isclose(black76_put(F, K, T, r, sigma), 0.0, abs_tol=1e-12)
        assert gamma(F, K, T, r, sigma) == 0.0
        assert vega(F, K, T, r, sigma) == 0.0
        assert theta_call(F, K, T, r, sigma) == 0.0
        assert math.isclose(delta_call(F, K, T, r, sigma), df, rel_tol=1e-12)  # F > K
        assert delta_put(F, K, T, r, sigma) == 0.0                              # F > K


def test_delta_at_expiry():
    """T <= 0 的 delta 退化：F>K → call=1, put=0；F<K → call=0, put=-1。"""
    assert delta_call(2050.0, 2000.0, 0.0, 0.04, 0.2) == 1.0
    assert delta_put(2050.0, 2000.0, 0.0, 0.04, 0.2) == 0.0
    assert delta_call(1950.0, 2000.0, 0.0, 0.04, 0.2) == 0.0
    assert delta_put(1950.0, 2000.0, 0.0, 0.04, 0.2) == -1.0


def test_black76_price_dispatch():
    """black76_price 分派至 call/put 與直呼一致。"""
    F, K, T, r, sigma = 2050.0, 2000.0, 0.25, 0.04, 0.20
    assert math.isclose(black76_price(F, K, T, r, sigma, "call"),
                        black76_call(F, K, T, r, sigma), rel_tol=1e-12)
    assert math.isclose(black76_price(F, K, T, r, sigma, "put"),
                        black76_put(F, K, T, r, sigma), rel_tol=1e-12)


def test_option_type_enum_normalization():
    """option_type 支援帶 .value 的列舉（如 capitalapi OptionType: value 'C'/'P'）。"""

    class _OptType(str, Enum):
        CALL = "C"
        PUT = "P"

    F, K, T, r, sigma = 2050.0, 2000.0, 0.25, 0.04, 0.20
    assert math.isclose(calc_all_greeks(F, K, T, r, sigma, _OptType.CALL).price,
                        black76_call(F, K, T, r, sigma), rel_tol=1e-12)
    assert math.isclose(calc_all_greeks(F, K, T, r, sigma, _OptType.PUT).price,
                        black76_put(F, K, T, r, sigma), rel_tol=1e-12)
