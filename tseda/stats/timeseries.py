"""Công cụ chuỗi thời gian: ACF, kiểm định dừng (ADF + KPSS), điểm đứt gãy ứng viên."""
from __future__ import annotations

import warnings

import numpy as np
from scipy import stats as sps


def acf(x: np.ndarray, max_lag: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = x.size
    if n < 3 or x.std() == 0:
        return np.zeros(max_lag + 1)
    x = x - x.mean()
    denom = float((x * x).sum())
    max_lag = min(max_lag, n - 1)
    out = np.zeros(max_lag + 1)
    for lag in range(max_lag + 1):
        out[lag] = float((x[: n - lag] * x[lag:]).sum()) / denom
    return out


def acf_threshold(n: int) -> float:
    return 1.96 / np.sqrt(n) if n > 0 else 1.0


def seasonal_candidates(x: np.ndarray, lags: list[int], min_strength: float) -> list[dict]:
    """Các lag mùa vụ ứng viên có tự tương quan vượt ngưỡng ý nghĩa và mạnh hơn min_strength."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if x.size < 3:
        return []
    max_lag = max(lags) if lags else 1
    values = acf(x, max_lag)
    thr = max(acf_threshold(x.size), min_strength)
    out = []
    for lag in lags:
        if lag < len(values) and abs(values[lag]) >= thr:
            out.append({"lag": lag, "acf": round(float(values[lag]), 4)})
    return sorted(out, key=lambda d: -abs(d["acf"]))


def stationarity(x: np.ndarray, alpha: float = 0.05, max_n: int = 2000) -> dict:
    """ADF (H0: có nghiệm đơn vị) và KPSS (H0: dừng). Kết luận kết hợp hai kiểm định.

    Chỉ dùng `max_n` quan sát gần nhất: autolag trên chuỗi dài rất chậm và tính dừng thường
    được quyết định bởi giai đoạn gần đây. Ghi rõ cửa sổ trong kết quả.
    """
    try:
        from statsmodels.tsa.stattools import adfuller, kpss
    except ImportError:
        return {"available": False, "reason": "Cần statsmodels: pip install 'tseda[stats]'"}

    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if x.size < 20 or x.std() == 0:
        return {"available": True, "conclusion": "không đủ dữ liệu", "n": int(x.size)}
    window = x[-max_n:] if x.size > max_n else x
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            adf_p = float(adfuller(window, maxlag=min(12, window.size // 10), autolag="AIC")[1])
        except Exception:  # noqa: BLE001 - statsmodels đôi khi lỗi trên chuỗi đặc biệt
            adf_p = None
        try:
            kpss_p = float(kpss(window, regression="c", nlags="auto")[1])
        except Exception:  # noqa: BLE001
            kpss_p = None

    if adf_p is None or kpss_p is None:
        conclusion = "không kết luận được (một kiểm định lỗi)"
    else:
        adf_rej = adf_p < alpha
        kpss_rej = kpss_p < alpha
        if adf_rej and not kpss_rej:
            conclusion = "dừng (stationary)"
        elif not adf_rej and kpss_rej:
            conclusion = "không dừng (có nghiệm đơn vị)"
        elif adf_rej and kpss_rej:
            conclusion = "mâu thuẫn: cả hai đều bác bỏ, có thể là dừng quanh xu hướng hoặc đứt gãy cấu trúc"
        else:
            conclusion = "chưa đủ bằng chứng (cả hai đều không bác bỏ)"
    return {"available": True, "adf_p": adf_p, "kpss_p": kpss_p, "conclusion": conclusion,
            "n": int(x.size), "window_n": int(window.size)}


def _welch_all(x: np.ndarray, cands: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Welch t cho mọi điểm chia cùng lúc, bằng tổng tích lũy. Trả về (t, mean_left, mean_right)."""
    n = x.size
    cs = np.concatenate([[0.0], np.cumsum(x)])
    cs2 = np.concatenate([[0.0], np.cumsum(x * x)])
    nl = cands.astype(float)
    nr = n - nl
    sum_l, sum_r = cs[cands], cs[n] - cs[cands]
    sq_l, sq_r = cs2[cands], cs2[n] - cs2[cands]
    mean_l, mean_r = sum_l / nl, sum_r / nr
    var_l = np.maximum(sq_l / nl - mean_l ** 2, 0) * nl / np.maximum(nl - 1, 1)
    var_r = np.maximum(sq_r / nr - mean_r ** 2, 0) * nr / np.maximum(nr - 1, 1)
    se = np.sqrt(var_l / nl + var_r / nr)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (mean_l - mean_r) / se
    return t, mean_l, mean_r


def break_candidate(x: np.ndarray, min_segment: int = 20, max_candidates: int = 5000) -> dict | None:
    """Điểm chia có |t| lớn nhất giữa hai đoạn (Welch), đã hiệu chỉnh tự tương quan và đa so sánh.

    - Hiệu chỉnh AR(1): t được nhân với sqrt((1-rho)/(1+rho)) vì các quan sát liên tiếp không độc lập.
      Không có hiệu chỉnh này, chuỗi giá (random walk) luôn cho p-value giả rất nhỏ.
    - Bonferroni theo số điểm ứng viên đã thử, vì điểm chia được chọn là điểm cực đại.
    Đây là chỉ báo ứng viên. Cần đối chiếu với sự kiện thực tế.
    """
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = x.size
    if n < 2 * min_segment:
        return None
    rho = float(np.clip(acf(x, 1)[1], -0.99, 0.99))
    scale = float(np.sqrt((1 - rho) / (1 + rho)))
    candidates = np.arange(min_segment, n - min_segment + 1)
    if candidates.size > max_candidates:
        candidates = candidates[np.linspace(0, candidates.size - 1, max_candidates).astype(int)]
    t_all, mean_l, mean_r = _welch_all(x, candidates)
    valid = np.isfinite(t_all)
    tried = int(valid.sum())
    if tried == 0:
        return None
    t_adj_all = np.where(valid, t_all * scale, 0.0)
    k = int(np.argmax(np.abs(t_adj_all)))
    best = {"index": int(candidates[k]), "t": float(t_adj_all[k]), "t_raw": float(t_all[k]),
            "mean_left": float(mean_l[k]), "mean_right": float(mean_r[k])}
    p_adj = float(2 * sps.norm.sf(abs(best["t"])))
    best["p"] = min(1.0, p_adj * max(tried, 1))
    best["rho1"] = round(rho, 4)
    best["n_candidates"] = tried
    return best
