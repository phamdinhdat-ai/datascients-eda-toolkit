"""Các phép biến đổi có thể đưa vào transform plan. Mỗi phép là hàm thuần: series -> series."""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from tseda.text import dates as tdates
from tseda.text import numeric as tnum


def parse_numeric(series: pd.Series, locale: str = "vi", suffix_map: dict | None = None,
                  currency: list | None = None) -> pd.Series:
    numeric, _ = tnum.parse_series(series, locale, suffix_map or {}, currency or [])
    return numeric


def parse_datetime(series: pd.Series, format: str) -> pd.Series:  # noqa: A002
    return tdates.parse_dates(series, format)


def canonicalize(series: pd.Series, mapping: dict) -> pd.Series:
    """mapping: {giá trị gốc: giá trị chuẩn}. Giá trị không có trong mapping giữ nguyên."""
    return series.map(lambda x: mapping.get(x, x) if pd.notna(x) else x).astype("object")


def to_missing(series: pd.Series, values: list) -> pd.Series:
    targets = {str(v).strip().lower() for v in values}
    out = series.astype("object")
    mask = out.map(lambda x: pd.notna(x) and str(x).strip().lower() in targets)
    return out.where(~mask, None)


def map_boolean(series: pd.Series, true_values: list, false_values: list) -> pd.Series:
    t = {str(v).lower() for v in true_values}
    f = {str(v).lower() for v in false_values}

    def conv(x):
        if pd.isna(x):
            return None
        k = str(x).strip().lower()
        if k in t:
            return True
        if k in f:
            return False
        return None
    return pd.Series(series.map(conv), index=series.index, dtype="boolean")


def log1p(series: pd.Series) -> pd.Series:
    num = pd.to_numeric(series, errors="coerce").astype(float)
    return np.log1p(num.where(num > -1))


def winsorize(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    num = pd.to_numeric(series, errors="coerce").astype(float)
    lo, hi = num.quantile(lower), num.quantile(upper)
    return num.clip(lower=lo, upper=hi)


def impute_median(series: pd.Series) -> pd.Series:
    num = pd.to_numeric(series, errors="coerce").astype(float)
    return num.fillna(num.median())


OPS: dict[str, Callable] = {
    "parse_numeric": parse_numeric,
    "parse_datetime": parse_datetime,
    "canonicalize": canonicalize,
    "to_missing": to_missing,
    "map_boolean": map_boolean,
    "log1p": log1p,
    "winsorize": winsorize,
    "impute_median": impute_median,
}

# Phép đảo ngược được (nếu có), để ghi vào plan khi cần hoàn tác.
INVERSE: dict[str, str] = {"log1p": "expm1"}
