"""Ánh xạ thực thể dùng chung cho temporal, panel và dashboard.

Chỉ gộp các biến thể có CÙNG khóa chuẩn hóa (khác dấu, hoa thường, khoảng trắng) — ví dụ 'Hà Nội' / 'Ha Noi' / 'HÀ NỘI'.
Các nhóm chỉ 'gần giống' theo khoảng cách chuỗi (lỗi gõ) KHÔNG được gộp tự động, vì có thể gộp nhầm hai thực thể khác nhau.
"""
from __future__ import annotations

import pandas as pd


def entity_mapping(ctx, col: str) -> dict[str, str]:
    """{giá trị gốc: giá trị chuẩn} cho các nhóm biến thể đạt tiêu chí gộp tự động."""
    mapping: dict[str, str] = {}
    for g in ctx.profiles.get(col, {}).get("variant_groups", []):
        if g.get("method") != "accent_case_space":
            continue
        canonical = str(g["canonical"])
        for m in g["members"]:
            mapping[str(m["value"])] = canonical
    return mapping


def entity_series(ctx, col: str) -> pd.Series:
    """Chuỗi thực thể đã gộp biến thể; giá trị thiếu giữ nguyên."""
    s = ctx.typed[col]
    mapping = entity_mapping(ctx, col)
    if not mapping:
        return s
    return s.map(lambda v: mapping.get(str(v), v) if pd.notna(v) else v)
