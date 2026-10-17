"""Capability ràng buộc: kiểm tra miền giá trị, đẳng thức, khóa và điều kiện kéo theo.

Nguồn ràng buộc: plugin domain (`domain.constraints(columns, roles)`) và cấu hình `constraints.custom`.
Core không biết nghiệp vụ; nó chỉ thực thi các ràng buộc được khai báo.

Các loại ràng buộc:
  range       {type, column, min?, max?}
  nonnegative {type, column}
  identity    {type, columns: [..], total: col, tol: 0.01}   sum(columns) == total (sai số tương đối)
  unique      {type, columns: [..]}                           khóa không trùng
  product     {type, columns: [a, b], total: c, tol: 0.001}   a * b == c
  order       {type, lower: a, upper: b}                      a <= b
  implies     {type, if: {column, op, value}, then: {column, op}}   op: notna | isna | > | >= | < | <= | ==
"""
from __future__ import annotations

import operator

import pandas as pd

from tseda.core.finding import Severity
from tseda.core.registry import register_capability

_OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq}


def _num(ctx, col: str) -> pd.Series:
    return pd.to_numeric(ctx.typed[col], errors="coerce").astype("float64")


def _check(ctx, rule: dict) -> dict | None:
    kind = rule.get("type")
    name = rule.get("name") or f"{kind}:{rule.get('column') or rule.get('columns')}"
    cols = [rule["column"]] if "column" in rule else list(rule.get("columns", []))
    if "total" in rule:
        cols.append(rule["total"])
    if kind == "order":
        cols = [rule["lower"], rule["upper"]]
    if kind == "implies":
        cols += [rule["if"]["column"], rule["then"]["column"]]
    missing = [c for c in cols if c not in ctx.typed]
    if missing:
        ctx.decide("table", "constraints", f"bỏ qua '{name}'", "thiếu cột", missing=missing)
        return None

    mask = None
    if kind in ("range", "nonnegative"):
        s = _num(ctx, rule["column"])
        lo = rule.get("min", 0.0 if kind == "nonnegative" else None)
        hi = rule.get("max")
        valid = s.notna()
        bad = pd.Series(False, index=s.index)
        if lo is not None:
            bad |= s < lo
        if hi is not None:
            bad |= s > hi
        mask = valid
        violations = bad & valid
    elif kind == "identity":
        parts = pd.DataFrame({c: _num(ctx, c) for c in rule["columns"]})
        total = _num(ctx, rule["total"])
        valid = parts.notna().all(axis=1) & total.notna()
        diff = (parts.sum(axis=1) - total).abs()
        tol = float(rule.get("tol", 0.01))
        violations = (diff > tol * total.abs().clip(lower=1.0)) & valid
        mask = valid
    elif kind == "product":
        a = _num(ctx, rule["columns"][0])
        b = _num(ctx, rule["columns"][1])
        total = _num(ctx, rule["total"])
        valid = a.notna() & b.notna() & total.notna()
        tol = float(rule.get("tol", 0.001))
        diff = (a * b - total).abs()
        violations = (diff > tol * total.abs().clip(lower=1.0)) & valid
        mask = valid
    elif kind == "order":
        lo = _num(ctx, rule["lower"])
        hi = _num(ctx, rule["upper"])
        valid = lo.notna() & hi.notna()
        violations = (lo > hi) & valid
        mask = valid
    elif kind == "unique":
        keys = pd.DataFrame({c: ctx.typed[c].astype(str) for c in rule["columns"]})
        valid = ctx.typed[rule["columns"][0]].notna()
        violations = keys.duplicated(keep=False) & valid
        mask = valid
    elif kind == "implies":
        cond = rule["if"]
        then = rule["then"]
        c_series = ctx.typed[cond["column"]]
        if cond["op"] in ("notna", "isna"):
            cond_mask = c_series.notna() if cond["op"] == "notna" else c_series.isna()
        else:
            cond_mask = _OPS[cond["op"]](_num(ctx, cond["column"]), cond["value"]).fillna(False)
        t_series = ctx.typed[then["column"]]
        if then["op"] == "notna":
            ok = t_series.notna()
        elif then["op"] == "isna":
            ok = t_series.isna()
        else:
            ok = _OPS[then["op"]](_num(ctx, then["column"]), then["value"]).fillna(False)
        mask = cond_mask.astype(bool)
        violations = mask & ~ok.astype(bool)
    else:
        ctx.decide("table", "constraints", f"bỏ qua '{name}'", f"loại ràng buộc không hỗ trợ: {kind}")
        return None

    n_checked = int(mask.sum())
    n_viol = int(violations.sum())
    examples = []
    if n_viol:
        idx = violations[violations].index[:5]
        examples = [{"row": int(i)} for i in idx]
    return {"name": name, "type": kind, "columns": cols, "n_checked": n_checked,
            "n_violations": n_viol, "share": round(n_viol / n_checked, 6) if n_checked else 0.0,
            "examples": examples}


@register_capability("constraints")
def constraints_capability(ctx):
    rules: list[dict] = []
    if ctx.domain is not None:
        rules += list(ctx.domain.constraints(list(ctx.typed.keys()), ctx.roles) or [])
    rules += list(ctx.cfg.get("constraints.custom", []) or [])
    if not rules:
        ctx.decide("table", "capability.constraints", "không bật", "không có ràng buộc nào được khai báo")
        return None

    critical = float(ctx.cfg["constraints.critical_share"])
    results = []
    for rule in rules:
        res = _check(ctx, rule)
        if res is None:
            continue
        results.append(res)
        if res["n_violations"]:
            sev = Severity.CRITICAL if res["share"] >= critical else Severity.WARN
            ctx.finding("constraint.violation", sev,
                        f"Ràng buộc '{res['name']}' bị vi phạm ở {res['n_violations']}/{res['n_checked']} dòng ({res['share']:.2%}).",
                        scope=res["name"], metric=res,
                        suggestion="Kiểm tra quy tắc nghiệp vụ và nguồn tạo số liệu. Không tự sửa.")
    return {"rules": results}
