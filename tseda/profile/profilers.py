"""Profile theo vai trò. Mỗi vai trò dispatch về một hàm riêng qua registry."""
from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from tseda.core.finding import Severity
from tseda.core.registry import register_profiler
from tseda.core.roles import Role
from tseda.profile.base import base_profile, sentinel_numbers_hit
from tseda.stats import descriptive as sd
from tseda.text import lang as tlang
from tseda.text import normalize as tnorm
from tseda.text import patterns as tpat


# ---------------------------------------------------------------- số
@register_profiler(Role.NUMERIC_CONTINUOUS, Role.NUMERIC_COUNT, Role.NUMERIC_STORED_AS_TEXT)
def profile_numeric(ctx, name, typed, guess, info):
    cfg = ctx.cfg
    p = base_profile(ctx, name, typed, guess, info)
    x = typed.dropna().astype(float)
    if len(x) == 0:
        return p

    s = sd.numeric_summary(x, float(cfg["numeric.robust_z_threshold"]), float(cfg["numeric.outlier_iqr_k"]))
    idx = ctx.sample_index(x.index)
    if len(x) >= int(cfg["general.min_n_for_tests"]):
        s["normality"] = sd.normality(x.loc[idx])
    s["modes"] = sd.multimodality(x.loc[idx], prominence=float(cfg["numeric.mode_prominence"]))
    p["stats"] = s

    # Lựa chọn thống kê trung tâm và phân tán theo độ lệch
    robust = abs(s["skew"]) > float(cfg["numeric.skew_robust"]) or s["robust_outlier_share"] > 0.05
    ctx.decide(name, "center", "median/MAD" if robust else "mean/std",
               "phân phối lệch hoặc nhiều outlier, mean bị kéo lệch" if robust else "phân phối gần đối xứng",
               skew=round(s["skew"], 3), robust_outlier_share=round(s["robust_outlier_share"], 4))
    if len(x) < int(cfg["general.min_n_for_tests"]):
        ctx.decide(name, "tests", "skipped", f"n={len(x)} quá nhỏ cho kiểm định")

    if s["robust_outlier_share"] >= 0.01:
        ctx.finding(
            "outliers.robust", Severity.WARN if s["robust_outlier_share"] >= 0.05 else Severity.INFO,
            f"'{name}' có {s['robust_outlier_share']:.1%} giá trị outlier theo robust z (|z|>{cfg['numeric.robust_z_threshold']}).",
            scope=name, metric={"n": s["n_robust_outliers"], "share": s["robust_outlier_share"],
                                "p99": s["p99"], "max": s["max"]},
            suggestion="Xem lại nguồn các giá trị cực đại. Không tự winsorize nếu outlier có ý nghĩa nghiệp vụ.",
        )

    if s["zero_share"] >= float(cfg["numeric.zero_inflation_share"]):
        ctx.decide(name, "model", "hai phần (zero-inflated)", "tỷ lệ 0 cao, trung bình không đại diện",
                   zero_share=round(s["zero_share"], 4))
        ctx.finding("numeric.zero_inflated", Severity.WARN,
                    f"'{name}' có {s['zero_share']:.1%} giá trị bằng 0.", scope=name,
                    metric={"zero_share": s["zero_share"]},
                    suggestion="Tách mô hình 'có/không' và mô hình độ lớn khi có dữ liệu đủ.")

    if x.min() > 0 and s["skew"] > float(cfg["numeric.skew_robust"]):
        ctx.decide(name, "transform", "log1p đề xuất", "dương và lệch phải mạnh")

    if len(x) >= 30:
        mult = int(cfg["numeric.round_multiple"])
        share_round = float((np.mod(x, mult) == 0).mean())
        if share_round >= float(cfg["numeric.round_multiple_share"]) and x.abs().max() > 0:
            ctx.finding("numeric.rounding", Severity.WARN,
                        f"'{name}': {share_round:.1%} giá trị chia hết cho {mult}. Có thể là dữ liệu làm tròn hoặc đổi đơn vị.",
                        scope=name, metric={"share_multiple": share_round, "multiple": mult},
                        suggestion="Kiểm tra đơn vị (đồng, nghìn đồng, triệu đồng) với nguồn.")

    hits = sentinel_numbers_hit(x, list(cfg["missing.sentinel_numbers"]))
    if hits:
        total = sum(hits.values())
        ctx.finding("sentinel.numeric", Severity.WARN if total / len(x) >= 0.01 else Severity.INFO,
                    f"'{name}' chứa giá trị nghi là sentinel: {hits}.", scope=name,
                    metric={"hits": hits, "share": total / len(x)},
                    suggestion="Xác nhận đây là missing (đổi thành NA) hay là giá trị thật.")

    if info.get("parse_rate") is not None and info["parse_rate"] < 1.0:
        ctx.finding("parse.unparsed", Severity.WARN,
                    f"'{name}' (số lưu dạng chữ): {1 - info['parse_rate']:.1%} giá trị không parse được.",
                    scope=name, metric={"parse_rate": info["parse_rate"], "examples": info.get("unparsed_examples", [])},
                    suggestion="Xem danh sách giá trị không parse được. Thêm hậu tố hoặc quy tắc vào cấu hình numeric.suffix_map.")
    return p


# ---------------------------------------------------------------- boolean
@register_profiler(Role.BOOLEAN)
def profile_boolean(ctx, name, typed, guess, info):
    p = base_profile(ctx, name, typed, guess, info)
    x = typed.dropna()
    n = int(len(x))
    n_true = int((x == True).sum())  # noqa: E712 (boolean dtype)
    p["stats"] = {"n": n, "n_true": n_true, "n_false": n - n_true,
                  "true_share": round(n_true / n, 4) if n else None,
                  "unmapped": int(info.get("unmapped", 0))}
    if info.get("unmapped", 0) > 0:
        ctx.finding("boolean.unmapped", Severity.WARN,
                    f"'{name}' có {info['unmapped']} giá trị không thuộc bộ boolean đã biết.", scope=name,
                    suggestion="Bổ sung cặp giá trị vào typing.boolean_pairs.")
    if n and (n_true / n < 0.01 or n_true / n > 0.99):
        ctx.finding("boolean.imbalanced", Severity.INFO,
                    f"'{name}' mất cân bằng mạnh: {n_true / n:.2%} là True.", scope=name,
                    metric={"true_share": n_true / n})
    return p


# ---------------------------------------------------------------- category
@register_profiler(Role.CATEGORICAL_NOMINAL, Role.CATEGORICAL_ORDINAL)
def profile_categorical(ctx, name, typed, guess, info):
    cfg = ctx.cfg
    p = base_profile(ctx, name, typed, guess, info)
    vals = typed.dropna().astype(str)
    if len(vals) == 0:
        return p
    counts = vals.value_counts()
    summary = sd.categorical_summary(counts, float(cfg["categorical.rare_level_min_share"]),
                                     int(cfg["categorical.rare_level_min_count"]))
    total = int(counts.sum())
    summary["top_levels"] = [{"level": str(k), "count": int(v), "share": round(v / total, 4)}
                             for k, v in counts.head(20).items()]
    p["stats"] = summary

    ratio = summary["n_levels"] / max(total, 1)
    if ratio > float(cfg["categorical.high_cardinality_ratio"]):
        ctx.decide(name, "encoding", "không vẽ bar chart, không one-hot", "cardinality cao",
                   n_levels=summary["n_levels"])
        ctx.finding("categorical.high_cardinality", Severity.INFO,
                    f"'{name}' có {summary['n_levels']} level, tỷ lệ {ratio:.1%}: gần như định danh.",
                    scope=name, metric={"n_levels": summary["n_levels"], "ratio": ratio},
                    suggestion="Cân nhắc đổi vai trò sang ID hoặc text, hoặc gom level hiếm.")
    if summary.get("rare_share", 0) > 0 and summary.get("n_rare_levels", 0) > 0:
        ctx.finding("categorical.rare_levels", Severity.INFO,
                    f"'{name}' có {summary['n_rare_levels']} level hiếm, chiếm {summary['rare_share']:.2%} dữ liệu.",
                    scope=name, metric={"n_rare_levels": summary["n_rare_levels"], "rare_share": summary["rare_share"]},
                    suggestion="Gộp thành '__khác__' trong phân tích quan hệ, hoặc xác nhận đây là level thật.")

    raw_counts = Counter(vals.tolist())
    groups = tnorm.variant_groups(raw_counts, float(cfg["categorical.variant_similarity"]),
                                  int(cfg["categorical.max_variant_keys"]))
    p["variant_groups"] = groups
    if groups:
        ctx.finding("categorical.variants", Severity.WARN,
                    f"'{name}' có {len(groups)} nhóm giá trị có thể là biến thể của nhau (dấu, hoa thường, lỗi gõ).",
                    scope=name,
                    metric={"n_groups": len(groups), "examples": groups[:5]},
                    suggestion="Xác nhận danh sách rồi áp dụng canonicalize trong transform plan. Chưa tự gộp.")

    non_nfc = sum(c for v, c in raw_counts.items() if not tnorm.is_nfc(v))
    if non_nfc:
        ctx.finding("text.non_nfc", Severity.WARN,
                    f"'{name}': {non_nfc} giá trị chưa chuẩn Unicode NFC (cùng một chữ có dấu nhưng khác mã hóa).",
                    scope=name, metric={"count": non_nfc},
                    suggestion="Chuẩn hóa NFC trước khi so sánh hoặc join.")

    lang = tlang.language_signals(list(raw_counts.keys()))
    p["stats"]["language"] = lang
    if lang["share_possible_mojibake"] > 0:
        ctx.finding("text.mojibake", Severity.WARN,
                    f"'{name}': có dấu hiệu lỗi mã hóa (mojibake) ở {lang['share_possible_mojibake']:.1%} giá trị.",
                    scope=name, metric=lang,
                    suggestion="Kiểm tra nguồn xuất dữ liệu (UTF-8 bị đọc theo cp1252, hoặc dữ liệu TCVN3/VNI cũ).")

    if guess.role == Role.CATEGORICAL_ORDINAL:
        lex = guess.evidence.get("matched_lexicon") or []
        p["stats"]["ordinal_levels_matched"] = lex
        ctx.decide(name, "encoding", "thứ tự (ordinal)", "khớp từ điển mức độ", matched=lex)
    return p


# ---------------------------------------------------------------- văn bản
@register_profiler(Role.TEXT_SHORT, Role.TEXT_FREE)
def profile_text(ctx, name, typed, guess, info):
    p = base_profile(ctx, name, typed, guess, info)
    vals = typed.dropna().astype(str)
    if len(vals) == 0:
        return p
    lens = vals.str.len()
    toks = vals.str.split().str.len()
    s = {
        "n": int(len(vals)),
        "mean_len": float(lens.mean()),
        "p50_len": float(lens.median()),
        "p95_len": float(lens.quantile(0.95)),
        "mean_tokens": float(toks.mean()),
        "duplicate_share": round(1 - vals.nunique() / len(vals), 4),
        "digit_char_share": round(float(vals.str.count(r"\d").sum() / max(lens.sum(), 1)), 4),
        "punct_char_share": round(float(vals.str.count(r"[^\w\s]").sum() / max(lens.sum(), 1)), 4),
        "pattern_top": tpat.top_patterns(vals, k=5),
    }
    counts = Counter(vals.tolist())
    lang = tlang.language_signals(list(counts.keys()))
    s["language"] = lang
    p["stats"] = s
    ctx.decide(name, "analysis", "thống kê độ dài, mẫu ký tự, ngôn ngữ",
               "văn bản: không dùng NLP nặng mặc định")
    if lang["share_possible_mojibake"] > 0:
        ctx.finding("text.mojibake", Severity.WARN,
                    f"'{name}': có dấu hiệu lỗi mã hóa ở {lang['share_possible_mojibake']:.1%} giá trị.",
                    scope=name, metric=lang, suggestion="Kiểm tra bảng mã của nguồn.")
    if s["duplicate_share"] > 0.5 and guess.role == Role.TEXT_FREE:
        ctx.finding("text.duplicates", Severity.INFO,
                    f"'{name}': {s['duplicate_share']:.1%} ghi chú bị lặp (có thể là mẫu có sẵn).",
                    scope=name, metric={"duplicate_share": s["duplicate_share"]})
    non_nfc = sum(c for v, c in counts.items() if not tnorm.is_nfc(v))
    if non_nfc:
        ctx.finding("text.non_nfc", Severity.WARN,
                    f"'{name}': {non_nfc} giá trị chưa chuẩn NFC.", scope=name, metric={"count": non_nfc},
                    suggestion="Chuẩn hóa NFC.")
    return p


@register_profiler(Role.STRUCTURED_TEXT)
def profile_structured(ctx, name, typed, guess, info):
    p = base_profile(ctx, name, typed, guess, info)
    vals = typed.dropna().astype(str).tolist()
    kind = guess.evidence.get("kind")
    invalid = 0
    if kind and vals:
        rx = tpat._REGEX.get(kind)
        if rx is not None:
            invalid = sum(not rx.match(v.strip()) for v in vals)
        elif kind == "json":
            invalid = sum(not tpat._is_json(v) for v in vals)
    p["stats"] = {"kind": kind, "invalid_count": invalid,
                  "invalid_share": round(invalid / len(vals), 4) if vals else 0.0,
                  "pattern_top": tpat.top_patterns(pd.Series(vals), k=5) if vals else []}
    if invalid:
        ctx.finding("structured.invalid", Severity.WARN,
                    f"'{name}' ({kind}): {invalid} giá trị không đúng định dạng.", scope=name,
                    metric={"invalid_share": p["stats"]["invalid_share"]},
                    suggestion="Xem các giá trị không khớp mẫu và sửa tại nguồn.")
    return p


# ---------------------------------------------------------------- ngày giờ
@register_profiler(Role.DATETIME)
def profile_datetime(ctx, name, typed, guess, info):
    p = base_profile(ctx, name, typed, guess, info)
    t = typed.dropna()
    if len(t) == 0:
        return p
    today = ctx.today()
    has_time = bool(((t.dt.hour != 0) | (t.dt.minute != 0) | (t.dt.second != 0)).any())
    suspicious_defaults = t.dt.strftime("%Y-%m-%d").isin(["1900-01-01", "1970-01-01", "0001-01-01"])
    future = t > today
    years = t.dt.year.value_counts().sort_index()
    s = {
        "n": int(len(t)),
        "min": t.min().isoformat(),
        "max": t.max().isoformat(),
        "span_days": int((t.max() - t.min()).days),
        "has_time_component": has_time,
        "is_monotonic_increasing": bool(t.is_monotonic_increasing),
        "duplicate_share": round(1 - t.nunique() / len(t), 4),
        "n_future": int(future.sum()),
        "n_suspicious_default": int(suspicious_defaults.sum()),
        "years": {str(int(k)): int(v) for k, v in years.head(60).items()},
        "format": info.get("format"),
        "dayfirst_used": info.get("dayfirst_used"),
        "dayfirst_source": guess.evidence.get("dayfirst_source", "config"),
        "ambiguous": bool(info.get("ambiguous", False)),
    }
    p["stats"] = s
    ctx.decide(name, "parse", f"format={info.get('format')}", "định dạng có tỷ lệ parse cao nhất",
               dayfirst=s["dayfirst_used"], source=s["dayfirst_source"])
    if s["ambiguous"]:
        ctx.finding("datetime.ambiguous_dayfirst", Severity.WARN,
                    f"'{name}': mọi ngày đều ≤ 12 nên không xác định được dd/mm hay mm/dd. Đang dùng dayfirst={s['dayfirst_used']}.",
                    scope=name, metric={"dayfirst_used": s["dayfirst_used"]},
                    suggestion="Khai báo general.dayfirst đúng với nguồn.")
    if s["n_future"]:
        ctx.finding("datetime.future", Severity.WARN,
                    f"'{name}' có {s['n_future']} ngày ở tương lai so với hôm nay ({today.date()}).",
                    scope=name, metric={"n_future": s["n_future"], "max": s["max"]},
                    suggestion="Kiểm tra ngày nhập sai hoặc ngày dự kiến bị lẫn với ngày thực tế.")
    if s["n_suspicious_default"]:
        ctx.finding("datetime.default_value", Severity.WARN,
                    f"'{name}' có {s['n_suspicious_default']} ngày trùng giá trị mặc định (1900/1970/0001).",
                    scope=name, metric={"n": s["n_suspicious_default"]},
                    suggestion="Giá trị mặc định khi lỗi thường xuất hiện. Đổi thành NA sau khi xác nhận.")
    if info.get("parse_rate", 1.0) < 1.0:
        cleaned = ctx.cleaned[name]
        bad = typed.isna() & cleaned.notna()
        ctx.finding("datetime.unparsed", Severity.WARN,
                    f"'{name}': {1 - info['parse_rate']:.1%} giá trị không parse được thành ngày.", scope=name,
                    metric={"parse_rate": info["parse_rate"], "n_unparsed": int(bad.sum()),
                            "examples": cleaned[bad].astype(str).value_counts().head(5).to_dict()},
                    suggestion="Thêm định dạng vào typing.date_formats hoặc sửa nguồn.")
    return p


# ---------------------------------------------------------------- ID
@register_profiler(Role.ID)
def profile_id(ctx, name, typed, guess, info):
    p = base_profile(ctx, name, typed, guess, info)
    vals = typed.dropna()
    n = int(len(vals))
    dup = n - int(vals.nunique())
    s = {"n": n, "n_duplicates": dup, "duplicate_share": round(dup / n, 4) if n else 0.0,
         "pattern_top": tpat.top_patterns(vals.astype(str), k=5, compress=False)}
    if pd.api.types.is_numeric_dtype(vals):
        s["is_monotonic_increasing"] = bool(vals.is_monotonic_increasing)
    p["stats"] = s
    if dup > 0:
        ctx.finding("id.duplicates", Severity.WARN,
                    f"'{name}' được coi là ID nhưng có {dup} giá trị trùng.", scope=name,
                    metric={"n_duplicates": dup}, suggestion="Kiểm tra khóa chính hoặc đổi vai trò sang categorical.")
    if s.get("is_monotonic_increasing") and n >= 30:
        ctx.finding("id.monotonic", Severity.INFO,
                    f"'{name}' tăng đơn điệu theo thứ tự dòng: ID này có thể mã hóa thời gian và gây rò rỉ nếu dùng làm feature.",
                    scope=name, suggestion="Không dùng trực tiếp làm feature. Kiểm tra rò rỉ ở bước split.")
    return p


# ---------------------------------------------------------------- hỗn hợp
@register_profiler(Role.MIXED)
def profile_mixed(ctx, name, typed, guess, info):
    p = base_profile(ctx, name, typed, guess, info)
    cleaned = ctx.cleaned[name]
    clean = ctx.clean_info.get(name, {})
    parsed_mask = typed.notna()
    text_part = cleaned[~parsed_mask & cleaned.notna()].astype(str)
    text_counts = Counter(text_part.tolist())
    s = {
        "parse_rate_numeric": info.get("parse_rate"),
        "numeric_part": int(parsed_mask.sum()),
        "text_part": int(len(text_part)),
        "text_top": [{"value": k, "count": int(v)} for k, v in text_counts.most_common(10)],
        "pattern_top": tpat.top_patterns(text_part, k=8) if len(text_part) else [],
        "sentinel_strings": clean.get("sentinel_strings", 0),
    }
    p["stats"] = s
    ctx.finding("mixed.column", Severity.WARN,
                f"'{name}' là cột hỗn hợp: {s['numeric_part']} giá trị parse được thành số, {s['text_part']} giá trị là chữ.",
                scope=name, metric={"parse_rate_numeric": s["parse_rate_numeric"], "text_top": s["text_top"][:5]},
                suggestion="Xem danh sách chữ. Đề xuất parser số kèm hậu tố trong transform plan, không tự chuyển đổi.")
    return p


# ---------------------------------------------------------------- empty / constant
@register_profiler(Role.EMPTY)
def profile_empty(ctx, name, typed, guess, info):
    p = base_profile(ctx, name, typed, guess, info)
    ctx.finding("column.empty", Severity.WARN, f"Cột '{name}' rỗng hoàn toàn.", scope=name,
                suggestion="Xóa cột khỏi phân tích hoặc kiểm tra nguồn.")
    return p


@register_profiler(Role.CONSTANT)
def profile_constant(ctx, name, typed, guess, info):
    p = base_profile(ctx, name, typed, guess, info)
    value = typed.dropna().iloc[0] if typed.notna().any() else None
    p["stats"] = {"value": value.item() if hasattr(value, "item") else value}
    ctx.finding("column.constant", Severity.INFO, f"Cột '{name}' chỉ có một giá trị.", scope=name,
                metric={"value": p["stats"]["value"]}, suggestion="Không mang thông tin, có thể loại bỏ.")
    return p
