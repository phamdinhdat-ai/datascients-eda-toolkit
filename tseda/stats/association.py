"""Effect size cho các cặp biến. Luôn báo cáo effect size cùng với p-value."""
from __future__ import annotations

import numpy as np
import pandas as pd


def cramers_v_bias_corrected(table: np.ndarray, chi2: float) -> float:
    """Cramér's V có hiệu chỉnh độ lệch (Bergsma, 2013). Ổn định hơn khi mẫu nhỏ hoặc bảng lớn."""
    n = float(table.sum())
    if n <= 1:
        return 0.0
    r, k = table.shape
    phi2 = chi2 / n
    phi2c = max(0.0, phi2 - (k - 1) * (r - 1) / (n - 1))
    rc = r - (r - 1) ** 2 / (n - 1)
    kc = k - (k - 1) ** 2 / (n - 1)
    denom = min(kc - 1, rc - 1)
    if denom <= 0:
        return 0.0
    return float(np.sqrt(phi2c / denom))


def eta_squared_from_h(h: float, k: int, n: int) -> float:
    """Epsilon-squared cho Kruskal-Wallis: (H - k + 1) / (n - k)."""
    if n - k <= 0:
        return 0.0
    return float(max(0.0, (h - k + 1) / (n - k)))


def eta_squared_anova(groups: list[np.ndarray]) -> float:
    all_vals = np.concatenate(groups)
    grand = all_vals.mean()
    ss_between = sum(len(g) * (g.mean() - grand) ** 2 for g in groups)
    ss_total = float(((all_vals - grand) ** 2).sum())
    return float(ss_between / ss_total) if ss_total > 0 else 0.0


def rank_biserial(u: float, n1: int, n2: int) -> float:
    """Effect size cho Mann-Whitney: 2U/(n1 n2) - 1, nằm trong [-1, 1]."""
    if n1 == 0 or n2 == 0:
        return 0.0
    return float(2 * u / (n1 * n2) - 1)


def normalized_mutual_information(x: pd.Series, y: pd.Series) -> float:
    """NMI giữa hai biến rời rạc, chuẩn hóa về [0, 1]."""
    df = pd.DataFrame({"x": x.astype(str), "y": y.astype(str)})
    n = len(df)
    if n == 0:
        return 0.0
    pxy = df.value_counts(normalize=True)
    px = df["x"].value_counts(normalize=True)
    py = df["y"].value_counts(normalize=True)
    mi = 0.0
    for (xi, yi), p in pxy.items():
        mi += p * np.log(p / (px[xi] * py[yi]))
    hx = -(px * np.log(px)).sum()
    hy = -(py * np.log(py)).sum()
    denom = np.sqrt(hx * hy)
    return float(mi / denom) if denom > 0 else 0.0
