"""Tiện ích nhỏ dùng chung: chuyển kiểu numpy/pandas sang JSON, làm tròn an toàn."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [to_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return None if pd.isna(obj) else obj.isoformat()
    if obj is pd.NaT:
        return None
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    if hasattr(obj, "value") and hasattr(obj, "name"):  # Enum
        return obj.value
    return str(obj)


def safe_float(x: Any, default: float | None = None) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(f) or math.isinf(f) else f
