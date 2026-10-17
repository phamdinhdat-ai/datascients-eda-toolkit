"""Capability chuỗi thời gian. Chỉ bật khi có cột ngày đủ dữ liệu.

Nội dung: tần suất và ngày thiếu theo lịch, timestamp trùng, chuỗi giá trị đóng băng,
xu hướng (Kendall/Mann-Kendall), tính dừng (ADF+KPSS), mùa vụ, điểm đứt gãy ứng viên.
Nếu có cột thực thể (mã CK, tài khoản, chi nhánh) thì phân tích theo từng thực thể.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tseda.capability.entity import entity_mapping, entity_series

from tseda.core.finding import Severity
from tseda.core.registry import register_capability
from tseda.core.roles import Role
from tseda.stats import tests as st
from tseda.stats import timeseries as ts

MAX_ENTITIES_ANALYSED = 50
MAX_NUMERIC_COLUMNS = 10
MAX_STATIONARITY_COLUMNS = 3   # ADF/KPSS tốn kém: chỉ chạy cho vài cột đầu


def pick_time_column(ctx) -> str | None:
    override = ctx.cfg.get("general.time_column")
    if override:
        return override if override in ctx.typed and pd.api.types.is_datetime64_any_dtype(ctx.typed[override]) else None
    dt_cols = [c for c, g in ctx.roles.items() if g.role == Role.DATETIME and c in ctx.typed]
    if not dt_cols:
        return None
    return max(dt_cols, key=lambda c: ctx.typed[c].notna().mean())


def pick_entity_column(ctx, time_col: str) -> tuple[str | None, list[str]]:
    """Cột thực thể: phân loại có nhiều level nhưng mỗi level vẫn đủ dòng để có lịch sử."""
    override = ctx.cfg.get("general.entity_column")
    if override:
        return (override if override in ctx.typed else None), []
    n_time = int(ctx.typed[time_col].notna().sum())
    min_hist = int(ctx.cfg["panel.short_history_min"])
    max_levels = max(2, n_time // max(min_hist, 1))
    candidates = []
    for c, g in ctx.roles.items():
        if c == time_col or c not in ctx.typed or g.role != Role.CATEGORICAL_NOMINAL:
            continue
        nun = int(entity_series(ctx, c).nunique(dropna=True))
        if 2 <= nun <= max_levels:
            candidates.append((nun, c))
    if not candidates:
        return None, []
    # Thực thể đúng là cột mà cặp (thực thể, thời gian) gần như duy nhất.
    # Cột phân nhóm như chi nhánh có nhiều dòng cùng ngày nên bị loại ở đây.
    t = ctx.typed[time_col]
    scored = []
    for nun, c in candidates:
        frame = pd.DataFrame({"e": entity_series(ctx, c), "t": t}).dropna()
        dup_share = float(frame.duplicated(subset=["e", "t"]).mean()) if len(frame) else 1.0
        scored.append((dup_share, -nun, c))
    unique_keys = sorted([s for s in scored if s[0] <= 0.02], key=lambda s: (s[1], s[0]))
    if not unique_keys:
        ctx.decide("table", "entity", "không chọn được cột thực thể",
                   "không cột nào có cặp (thực thể, thời gian) gần như duy nhất")
        return None, [c for *_, c in scored]
    chosen = unique_keys[0][2]
    return chosen, [c for *_, c in scored if c != chosen]


def _freq_label(days_median: float) -> str:
    if days_median <= 1.5:
        return "D"
    if 5 <= days_median <= 9:
        return "W"
    if 25 <= days_median <= 35:
        return "M"
    if 85 <= days_median <= 95:
        return "Q"
    if 360 <= days_median <= 370:
        return "Y"
    return "irregular"


def period_gaps(times: pd.Series, calendar: str, holidays: set) -> dict:
    t = pd.Series(times).dropna().sort_values()
    if len(t) < 3:
        return {"freq": None, "n_missing": 0, "missing_share": 0.0, "examples": []}
    uniq = t.drop_duplicates()
    med = float(uniq.diff().dropna().dt.total_seconds().median() / 86400)
    freq = _freq_label(med)
    if freq == "irregular":
        return {"freq": freq, "median_gap_days": round(med, 3), "n_missing": 0, "missing_share": 0.0, "examples": []}

    if freq == "D":
        days = pd.DatetimeIndex(t.dt.normalize().unique())
        full = pd.bdate_range(days.min(), days.max()) if calendar == "business" else pd.date_range(days.min(), days.max(), freq="D")
        missing = full.difference(days)
        if holidays:
            missing = missing[~missing.isin(list(holidays))]
        expected = len(full)
        examples = [d.date().isoformat() for d in missing[:10]]
    else:
        periods = t.dt.to_period(freq)
        full = pd.period_range(periods.min(), periods.max(), freq=freq)
        missing = full.difference(pd.PeriodIndex(periods.unique(), freq=freq))
        expected = len(full)
        examples = [str(p) for p in missing[:10]]
    n_missing = int(len(missing))
    return {"freq": freq, "expected_periods": int(expected), "n_missing": n_missing,
            "missing_share": round(n_missing / expected, 4) if expected else 0.0,
            "examples": examples, "median_gap_days": round(med, 3)}


def stale_runs(values: np.ndarray, times: pd.Series, min_len: int) -> dict:
    v = pd.Series(values)
    valid = v.notna().to_numpy()
    if valid.sum() < 2:
        return {"n_runs": 0, "longest": 0}
    v = v[valid].reset_index(drop=True)
    tt = pd.Series(times).reset_index(drop=True)[valid].reset_index(drop=True)
    run_id = (v != v.shift()).cumsum()
    lengths = run_id.value_counts()
    long_ids = lengths[lengths >= min_len].index
    if len(long_ids) == 0:
        return {"n_runs": 0, "longest": int(lengths.max())}
    first_dates = []
    for rid in long_ids[:5]:
        pos = run_id[run_id == rid].index[0]
        first_dates.append(str(tt.iloc[pos].date()))
    return {"n_runs": int(len(long_ids)), "longest": int(lengths[long_ids].max()),
            "example_start_dates": first_dates, "value": float(v[run_id == long_ids[0]].iloc[0])}


def _analyse_series(ctx, times: pd.Series, numeric_cols: list[str], frame: pd.DataFrame, label: str,
                    full: bool) -> dict:
    cfg = ctx.cfg
    alpha = float(cfg["general.alpha"])
    holidays = set(pd.to_datetime(list(cfg["temporal.holidays"]))) if cfg["temporal.holidays"] else set()
    out: dict = {"label": label, "n_obs": int(len(frame)), "columns": {}}
    order = np.argsort(times.values, kind="stable")
    t_sorted = times.iloc[order].reset_index(drop=True)
    out["duplicate_timestamps"] = int(t_sorted.duplicated().sum())
    out["gaps"] = period_gaps(t_sorted, str(cfg["temporal.calendar"]), holidays)
    days = (t_sorted - t_sorted.min()).dt.total_seconds().to_numpy() / 86400.0

    for col_idx, c in enumerate(numeric_cols):
        vals = frame[c].to_numpy(dtype=float)[order]
        col: dict = {}
        col["stale"] = stale_runs(vals, t_sorted, int(cfg["missing.stale_run_min_length"]))
        col["trend"] = st.trend(days, vals).to_dict()
        if full:
            clean = vals[~np.isnan(vals)]
            if col_idx < MAX_STATIONARITY_COLUMNS and len(clean) >= int(cfg["temporal.stationarity_min_n"]):
                col["stationarity"] = ts.stationarity(clean, alpha)
            col["seasonal"] = ts.seasonal_candidates(clean, list(cfg["temporal.seasonal_lags"]),
                                                     float(cfg["temporal.seasonal_min_strength"]))
            brk = ts.break_candidate(clean, int(cfg["temporal.break_min_segment"]))
            if brk is not None:
                ix_valid = np.where(~np.isnan(vals))[0]
                pos = ix_valid[brk["index"]] if brk["index"] < len(ix_valid) else len(t_sorted) - 1
                brk["date"] = str(t_sorted.iloc[pos].date())
                col["break"] = brk
        out["columns"][c] = col
    return out


@register_capability("temporal")
def temporal_capability(ctx):
    cfg = ctx.cfg
    time_col = pick_time_column(ctx)
    min_rows = int(cfg["temporal.min_rows"])
    if time_col is None:
        ctx.decide("table", "capability.temporal", "không bật", "không có cột ngày")
        return None
    if int(ctx.typed[time_col].notna().sum()) < min_rows:
        ctx.decide("table", "capability.temporal", "không bật", f"cột ngày có ít hơn {min_rows} giá trị hợp lệ")
        return None

    numeric_cols = [c for c, g in ctx.roles.items() if g.family == "numeric" and c in ctx.typed][:MAX_NUMERIC_COLUMNS]
    entity, others = pick_entity_column(ctx, time_col)
    ctx.decide("table", "capability.temporal", f"bật, cột thời gian={time_col}",
               "có cột ngày đủ dữ liệu", entity=entity, numeric_columns=numeric_cols,
               alternative_entities=others)

    used = list(dict.fromkeys([time_col] + numeric_cols + ([entity] if entity else [])))
    frame = pd.DataFrame({c: (entity_series(ctx, c) if c == entity else ctx.typed[c]) for c in used})
    frame = frame[frame[time_col].notna()]
    result: dict = {"time_column": time_col, "entity_column": entity, "series": [],
                    "entity_map": entity_mapping(ctx, entity) if entity else {}}

    if entity:
        groups = frame.groupby(entity, sort=False)
        sizes = groups.size().sort_values(ascending=False)
        analysed = [k for k in sizes.index if sizes[k] >= min_rows][:MAX_ENTITIES_ANALYSED]
        if len(sizes) > MAX_ENTITIES_ANALYSED:
            ctx.decide("table", "temporal.entities", f"phân tích {MAX_ENTITIES_ANALYSED}/{len(sizes)} thực thể lớn nhất",
                       "giới hạn chi phí tính toán")
        largest = analysed[0] if analysed else None
        for key in analysed:
            sub = groups.get_group(key)
            res = _analyse_series(ctx, sub[time_col], numeric_cols, sub, str(key), full=(key == largest))
            result["series"].append(res)
    else:
        if len(frame) < min_rows:
            return None
        res = _analyse_series(ctx, frame[time_col], numeric_cols, frame, "table", full=True)
        result["series"].append(res)

    _emit_temporal_findings(ctx, result)
    return result


def _emit_temporal_findings(ctx, result: dict) -> None:
    alpha = float(ctx.cfg["general.alpha"])
    dup_total = sum(s["duplicate_timestamps"] for s in result["series"])
    if dup_total:
        ctx.finding("temporal.duplicate_timestamps", Severity.WARN,
                    f"{dup_total} timestamp bị trùng trong chuỗi thời gian.",
                    metric={"n": dup_total},
                    suggestion="Kiểm tra có phải nhiều bản ghi cùng thời điểm (ví dụ nhiều giao dịch) hay do nhân bản.")

    gap_entries = [(s["label"], s["gaps"]) for s in result["series"] if s["gaps"].get("n_missing")]
    if gap_entries:
        worst = max(gap_entries, key=lambda kv: kv[1].get("missing_share", 0))
        share = worst[1].get("missing_share", 0)
        ctx.finding("temporal.gaps", Severity.WARN if share >= 0.05 else Severity.INFO,
                    f"{len(gap_entries)} chuỗi thiếu kỳ theo lịch '{worst[1].get('freq')}'. "
                    f"Tệ nhất: {worst[0]} thiếu {share:.1%}.",
                    metric={"n_series_with_gaps": len(gap_entries), "worst": worst[0], "share": share,
                            "examples": worst[1].get("examples", [])},
                    suggestion="Nếu thiếu vào ngày nghỉ, khai báo temporal.holidays. Nếu không, kiểm tra ETL.")

    for s in result["series"]:
        for c, col in s["columns"].items():
            stale = col.get("stale", {})
            if stale.get("n_runs"):
                ctx.finding("temporal.stale", Severity.WARN,
                            f"'{c}' ({s['label']}): {stale['n_runs']} chuỗi giá trị đóng băng, dài nhất {stale['longest']} kỳ.",
                            scope=c, metric=stale,
                            suggestion="Dữ liệu đóng băng thường là lỗi nguồn hoặc không cập nhật. Kiểm tra trước khi tin.")
            tr = col.get("trend", {})
            if tr.get("p_value") is not None and tr["p_value"] < alpha and abs(tr.get("effect") or 0) >= 0.3:
                ctx.finding("temporal.trend", Severity.INFO,
                            f"'{c}' ({s['label']}) có xu hướng {'tăng' if tr['effect'] > 0 else 'giảm'} (tau={tr['effect']:.2f}).",
                            scope=c, metric=tr)
            stat = col.get("stationarity")
            if stat and stat.get("conclusion", "").startswith("không dừng"):
                ctx.finding("temporal.nonstationary", Severity.INFO,
                            f"'{c}' ({s['label']}) không dừng: cân nhắc sai phân hoặc mô hình hóa xu hướng.",
                            scope=c, metric={k: stat.get(k) for k in ("adf_p", "kpss_p")},
                            suggestion="Thử sai phân bậc 1 rồi kiểm định lại.")
            if col.get("seasonal") and s["label"] == result["series"][0]["label"]:
                ctx.finding("temporal.seasonal", Severity.INFO,
                            f"'{c}' có tự tương quan mạnh tại lag {[x['lag'] for x in col['seasonal']]}.",
                            scope=c, metric={"candidates": col["seasonal"]})
            brk = col.get("break")
            if brk and brk["p"] < float(ctx.cfg["temporal.break_p_threshold"]):
                ctx.finding("temporal.break", Severity.WARN,
                            f"'{c}' ({s['label']}) có điểm đứt gãy ứng viên ngày {brk['date']} "
                            f"(trung bình {brk['mean_left']:.3g} -> {brk['mean_right']:.3g}, p={brk['p']:.1e}).",
                            scope=c, metric=brk,
                            suggestion="Đối chiếu với sự kiện: đổi chính sách, đổi chuẩn kế toán, sáp nhập, hoặc đổi nguồn.")
