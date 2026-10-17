"""Mô tả thống kê robust cho số và category. Không biết gì về vai trò hay lĩnh vực."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats as sps


def numeric_summary(x, robust_z_threshold: float = 3.5, iqr_k: float = 3.0) -> dict:
    arr = np.asarray(pd.to_numeric(pd.Series(x), errors="coerce").dropna(), dtype=float)
    n = int(arr.size)
    if n == 0:
        return {"n": 0}
    q = np.quantile(arr, [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    iqr = q[4] - q[2]
    median = q[3]
    mad = float(np.median(np.abs(arr - median)))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        skew = float(sps.skew(arr, bias=False)) if n > 2 and arr.std() > 0 else 0.0
        kurt = float(sps.kurtosis(arr, bias=False)) if n > 3 and arr.std() > 0 else 0.0
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    iqr_out = (arr < q[2] - iqr_k * iqr) | (arr > q[4] + iqr_k * iqr)
    robust_z = 0.6745 * (arr - median) / mad if mad > 0 else np.zeros_like(arr)
    mad_out = np.abs(robust_z) > robust_z_threshold
    return {
        "n": n,
        "mean": mean,
        "std": std,
        "min": float(arr.min()),
        "p01": float(q[0]),
        "p05": float(q[1]),
        "q25": float(q[2]),
        "median": float(median),
        "q75": float(q[4]),
        "p95": float(q[5]),
        "p99": float(q[6]),
        "max": float(arr.max()),
        "iqr": float(iqr),
        "mad": mad,
        "cv": float(std / abs(mean)) if mean != 0 else None,
        "skew": skew,
        "kurtosis_excess": kurt,
        "zero_share": float(np.mean(arr == 0)),
        "negative_share": float(np.mean(arr < 0)),
        "integer_share": float(np.mean(np.isclose(arr, np.round(arr)))),
        "iqr_outlier_share": float(np.mean(iqr_out)),
        "robust_outlier_share": float(np.mean(mad_out)),
        "n_iqr_outliers": int(iqr_out.sum()),
        "n_robust_outliers": int(mad_out.sum()),
    }


def normality(x, max_n_shapiro: int = 5000) -> dict:
    arr = np.asarray(pd.to_numeric(pd.Series(x), errors="coerce").dropna(), dtype=float)
    n = arr.size
    if n < 8 or arr.std() == 0:
        return {"test": None, "p": None, "n": int(n), "reason": "n quá nhỏ hoặc không biến thiên"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if n <= max_n_shapiro:
            stat, p = sps.shapiro(arr)
            return {"test": "shapiro", "statistic": float(stat), "p": float(p), "n": int(n)}
        stat, p = sps.normaltest(arr)
        return {"test": "dagostino", "statistic": float(stat), "p": float(p), "n": int(n)}


def multimodality(x, bins: int = 50, prominence: float = 0.15) -> int:
    """Đếm số đỉnh có ý nghĩa trên histogram đã làm mượt. Chỉ là chỉ báo, không phải kiểm định."""
    arr = np.asarray(pd.to_numeric(pd.Series(x), errors="coerce").dropna(), dtype=float)
    if arr.size < 100 or arr.std() == 0:
        return 1
    counts, _ = np.histogram(arr, bins=bins)
    kernel = np.array([1, 2, 3, 2, 1], dtype=float) / 9
    smooth = np.convolve(counts, kernel, mode="same")
    peak = smooth.max()
    if peak == 0:
        return 1
    modes = 0
    for i in range(1, len(smooth) - 1):
        if smooth[i] > smooth[i - 1] and smooth[i] >= smooth[i + 1] and smooth[i] >= prominence * peak:
            modes += 1
    return max(modes, 1)


def categorical_summary(counts: pd.Series, rare_share: float = 0.001, rare_min_count: int = 5) -> dict:
    counts = counts[counts > 0].sort_values(ascending=False)
    total = int(counts.sum())
    if total == 0:
        return {"n": 0, "n_levels": 0}
    p = counts / total
    k = len(counts)
    entropy = float(-(p * np.log2(p)).sum())
    max_entropy = float(np.log2(k)) if k > 1 else 0.0
    rare_mask = (p < rare_share) | (counts < rare_min_count)
    return {
        "n": total,
        "n_levels": int(k),
        "top_level": str(counts.index[0]),
        "top_share": float(p.iloc[0]),
        "entropy_bits": round(entropy, 4),
        "entropy_normalized": round(entropy / max_entropy, 4) if max_entropy > 0 else None,
        "n_rare_levels": int(rare_mask.sum()),
        "rare_share": float(p[rare_mask].sum()),
    }
