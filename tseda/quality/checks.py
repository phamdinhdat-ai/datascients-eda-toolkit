"""Kiểm tra chất lượng ở mức bảng: dòng trùng, cột trùng, cỡ mẫu, tên cột."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

import pandas as pd

from tseda.core.finding import Severity


def run_quality(ctx) -> dict:
    cfg = ctx.cfg
    df = ctx.df
    n = len(df)
    result: dict = {"n_rows": n, "n_columns": int(df.shape[1])}

    # 1) Dòng trùng hoàn toàn (trên giá trị đã làm sạch)
    cleaned_frame = pd.DataFrame({c: ctx.cleaned[c] for c in df.columns})
    dup_rows = int(cleaned_frame.duplicated().sum())
    result["duplicate_rows"] = dup_rows
    result["duplicate_row_share"] = round(dup_rows / n, 4) if n else 0.0
    if dup_rows:
        ctx.finding(
            "table.duplicate_rows",
            Severity.WARN if dup_rows / n >= 0.01 else Severity.INFO,
            f"Có {dup_rows} dòng trùng hoàn toàn ({dup_rows / n:.2%}).",
            metric={"n": dup_rows, "share": dup_rows / n},
            suggestion="Kiểm tra nguồn có nhân bản dòng khi join hoặc khi ETL chạy lại không.",
        )

    # 2) Cột trùng nội dung (hai cột có cùng giá trị nghĩa là một cột bị sao chép)
    hashes: dict[int, list[str]] = defaultdict(list)
    for c in df.columns:
        s = ctx.typed.get(c, ctx.cleaned[c])
        if s.nunique(dropna=True) <= 1:
            continue
        h = int(pd.util.hash_pandas_object(s.astype(object).where(s.notna(), None), index=False).sum())
        hashes[h].append(c)
    dup_cols = [cols for cols in hashes.values() if len(cols) > 1]
    result["duplicate_columns"] = dup_cols
    if dup_cols:
        ctx.finding(
            "table.duplicate_columns", Severity.WARN,
            f"Có {len(dup_cols)} nhóm cột trùng nội dung: {dup_cols}.",
            metric={"groups": dup_cols},
            suggestion="Giữ một cột trong mỗi nhóm.",
        )

    # 3) Cỡ mẫu
    min_n = int(cfg["general.min_n_for_tests"])
    if n < min_n:
        ctx.finding("table.small_sample", Severity.INFO,
                    f"Bảng chỉ có {n} dòng (dưới {min_n}): chỉ mô tả, không kiểm định.",
                    metric={"n_rows": n})

    # 4) Tên cột: khoảng trắng bên trong, ký tự đặc biệt, có dấu tiếng Việt
    odd_names = [c for c in df.columns
                 if re.search(r"\s|[^\w\s]", c) or _has_accent(c)]
    result["odd_column_names"] = odd_names
    if odd_names:
        ctx.finding(
            "table.column_names", Severity.INFO,
            f"{len(odd_names)} tên cột có khoảng trắng, ký tự đặc biệt hoặc dấu tiếng Việt.",
            metric={"columns": odd_names[:20]},
            suggestion="Chuẩn hóa tên cột (snake_case không dấu) trước khi đưa vào pipeline.",
        )
    return result


def _has_accent(name: str) -> bool:
    return any(unicodedata.category(ch) == "Mn" or ch in "đĐ" for ch in unicodedata.normalize("NFD", name))
