"""Capability phân cấp: kiểm tra phụ thuộc hàm giữa các cột phân loại (ví dụ xã -> huyện -> tỉnh).

child -> parent là phụ thuộc hàm nếu mỗi giá trị child chỉ thuộc một parent.
Số dòng vi phạm tối thiểu = tổng số dòng - tổng số dòng của parent chiếm đa số trong mỗi child.
"""
from __future__ import annotations

import pandas as pd

from tseda.core.finding import Severity
from tseda.core.registry import register_capability
from tseda.core.roles import Role

MAX_COLUMNS = 15


def violation_count(child: pd.Series, parent: pd.Series) -> tuple[int, int, list[dict]]:
    frame = pd.DataFrame({"c": child, "p": parent}).dropna().astype(str)
    counts = frame.groupby(["c", "p"]).size()
    total = int(counts.sum())
    best_per_child = counts.groupby(level="c").max()
    minimal_violations = total - int(best_per_child.sum())
    ambiguous = counts.groupby(level="c").size()
    examples = []
    for c in ambiguous[ambiguous > 1].index[:5]:
        examples.append({"child": c, "parents": counts.loc[c].sort_values(ascending=False).head(3).to_dict()})
    return minimal_violations, total, examples


@register_capability("hierarchy")
def hierarchy_capability(ctx):
    cfg = ctx.cfg
    max_card = int(cfg["hierarchy.max_cardinality"])
    tol = float(cfg["hierarchy.violation_tolerance"])
    cats = []
    for c, g in ctx.roles.items():
        if g.role not in (Role.CATEGORICAL_NOMINAL, Role.CATEGORICAL_ORDINAL) or c not in ctx.typed:
            continue
        nun = int(ctx.typed[c].nunique(dropna=True))
        if 2 <= nun <= max_card:
            cats.append((nun, c))
    cats = [c for _, c in sorted(cats)][:MAX_COLUMNS]
    if len(cats) < 2:
        ctx.decide("table", "capability.hierarchy", "không bật", "ít hơn hai cột phân loại")
        return None

    links = []
    for child in cats:
        for parent in cats:
            if child == parent:
                continue
            n_child = int(ctx.typed[child].nunique(dropna=True))
            n_parent = int(ctx.typed[parent].nunique(dropna=True))
            if n_parent >= n_child:
                continue  # parent phải có ít level hơn child
            viol, total, examples = violation_count(ctx.typed[child], ctx.typed[parent])
            if total < 30:
                continue
            share = viol / total
            if share > tol:
                continue
            links.append({"child": child, "parent": parent, "violation_rows": viol,
                          "violation_share": round(share, 6), "n_child_levels": n_child, "n_parent_levels": n_parent,
                          "examples": examples})

    result = {"links": links, "columns_checked": cats}
    for link in links:
        scope = f"pair:{link['child']}|{link['parent']}"
        if link["violation_rows"] == 0:
            ctx.finding("hierarchy.confirmed", Severity.INFO,
                        f"'{link['child']}' thuộc đúng một '{link['parent']}': cấu trúc phân cấp nhất quán.",
                        scope=scope, metric=link,
                        suggestion="Có thể dùng để tổng hợp theo cấp hoặc kiểm tra mapping.")
        else:
            ctx.finding("hierarchy.violations", Severity.WARN,
                        f"'{link['child']}' gần như thuộc một '{link['parent']}' nhưng có {link['violation_rows']} dòng vi phạm "
                        f"({link['violation_share']:.2%}).",
                        scope=scope, metric=link,
                        suggestion="Xem các giá trị child có nhiều parent. Thường là lỗi nhập hoặc đổi tên đơn vị hành chính.")
    return result
