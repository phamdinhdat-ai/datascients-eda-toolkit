"""Đa cộng tuyến giữa các cột số: VIF = diag(R^-1) của ma trận tương quan."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tseda.core.finding import Severity


def vif_report(ctx, threshold: float = 10.0) -> dict | None:
    cols = [c for c, g in ctx.roles.items() if g.family == "numeric" and c in ctx.typed]
    if len(cols) < 2:
        return None
    frame = pd.DataFrame({c: ctx.typed[c].astype(float) for c in cols}).dropna()
    if len(frame) < 30:
        return None
    frame = frame.loc[ctx.sample_index(frame.index)]
    keep = [c for c in cols if frame[c].std() > 0]
    if len(keep) < 2:
        return None

    corr = np.corrcoef(frame[keep].to_numpy().T)
    try:
        inv = np.linalg.inv(corr)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(corr)
    vif = {c: float(v) for c, v in zip(keep, np.diag(inv))}
    flagged = {c: round(v, 3) for c, v in vif.items() if v > threshold}
    if flagged:
        ctx.finding(
            "relation.vif", Severity.WARN,
            f"Đa cộng tuyến: {len(flagged)} cột số có VIF > {threshold:g}.",
            scope="table", metric={"vif": {c: round(v, 3) for c, v in vif.items()}, "flagged": flagged},
            suggestion="Bỏ bớt cột trùng thông tin hoặc dùng mô hình chịu được đa cộng tuyến.",
        )
    return {c: round(v, 3) for c, v in vif.items()}
