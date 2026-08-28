"""Black-76 期貨選擇權定價、Greeks 與隱含波動率。

期貨選擇權的正解是 **Black-76**（用期貨價 F、整體折現 e^{-rT}），
與股票現貨的 Black-Scholes-Merton 不同：

    BSM(spot S)                         Black-76(futures F)
    d1 = (ln(S/K)+(r+σ²/2)T)/(σ√T)      d1 = (ln(F/K)+(σ²/2)T)/(σ√T)   ← 無 r 漂移
    Call = S·N(d1) − K·e^{−rT}·N(d2)    Call = e^{−rT}·[F·N(d1) − K·N(d2)]

純標準庫（math），對單一選擇權做純量運算；不依賴 numpy/scipy、不碰 COM。
生產環境的 Greeks 由 Excel 公式即時算（可調 r/T），本模組是 IV 計算與測試/驗證的真值來源。

慣例：
- T 為年；sigma 為年化波動率（1.0 = 100%）。
- vega 為「每 1.0 vol」的價格變動（每 1% 需 /100）。
- theta 為「每年」的價格變動（每日需 /365）；θ = ∂Price/∂t = −∂Price/∂T。
- rho 對 F 固定（Black-76 中 d1/d2 不含 r）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    """標準常態 CDF（用 erfc 在尾端較穩定）。"""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _norm_pdf(x: float) -> float:
    """標準常態 PDF。"""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _normalize_type(option_type) -> str:
    """接受 'C'/'P'/'call'/'put'（含 OptionType 列舉）→ 'call'/'put'。"""
    raw = option_type.value if hasattr(option_type, "value") else option_type
    s = str(raw).strip().lower()
    if s in ("c", "call"):
        return "call"
    if s in ("p", "put"):
        return "put"
    raise ValueError(f"未知的 option_type: {option_type!r}（接受 C/P/call/put）")


def _d1(F: float, K: float, T: float, sigma: float) -> float:
    return (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))


def _d2(F: float, K: float, T: float, sigma: float) -> float:
    return _d1(F, K, T, sigma) - sigma * math.sqrt(T)


def _is_degenerate(T: float, sigma: float) -> bool:
    return T <= 0.0 or sigma <= 0.0


# --------------------------------------------------------------------------- #
# 理論價
# --------------------------------------------------------------------------- #
def black76_call(F: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-76 Call 理論價。"""
    if _is_degenerate(T, sigma):
        df = math.exp(-r * T) if T > 0 else 1.0
        return df * max(F - K, 0.0)
    df = math.exp(-r * T)
    d1 = _d1(F, K, T, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    return df * (F * _norm_cdf(d1) - K * _norm_cdf(d2))


def black76_put(F: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-76 Put 理論價。"""
    if _is_degenerate(T, sigma):
        df = math.exp(-r * T) if T > 0 else 1.0
        return df * max(K - F, 0.0)
    df = math.exp(-r * T)
    d1 = _d1(F, K, T, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    return df * (K * _norm_cdf(-d2) - F * _norm_cdf(-d1))


def black76_price(F: float, K: float, T: float, r: float, sigma: float, option_type) -> float:
    """依 option_type 分派至 call/put 理論價。"""
    if _normalize_type(option_type) == "call":
        return black76_call(F, K, T, r, sigma)
    return black76_put(F, K, T, r, sigma)


# --------------------------------------------------------------------------- #
# Greeks（封閉解）
# --------------------------------------------------------------------------- #
def delta_call(F: float, K: float, T: float, r: float, sigma: float) -> float:
    if _is_degenerate(T, sigma):
        return (math.exp(-r * T) if T > 0 else 1.0) if F > K else 0.0
    df = math.exp(-r * T)
    return df * _norm_cdf(_d1(F, K, T, sigma))


def delta_put(F: float, K: float, T: float, r: float, sigma: float) -> float:
    if _is_degenerate(T, sigma):
        return -(math.exp(-r * T) if T > 0 else 1.0) if F < K else 0.0
    df = math.exp(-r * T)
    return -df * _norm_cdf(-_d1(F, K, T, sigma))


def gamma(F: float, K: float, T: float, r: float, sigma: float) -> float:
    if _is_degenerate(T, sigma):
        return 0.0
    df = math.exp(-r * T)
    d1 = _d1(F, K, T, sigma)
    return df * _norm_pdf(d1) / (F * sigma * math.sqrt(T))


def vega(F: float, K: float, T: float, r: float, sigma: float) -> float:
    """∂Price/∂σ，每 1.0 vol（Call/Put 相同）。"""
    if _is_degenerate(T, sigma):
        return 0.0
    df = math.exp(-r * T)
    d1 = _d1(F, K, T, sigma)
    return F * df * _norm_pdf(d1) * math.sqrt(T)


def _theta_decay(F: float, K: float, T: float, r: float, sigma: float) -> float:
    df = math.exp(-r * T)
    d1 = _d1(F, K, T, sigma)
    return F * df * _norm_pdf(d1) * sigma / (2.0 * math.sqrt(T))


def theta_call(F: float, K: float, T: float, r: float, sigma: float) -> float:
    """每年 theta：θ = r·Call − decay（注意 r·Call 為正號）。"""
    if _is_degenerate(T, sigma):
        return 0.0
    return r * black76_call(F, K, T, r, sigma) - _theta_decay(F, K, T, r, sigma)


def theta_put(F: float, K: float, T: float, r: float, sigma: float) -> float:
    """每年 theta：θ = r·Put − decay。"""
    if _is_degenerate(T, sigma):
        return 0.0
    return r * black76_put(F, K, T, r, sigma) - _theta_decay(F, K, T, r, sigma)


def rho_call(F: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-76：d1/d2 不含 r → Rho_Call = −T·Call。"""
    if T <= 0.0:
        return 0.0
    return -T * black76_call(F, K, T, r, sigma)


def rho_put(F: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-76：Rho_Put = −T·Put。"""
    if T <= 0.0:
        return 0.0
    return -T * black76_put(F, K, T, r, sigma)


# --------------------------------------------------------------------------- #
# 聚合
# --------------------------------------------------------------------------- #
@dataclass
class OptionGreeks:
    """理論價 + 5 Greeks（驗證/測試用；生產 Greeks 走 Excel 公式）。"""
    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "delta": self.delta,
            "gamma": self.gamma,
            "vega": self.vega,
            "theta": self.theta,
            "rho": self.rho,
        }


def calc_all_greeks(
    F: float, K: float, T: float, r: float, sigma: float, option_type
) -> OptionGreeks:
    """一次算出理論價 + delta/gamma/vega/theta/rho。"""
    if _normalize_type(option_type) == "call":
        return OptionGreeks(
            price=black76_call(F, K, T, r, sigma),
            delta=delta_call(F, K, T, r, sigma),
            gamma=gamma(F, K, T, r, sigma),
            vega=vega(F, K, T, r, sigma),
            theta=theta_call(F, K, T, r, sigma),
            rho=rho_call(F, K, T, r, sigma),
        )
    return OptionGreeks(
        price=black76_put(F, K, T, r, sigma),
        delta=delta_put(F, K, T, r, sigma),
        gamma=gamma(F, K, T, r, sigma),
        vega=vega(F, K, T, r, sigma),
        theta=theta_put(F, K, T, r, sigma),
        rho=rho_put(F, K, T, r, sigma),
    )


# --------------------------------------------------------------------------- #
# 隱含波動率（Newton-Raphson + bisection 後備）
# --------------------------------------------------------------------------- #
_IV_LOW = 1e-3
_IV_HIGH = 5.0


def implied_vol(
    price: float,
    F: float,
    K: float,
    T: float,
    r: float,
    option_type,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> float | None:
    """由市價反解隱含波動率。

    回傳 sigma；下列情況回 None：
    - T <= 0（已到期）
    - 市價低於折現內含價或非正（無解）
    - 不收斂

    先用 Newton-Raphson（以 vega 為導數），失敗/越界則退回 [1e-3, 5] 區間的 bisection。
    """
    if T <= 0.0 or price <= 0.0:
        return None

    is_call = _normalize_type(option_type) == "call"
    df = math.exp(-r * T)
    intrinsic = df * (max(F - K, 0.0) if is_call else max(K - F, 0.0))
    if price < intrinsic - tol:
        return None

    def diff(sigma: float) -> float:
        model = black76_call(F, K, T, r, sigma) if is_call else black76_put(F, K, T, r, sigma)
        return model - price

    # --- Newton-Raphson ---
    sigma = 0.2
    for _ in range(max_iter):
        d = diff(sigma)
        if abs(d) < tol:
            if _IV_LOW <= sigma <= _IV_HIGH:
                return sigma
            break
        v = vega(F, K, T, r, sigma)
        if v < 1e-10:
            break
        sigma -= d / v
        if not (_IV_LOW <= sigma <= _IV_HIGH):
            break

    # --- bisection 後備 ---
    lo, hi = _IV_LOW, _IV_HIGH
    f_lo, f_hi = diff(lo), diff(hi)
    # 端點即為根（真實 σ 恰落在邊界）— 必須先處理，否則 f_lo==0 會讓嚴格變號判據失效
    if abs(f_lo) < tol:
        return lo
    if abs(f_hi) < tol:
        return hi
    if f_lo * f_hi > 0:
        return None  # 區間內無變號 → 無解
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f_mid = diff(mid)
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    # 未在容差內收斂：驗證後才回，避免悄悄回半路值
    mid = 0.5 * (lo + hi)
    return mid if abs(diff(mid)) < tol else None
