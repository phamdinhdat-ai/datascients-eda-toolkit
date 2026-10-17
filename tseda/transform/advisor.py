"""Advisor: đọc profile và sinh ra các TransformStep có lý do và tác động ước tính.

Mọi đề xuất đều mặc định chưa được chấp nhận. Chỉ bước `safe` mới có thể tự chấp nhận
khi cấu hình transform.auto_accept_safe = true.
"""
from __future__ import annotations

from tseda.core.registry import register_advisor
from tseda.core.roles import Role
from tseda.transform.plan import TransformStep


def _step(ctx, counter: dict, column: str, op: str, params: dict, reason: str, impact: dict,
          safe: bool = False, reversible: bool = True) -> TransformStep:
    key = f"{op}:{column}"
    counter[key] = counter.get(key, 0) + 1
    step = TransformStep(id=f"{key}:{counter[key]}", column=column, op=op, params=params, reason=reason,
                         impact=impact, reversible=reversible, safe=safe,
                         accepted=bool(safe and ctx.cfg["transform.auto_accept_safe"]))
    return step


@register_advisor
def advise_sentinels(ctx) -> list[TransformStep]:
    counter: dict = {}
    out = []
    for name, prof in ctx.profiles.items():
        examples = prof.get("sentinel_examples") or []
        if not examples:
            continue
        values = [e["value"] for e in examples]
        affected = sum(e["count"] for e in examples)
        out.append(_step(ctx, counter, name, "to_missing", {"values": values},
                         "Chuỗi sentinel được coi là thiếu dữ liệu",
                         {"rows_to_null": affected}, safe=True))
    return out


@register_advisor
def advise_parse(ctx) -> list[TransformStep]:
    counter: dict = {}
    out = []
    locale_default = ctx.cfg["numeric.default_locale"]
    suffix = dict(ctx.cfg["numeric.suffix_map"])
    currency = list(ctx.cfg["numeric.currency_tokens"])
    for name, g in ctx.roles.items():
        prof = ctx.profiles.get(name)
        if prof is None:
            continue
        if g.role in (Role.NUMERIC_STORED_AS_TEXT, Role.MIXED):
            coerce = prof.get("coerce", {})
            locale = coerce.get("locale", locale_default)
            parse_rate = coerce.get("parse_rate")
            n_present = int(ctx.cleaned[name].notna().sum())
            n_unparsed = n_present - int(coerce.get("parsed", n_present))
            exact = parse_rate == 1.0
            out.append(_step(ctx, counter, name, "parse_numeric",
                             {"locale": locale, "suffix_map": suffix, "currency": currency},
                             f"Parse số theo locale '{locale}' (tỷ lệ parse {parse_rate})",
                             {"rows_to_null": n_unparsed, "unparsed_examples": coerce.get("unparsed_examples", [])},
                             safe=exact and g.role == Role.NUMERIC_STORED_AS_TEXT))
        if g.role == Role.DATETIME and prof.get("stats", {}).get("format"):
            fmt = prof["stats"]["format"]
            ambiguous = prof["stats"].get("ambiguous", False)
            out.append(_step(ctx, counter, name, "parse_datetime", {"format": fmt},
                             "Parse ngày theo định dạng đã chọn"
                             + (" (mơ hồ dd/mm, cần xác nhận dayfirst)" if ambiguous else ""),
                             {"dayfirst": prof["stats"].get("dayfirst_used")},
                             safe=not ambiguous and prof["stats"].get("n_future", 0) == 0))
        if g.role == Role.BOOLEAN and g.evidence.get("tokens"):
            tokens = g.evidence["tokens"]
            cfg_pairs = ctx.cfg["typing.boolean_pairs"]
            trues = [t for t, _ in cfg_pairs if t in tokens]
            falses = [f for _, f in cfg_pairs if f in tokens]
            out.append(_step(ctx, counter, name, "map_boolean",
                             {"true_values": trues, "false_values": falses},
                             "Chuẩn hóa cờ về True/False", {}, safe=True))
    return out


@register_advisor
def advise_categories(ctx) -> list[TransformStep]:
    counter: dict = {}
    out = []
    for name, prof in ctx.profiles.items():
        groups = prof.get("variant_groups") or []
        if not groups:
            continue
        mapping: dict = {}
        for group in groups:
            for member in group["members"]:
                mapping[member["value"]] = group["canonical"]
        affected = sum(m["count"] for g in groups for m in g["members"] if m["value"] != g["canonical"])
        out.append(_step(ctx, counter, name, "canonicalize", {"mapping": mapping},
                         f"Gộp {len(groups)} nhóm biến thể (dấu, hoa thường, lỗi gõ) về giá trị chuẩn",
                         {"rows_affected": affected, "groups": [g["canonical"] for g in groups[:10]]},
                         safe=False))
    return out


@register_advisor
def advise_distribution(ctx) -> list[TransformStep]:
    counter: dict = {}
    out = []
    lo, hi = ctx.cfg["transform.winsor_quantiles"]
    for name, prof in ctx.profiles.items():
        if prof.get("family") != "numeric" or not prof.get("stats"):
            continue
        s = prof["stats"]
        if s.get("n", 0) < int(ctx.cfg["general.min_n_for_tests"]):
            continue
        if s.get("min", 0) > -1 and s.get("skew", 0) > float(ctx.cfg["numeric.skew_robust"]) and s.get("min", 0) >= 0:
            out.append(_step(ctx, counter, name, "log1p", {},
                             f"Lệch phải mạnh (skew={s['skew']:.2f}), giá trị không âm: log1p giúp ổn định phương sai",
                             {"skew_before": round(s["skew"], 3)}, safe=False, reversible=True))
        if s.get("robust_outlier_share", 0) >= 0.05:
            out.append(_step(ctx, counter, name, "winsorize", {"lower": lo, "upper": hi},
                             f"{s['robust_outlier_share']:.1%} outlier theo robust z: winsorize để giảm ảnh hưởng",
                             {"rows_clipped_estimate": s.get("n_robust_outliers", 0)}, safe=False, reversible=False))
        if prof.get("missing_share", 0) > 0 and prof.get("missing_share", 0) < float(ctx.cfg["missing.high_null_share"]):
            out.append(_step(ctx, counter, name, "impute_median", {},
                             "Thiếu ít: đề xuất điền median (chỉ là gợi ý, cần đánh giá theo mục đích sử dụng)",
                             {"n_missing": prof.get("n_missing", 0)}, safe=False, reversible=False))
    return out
