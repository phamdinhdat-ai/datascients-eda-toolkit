"""Dựng dữ liệu nhúng cho dashboard: KPI, metadata cột, mẫu dòng đã ép kiểu, quan hệ và phát hiện.

Mọi giá trị đi qua hàm chuẩn hóa ở đây, nên JSON luôn hợp lệ (không NaN/Inf) và chuỗi đã được cắt độ dài.
Khi bảng lớn hơn `dashboard.max_rows`, mẫu được lấy ngẫu nhiên có seed cố định và được ghi rõ trong `meta`.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from tseda.core.util import to_jsonable

KIND_BY_FAMILY = {
    "numeric": "numeric",
    "categorical": "categorical",
    "boolean": "boolean",
    "datetime": "datetime",
    "text": "text",
    "id": "id",
    "mixed": "mixed",
    "constant": "other",
    "empty": "other",
}

_KIND_LABEL = {
    "numeric": "số",
    "categorical": "phân loại",
    "boolean": "cờ (đúng/sai)",
    "datetime": "ngày giờ",
    "text": "văn bản",
    "id": "mã định danh",
    "mixed": "hỗn hợp",
    "other": "khác",
}


def _num(x: Any) -> float | None:
    """Số hữu hạn làm tròn 6 chữ số có nghĩa; NaN/Inf/NA trở thành None."""
    if x is None or pd.isna(x):
        return None
    f = float(x)
    if not math.isfinite(f):
        return None
    return float(f"{f:.6g}")


def _values_for_kind(series: pd.Series, kind: str, max_chars: int) -> list:
    out: list = []
    if kind in ("numeric", "mixed"):
        out = [_num(v) for v in series.tolist()]
    elif kind == "boolean":
        out = [None if pd.isna(v) else bool(v) for v in series.tolist()]
    elif kind == "datetime":
        s = pd.to_datetime(series, errors="coerce")
        valid = s.dropna()
        date_only = bool(len(valid)) and bool((valid == valid.dt.normalize()).all())
        fmt = "%Y-%m-%d" if date_only else "%Y-%m-%dT%H:%M:%S"
        out = [None if pd.isna(v) else v.strftime(fmt) for v in s.tolist()]
    else:
        out = [None if (v is None or (not isinstance(v, str) and pd.isna(v))) else str(v)[:max_chars]
               for v in series.tolist()]
    return out


def _levels(values: list, max_levels: int) -> list[dict] | None:
    """Danh sách level sắp theo tần suất cho bộ lọc; None nếu quá nhiều level."""
    counts: dict[Any, int] = {}
    for v in values:
        if v is None:
            continue
        counts[v] = counts.get(v, 0) + 1
    if not counts or len(counts) > max_levels:
        return None
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return [{"value": k, "count": c} for k, c in ordered]


def _scalar_capabilities(capabilities: dict) -> dict:
    """Giữ các trường vô hướng và danh sách nhỏ để hiển thị; bỏ phần dữ liệu lớn."""
    out: dict = {}
    for name, cap in capabilities.items():
        if not isinstance(cap, dict):
            continue
        facts = {}
        for k, v in cap.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                facts[k] = v
            elif isinstance(v, list) and len(v) <= 20:
                facts[k] = to_jsonable(v)
            elif isinstance(v, dict) and len(v) <= 20 and all(isinstance(x, (int, float, str)) for x in v.values()):
                facts[k] = to_jsonable(v)
        out[name] = facts
    return to_jsonable(out)


def _findings(report) -> list[dict]:
    rows = []
    for f in report.findings:
        rows.append({"severity": f.severity.name, "id": f.id, "scope": f.scope,
                     "message": f.message, "suggestion": f.suggestion or ""})
    order = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
    rows.sort(key=lambda r: order.get(r["severity"], 3))
    return rows


def _relations(report) -> list[dict]:
    rows = []
    for r in report.relations:
        t = r.test
        rows.append({
            "col_a": r.col_a, "col_b": r.col_b, "kind": r.kind,
            "test": t.name if t else None,
            "effect": _num(t.effect) if t else None,
            "effect_name": t.effect_name if t else None,
            "p_value": _num(t.p_value) if t else None,
            "q_value": _num(r.q_value),
            "significant": bool(r.significant),
            "n": int(t.n) if t and t.n is not None else None,
        })
    rows.sort(key=lambda r: (not r["significant"], -abs(r["effect"] or 0.0)))
    return rows


def _time_and_entity(report, columns: list[dict]) -> dict:
    temporal = report.capabilities.get("temporal", {}) or {}
    panel = report.capabilities.get("panel", {}) or {}
    time_col = temporal.get("time_column") or panel.get("time_column")
    entity_col = temporal.get("entity_column") or panel.get("entity_column")
    if time_col is None:
        dt = [c["name"] for c in columns if c["kind"] == "datetime"]
        time_col = dt[0] if dt else None
    entity_map = (temporal.get("entity_map") or panel.get("entity_map") or {}) if entity_col else {}
    return {"time_column": time_col, "entity_column": entity_col, "entity_map": entity_map}


def build_payload(report, cfg) -> dict:
    max_rows = int(cfg["dashboard.max_rows"])
    max_cols = int(cfg["dashboard.max_columns"])
    max_levels = int(cfg["dashboard.max_levels"])
    max_chars = int(cfg["dashboard.max_text_chars"])
    seed = int(cfg["general.seed"])

    typed: pd.DataFrame = report.typed
    n_total = len(typed)
    if n_total > max_rows:
        sample = typed.sample(n=max_rows, random_state=seed).sort_index()
    else:
        sample = typed
    sampled = len(sample) < n_total

    all_names = list(typed.columns)
    shown_names = all_names[:max_cols]

    columns: list[dict] = []
    for name in shown_names:
        guess = report.roles[name]
        kind = KIND_BY_FAMILY.get(guess.family, "other")
        series = sample[name]
        values = _values_for_kind(series, kind, max_chars)
        prof = report.profiles.get(name, {})
        entry: dict[str, Any] = {
            "name": str(name),
            "role": guess.role.value,
            "kind": kind,
            "kind_label": _KIND_LABEL.get(kind, kind),
            "confidence": round(float(guess.confidence), 3),
            "missing_share": _num(prof.get("missing_share")),
            "n_unique": int(prof.get("n_unique") or series.nunique(dropna=True)),
            "values": values,
        }
        if kind in ("categorical", "boolean", "text", "id", "mixed"):
            entry["levels"] = _levels(values, max_levels)
        if kind == "numeric" or kind == "mixed":
            nums = [v for v in values if v is not None]
            entry["min"] = min(nums) if nums else None
            entry["max"] = max(nums) if nums else None
            entry["text_part_count"] = (prof.get("coerce") or {}).get("text_part_count")
        if kind == "datetime":
            present = [v for v in values if v is not None]
            entry["min"] = min(present) if present else None
            entry["max"] = max(present) if present else None
        columns.append(entry)

    te = _time_and_entity(report, columns)

    # Số dòng trùng toàn bảng lấy từ quality; nếu không có thì để None.
    dup_rows = report.quality.get("duplicate_rows")
    missing_shares = [c["missing_share"] for c in columns if c["missing_share"] is not None]
    kpis = {
        "rows": int(n_total),
        "columns": int(len(all_names)),
        "missing_share_mean": _num(float(np.mean(missing_shares))) if missing_shares else None,
        "duplicate_rows": int(dup_rows) if dup_rows is not None else None,
        "n_critical": sum(1 for f in report.findings if f.severity.name == "CRITICAL"),
        "n_warn": sum(1 for f in report.findings if f.severity.name == "WARN"),
        "n_info": sum(1 for f in report.findings if f.severity.name == "INFO"),
    }

    meta = {
        "name": str(report.name),
        "source": str(report.source),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sample_rows": int(len(sample)),
        "total_rows": int(n_total),
        "sampled": bool(sampled),
        "columns_total": int(len(all_names)),
        "columns_truncated": len(all_names) > len(shown_names),
        "stages_run": list(report.stages_run),
        "stage_errors": [str(e) for e in report.stage_errors],
        "series_max": int(cfg["dashboard.series_max"]),
        "histogram_bins": int(cfg["dashboard.histogram_bins"]),
        "heatmap_max_columns": int(cfg["dashboard.heatmap_max_columns"]),
        "table_preview_rows": int(cfg["dashboard.table_preview_rows"]),
        "time_column": te["time_column"],
        "entity_column": te["entity_column"],
        "entity_map": te["entity_map"],
    }

    return {
        "meta": meta,
        "kpis": kpis,
        "columns": columns,
        "capabilities": _scalar_capabilities(report.capabilities),
        "relations": _relations(report),
        "findings": _findings(report),
    }
