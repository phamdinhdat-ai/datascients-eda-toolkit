"""Capability panel: dữ liệu nhiều thực thể theo thời gian (mã CK, tài khoản, chi nhánh...)."""
from __future__ import annotations

import pandas as pd

from tseda.capability.entity import entity_mapping, entity_series
from tseda.capability.temporal import pick_entity_column, pick_time_column
from tseda.core.finding import Severity
from tseda.core.registry import register_capability


@register_capability("panel")
def panel_capability(ctx):
    cfg = ctx.cfg
    time_col = pick_time_column(ctx)
    if time_col is None:
        ctx.decide("table", "capability.panel", "không bật", "không có cột thời gian")
        return None
    entity, _ = pick_entity_column(ctx, time_col)
    if entity is None:
        ctx.decide("table", "capability.panel", "không bật", "không tìm thấy cột thực thể lặp lại theo thời gian")
        return None

    frame = pd.DataFrame({"e": entity_series(ctx, entity), "t": ctx.typed[time_col]}).dropna(subset=["e", "t"])
    if frame["e"].nunique() < int(cfg["panel.min_entities"]):
        ctx.decide("table", "capability.panel", "không bật", "quá ít thực thể")
        return None

    rows = frame.groupby("e").size()
    first = frame.groupby("e")["t"].min()
    last = frame.groupby("e")["t"].max()
    span_start, span_end = frame["t"].min(), frame["t"].max()
    span_days = max((span_end - span_start).days, 1)
    late_start = (first - span_start).dt.days / span_days > 0.1
    short_min = int(cfg["panel.short_history_min"])
    short = rows[rows < short_min]
    dup_keys = int(frame.duplicated(subset=["e", "t"]).sum())

    numeric_cols = [c for c, g in ctx.roles.items() if g.family == "numeric" and c in ctx.typed]
    entity_missing: dict[str, float] = {}
    if numeric_cols:
        miss = pd.DataFrame({c: ctx.typed[c].isna() for c in numeric_cols})
        miss["e"] = entity_series(ctx, entity)
        per_entity = miss.groupby("e")[numeric_cols].mean()
        entity_missing = {c: round(float(per_entity[c].max()), 4) for c in numeric_cols}

    result = {
        "entity_column": entity,
        "entity_map": entity_mapping(ctx, entity),
        "time_column": time_col,
        "n_entities": int(rows.size),
        "rows_per_entity": {"min": int(rows.min()), "median": float(rows.median()),
                            "max": int(rows.max())},
        "balance_ratio": round(float(rows.min() / rows.max()), 4),
        "n_short_history": int(short.size),
        "n_late_start": int(late_start.sum()),
        "n_last_before_span_end": int((last < span_end).sum()),
        "duplicate_entity_time_keys": dup_keys,
        "max_missing_share_by_entity": entity_missing,
    }
    ctx.decide("table", "capability.panel", f"bật theo thực thể '{entity}'", "có nhiều thực thể lặp lại theo thời gian",
               n_entities=result["n_entities"])

    if dup_keys:
        ctx.finding("panel.duplicate_keys", Severity.CRITICAL,
                    f"{dup_keys} cặp ({entity}, {time_col}) bị trùng: không thể dùng làm khóa panel.",
                    scope=entity, metric={"n": dup_keys},
                    suggestion="Xác định nguyên nhân: nhiều bản ghi cùng ngày hay nhân bản khi join.")
    if result["n_short_history"]:
        ctx.finding("panel.short_history", Severity.INFO,
                    f"{result['n_short_history']}/{result['n_entities']} thực thể có dưới {short_min} kỳ quan sát.",
                    scope=entity, metric={"n": result["n_short_history"], "examples": list(short.index[:10].astype(str))},
                    suggestion="Thực thể lịch sử ngắn làm nhiễu thống kê theo thực thể. Cân nhắc loại hoặc gom.")
    if result["balance_ratio"] < 0.1:
        ctx.finding("panel.unbalanced", Severity.INFO,
                    f"Panel mất cân bằng mạnh: thực thể ít nhất có {result['balance_ratio']:.1%} số dòng của thực thể nhiều nhất.",
                    scope=entity, metric=result["rows_per_entity"])
    if result["n_late_start"]:
        ctx.finding("panel.late_start", Severity.INFO,
                    f"{result['n_late_start']} thực thể bắt đầu muộn (sau 10% khoảng thời gian chung).",
                    scope=entity, metric={"n": result["n_late_start"]},
                    suggestion="Kiểm tra có phải thực thể mới niêm yết/mở, hay dữ liệu bị thiếu từ đầu.")
    worst = {c: v for c, v in entity_missing.items() if v >= float(cfg["missing.high_null_share"])}
    if worst:
        ctx.finding("panel.entity_missing", Severity.WARN,
                    f"Có thực thể thiếu quá nửa dữ liệu ở các cột: {list(worst)}.",
                    scope=entity, metric={"max_missing_share_by_entity": worst},
                    suggestion="Loại các thực thể này khỏi phân tích hoặc xác nhận nguyên nhân.")
    return result
