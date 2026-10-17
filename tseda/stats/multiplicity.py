"""Hiệu chỉnh đa so sánh: Benjamini-Hochberg (kiểm soát tỷ lệ phát hiện sai)."""
from __future__ import annotations

import numpy as np


def benjamini_hochberg(pvalues: list[float | None]) -> list[float | None]:
    """Trả về q-value theo đúng thứ tự đầu vào. None được giữ nguyên và không tham gia hiệu chỉnh."""
    idx = [i for i, p in enumerate(pvalues) if p is not None and not np.isnan(p)]
    out: list[float | None] = [None] * len(pvalues)
    if not idx:
        return out
    p = np.array([pvalues[i] for i in idx], dtype=float)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order]
    q = ranked * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0, 1)
    adjusted = np.empty(m)
    adjusted[order] = q
    for pos, i in enumerate(idx):
        out[i] = float(adjusted[pos])
    return out
