"""Phần chung của mọi profile cột: thiếu dữ liệu, sentinel, vai trò và confidence."""
from __future__ import annotations

import pandas as pd

from tseda.core.finding import Severity
from tseda.core.roles import Role, RoleGuess


def base_profile(ctx, name: str, typed: pd.Series, guess: RoleGuess, info: dict) -> dict:
    clean = ctx.clean_info.get(name, {})
    n_rows = int(len(typed))
    n_missing = int(typed.isna().sum())
    missing_share = n_missing / n_rows if n_rows else 0.0
    profile = {
        "column": name,
        "role": guess.role.value,
        "family": guess.family,
        "role_confidence": guess.confidence,
        "role_source": guess.source,
        "role_alternatives": [(r.value, s) for r, s in guess.alternatives],
        "role_evidence": guess.evidence,
        "n_rows": n_rows,
        "n_missing": n_missing,
        "missing_share": round(missing_share, 4),
        "n_sentinel_strings": int(clean.get("sentinel_strings", 0)),
        "sentinel_examples": clean.get("sentinel_examples", []),
        "n_unique": int(typed.nunique(dropna=True)),
        "coerce": info,
        "stats": {},
    }
    if missing_share >= float(ctx.cfg["missing.high_null_share"]):
        ctx.finding(
            "missing.high", Severity.WARN,
            f"Cột '{name}' thiếu {missing_share:.1%} giá trị (gồm cả chuỗi sentinel và parse lỗi).",
            scope=name, metric={"missing_share": missing_share, "n_missing": n_missing},
            suggestion="Kiểm tra nguồn: thiếu có phải do nghiệp vụ (chưa phát sinh) hay do lỗi ETL?",
        )
    if guess.confidence < float(ctx.cfg["typing.min_confidence"]):
        ctx.finding(
            "typing.low_confidence", Severity.WARN,
            f"Cột '{name}' được suy là '{guess.role.value}' với confidence {guess.confidence:.2f}, thấp hơn ngưỡng.",
            scope=name,
            metric={"alternatives": [(r.value, s) for r, s in guess.alternatives]},
            suggestion="Xác nhận vai trò đúng bằng schema khai báo thủ công.",
        )
    return profile


def sentinel_numbers_hit(values: pd.Series, sentinel_numbers: list) -> dict[float, int]:
    hits: dict[float, int] = {}
    for s in sentinel_numbers:
        c = int((values == s).sum())
        if c:
            hits[float(s)] = c
    return hits
