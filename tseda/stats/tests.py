"""Kiểm định được chọn theo điều kiện quan sát được. Mỗi kết quả kèm lý do chọn."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats as sps

from tseda.core.records import TestResult
from tseda.stats.association import (
    cramers_v_bias_corrected,
    eta_squared_anova,
    eta_squared_from_h,
    rank_biserial,
)
from tseda.stats.descriptive import normality


def collapse_rare(labels: pd.Series, min_share: float = 0.001, min_count: int = 5) -> pd.Series:
    """Gộp các level hiếm thành '__khác__' trước khi kiểm định, tránh bảng thưa."""
    counts = labels.value_counts()
    total = counts.sum()
    rare = counts[(counts / total < min_share) | (counts < min_count)].index
    if len(rare) == 0:
        return labels
    return labels.where(~labels.isin(rare), "__khác__")


def num_num(x: pd.Series, y: pd.Series) -> TestResult:
    mask = x.notna() & y.notna()
    n = int(mask.sum())
    if n < 3:
        return TestResult("spearman", None, None, None, "rho", n, "n quá nhỏ")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rho, p = sps.spearmanr(x[mask].to_numpy(), y[mask].to_numpy())
    return TestResult("spearman", float(rho), float(p), float(rho), "rho", n,
                      "Spearman: không giả định phân phối chuẩn, bắt được quan hệ đơn điệu")


def num_cat(values: pd.Series, labels: pd.Series, min_n: int = 30, min_share: float = 0.001,
            min_count: int = 5) -> TestResult:
    mask = values.notna() & labels.notna()
    v = values[mask].astype(float)
    lab = collapse_rare(labels[mask].astype(str), min_share, min_count)
    groups = [v[lab == g].to_numpy() for g in lab.unique()]
    groups = [g for g in groups if len(g) > 0]
    n = int(len(v))
    k = len(groups)
    if k < 2:
        return TestResult("none", None, None, None, "", n, "chỉ có một nhóm sau khi gộp level hiếm")

    use_anova = (
        all(len(g) >= min_n for g in groups)
        and all(_roughly_normal(g) for g in groups)
        and _equal_variance(groups)
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if use_anova:
            stat, p = sps.f_oneway(*groups)
            eff = eta_squared_anova(groups)
            return TestResult("anova", float(stat), float(p), eff, "eta2", n,
                              "ANOVA: nhóm đủ lớn, gần chuẩn, phương sai đồng đều")
        stat, p = sps.kruskal(*groups)
        eff = eta_squared_from_h(float(stat), k, n)
        return TestResult("kruskal", float(stat), float(p), eff, "epsilon2", n,
                          "Kruskal-Wallis: không giả định chuẩn hay phương sai đồng đều")


def _roughly_normal(g: np.ndarray) -> bool:
    if len(g) < 8 or g.std() == 0:
        return False
    skew = float(sps.skew(g, bias=False))
    kurt = float(sps.kurtosis(g, bias=False))
    if abs(skew) > 1 or abs(kurt) > 2:
        return False
    res = normality(g)
    return res.get("p") is not None and res["p"] > 0.01


def _equal_variance(groups: list[np.ndarray]) -> bool:
    if any(len(g) < 3 for g in groups):
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _, p = sps.levene(*groups)
    return bool(p > 0.05)


def cat_cat(a: pd.Series, b: pd.Series, min_expected: float = 5.0, sparse_share: float = 0.2,
            min_share: float = 0.001, min_count: int = 5) -> TestResult:
    mask = a.notna() & b.notna()
    aa = collapse_rare(a[mask].astype(str), min_share, min_count)
    bb = collapse_rare(b[mask].astype(str), min_share, min_count)
    table = pd.crosstab(aa, bb)
    n = int(table.values.sum())
    if table.shape[0] < 2 or table.shape[1] < 2:
        return TestResult("none", None, None, None, "", n, "một trong hai biến có dưới 2 level")
    observed = table.to_numpy(dtype=float)
    expected = sps.contingency.expected_freq(observed)
    sparse = float((expected < min_expected).mean())
    if observed.shape == (2, 2) and sparse > 0:
        odds, p = sps.fisher_exact(observed.astype(int))
        chi2, _, _, _ = sps.chi2_contingency(observed, correction=True)
        v = cramers_v_bias_corrected(observed, float(chi2))
        return TestResult("fisher_exact", float(odds), float(p), v, "cramers_v", n,
                          f"Bảng 2x2 có {sparse:.0%} ô kỳ vọng < {min_expected:g}: dùng Fisher")
    chi2, p, _, _ = sps.chi2_contingency(observed, correction=False)
    v = cramers_v_bias_corrected(observed, float(chi2))
    reason = "Chi-square độc lập"
    if sparse > sparse_share:
        reason += f"; cảnh báo: {sparse:.0%} ô kỳ vọng < {min_expected:g}, p-value có thể không tin cậy"
    return TestResult("chi2", float(chi2), float(p), v, "cramers_v", n, reason)


def bool_num(flag: pd.Series, values: pd.Series) -> TestResult:
    mask = flag.notna() & values.notna()
    f = flag[mask].astype(bool)
    v = values[mask].astype(float)
    g1, g0 = v[f], v[~f]
    n = int(len(v))
    if len(g1) < 2 or len(g0) < 2:
        return TestResult("mannwhitney", None, None, None, "rank_biserial", n, "một nhóm quá nhỏ")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        u, p = sps.mannwhitneyu(g1, g0, alternative="two-sided")
    eff = rank_biserial(float(u), len(g1), len(g0))
    return TestResult("mannwhitney", float(u), float(p), eff, "rank_biserial", n,
                      "Mann-Whitney: so sánh phân phối giữa hai nhóm cờ")


def trend(time_ordinal: np.ndarray, values: np.ndarray) -> TestResult:
    """Mann-Kendall (qua Kendall tau với trục thời gian). Effect là tau."""
    mask = ~(np.isnan(time_ordinal) | np.isnan(values))
    t, y = time_ordinal[mask], values[mask]
    n = int(len(y))
    if n < 8 or np.std(y) == 0:
        return TestResult("mann_kendall", None, None, None, "tau", n, "chuỗi quá ngắn hoặc hằng số")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tau, p = sps.kendalltau(t, y)
    return TestResult("mann_kendall", float(tau), float(p), float(tau), "tau", n,
                      "Kendall tau theo trục thời gian (Mann-Kendall không hiệu chỉnh tự tương quan)")
