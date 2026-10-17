"""Quan hệ theo cặp họ. Phép kiểm định được chọn theo họ của hai cột, rồi hiệu chỉnh BH cho cả họ kiểm định."""
from __future__ import annotations

from itertools import combinations

import pandas as pd

from tseda.core.finding import Severity
from tseda.core.records import PairRelation
from tseda.core.registry import PAIR_TESTS, register_pair
from tseda.stats import tests as st
from tseda.stats.multiplicity import benjamini_hochberg

ANALYSED_FAMILIES = {"numeric", "categorical", "boolean", "datetime"}
MAX_LEVELS_FOR_PAIRS = 200


def _orient(ctx, a: str, b: str, sa: pd.Series, sb: pd.Series, first: str):
    if ctx.roles[a].family == first:
        return a, b, sa, sb
    return b, a, sb, sa


@register_pair("numeric", "numeric")
def pair_num_num(ctx, a, b, sa, sb):
    return PairRelation(a, b, "numeric~numeric", st.num_num(sa.astype(float), sb.astype(float)))


@register_pair("numeric", "categorical")
def pair_num_cat(ctx, a, b, sa, sb):
    num, cat, snum, scat = _orient(ctx, a, b, sa, sb, "numeric")
    return PairRelation(a, b, "numeric~categorical",
                        st.num_cat(snum.astype(float), scat,
                                   int(ctx.cfg["general.min_n_for_tests"]),
                                   float(ctx.cfg["categorical.rare_level_min_share"]),
                                   int(ctx.cfg["categorical.rare_level_min_count"])))


@register_pair("numeric", "boolean")
def pair_num_bool(ctx, a, b, sa, sb):
    num, flag, snum, sflag = _orient(ctx, a, b, sa, sb, "numeric")
    return PairRelation(a, b, "numeric~boolean", st.bool_num(sflag.astype("boolean"), snum.astype(float)))


@register_pair("categorical", "categorical")
def pair_cat_cat(ctx, a, b, sa, sb):
    # Không ép kiểu str trước: hàm thống kê tự loại NA rồi mới chuyển chuỗi.
    return PairRelation(a, b, "categorical~categorical",
                        st.cat_cat(sa, sb,
                                   float(ctx.cfg["relate.cramers_min_expected"]),
                                   float(ctx.cfg["relate.sparse_cell_share"]),
                                   float(ctx.cfg["categorical.rare_level_min_share"]),
                                   int(ctx.cfg["categorical.rare_level_min_count"])))


@register_pair("categorical", "boolean")
def pair_cat_bool(ctx, a, b, sa, sb):
    return pair_cat_cat(ctx, a, b, sa, sb)


@register_pair("boolean", "boolean")
def pair_bool_bool(ctx, a, b, sa, sb):
    return pair_cat_cat(ctx, a, b, sa, sb)


@register_pair("datetime", "numeric")
def pair_dt_num(ctx, a, b, sa, sb):
    dt, num, sdt, snum = _orient(ctx, a, b, sa, sb, "datetime")
    t0 = sdt.min()
    days = ((sdt - t0).dt.total_seconds() / 86400.0).to_numpy(dtype=float)
    values = snum.astype(float).to_numpy()
    return PairRelation(a, b, "datetime~numeric", st.trend(days, values))


def _eligible(ctx) -> list[str]:
    cols = []
    for c, g in ctx.roles.items():
        if g.family not in ANALYSED_FAMILIES or c not in ctx.typed:
            continue
        if g.family == "categorical" and ctx.typed[c].nunique(dropna=True) > MAX_LEVELS_FOR_PAIRS:
            ctx.decide(c, "pairs", "bỏ qua khỏi kiểm định cặp", f"cardinality > {MAX_LEVELS_FOR_PAIRS}")
            continue
        cols.append(c)
    return cols


def _priority(fa: str, fb: str) -> int:
    order = {("numeric", "numeric"): 0, ("numeric", "categorical"): 1, ("categorical", "categorical"): 2,
             ("numeric", "boolean"): 3, ("boolean", "categorical"): 4, ("boolean", "boolean"): 5,
             ("datetime", "numeric"): 6}
    return order.get((fa, fb), order.get((fb, fa), 9))


def run_pairs(ctx) -> list[PairRelation]:
    alpha = float(ctx.cfg["relate.fdr_alpha"])
    moderate = float(ctx.cfg["relate.moderate_effect"])
    strong = float(ctx.cfg["relate.strong_effect"])
    cols = _eligible(ctx)

    candidates = []
    for a, b in combinations(cols, 2):
        fa, fb = ctx.roles[a].family, ctx.roles[b].family
        if (fa, fb) in PAIR_TESTS:
            candidates.append((_priority(fa, fb), a, b, fa, fb))
    candidates.sort(key=lambda t: t[0])
    max_pairs = int(ctx.cfg["relate.max_pairs"])
    if len(candidates) > max_pairs:
        ctx.decide("table", "pairs", f"chỉ kiểm định {max_pairs}/{len(candidates)} cặp",
                   "giới hạn số cặp để kiểm soát thời gian và đa so sánh", max_pairs=max_pairs)
        candidates = candidates[:max_pairs]
    if not candidates:
        return []

    base_index = ctx.df.index
    idx = ctx.sample_index(base_index)
    sample = {c: ctx.typed[c].loc[idx] for c in cols}

    results: list[PairRelation] = []
    for _, a, b, fa, fb in candidates:
        fn = PAIR_TESTS[(fa, fb)]
        try:
            rel = fn(ctx, a, b, sample[a], sample[b])
        except Exception as exc:  # noqa: BLE001 - một cặp lỗi không được làm hỏng cả pipeline
            ctx.decide(f"pair:{a}|{b}", "error", "bỏ qua", f"{type(exc).__name__}: {exc}")
            continue
        if rel is not None:
            results.append(rel)

    pvals = [r.test.p_value if r.test else None for r in results]
    qvals = benjamini_hochberg(pvals)
    for rel, q in zip(results, qvals):
        rel.q_value = q
        rel.significant = q is not None and q < alpha

    n_tests = sum(1 for r in results if r.test and r.test.p_value is not None)
    ctx.decide("table", "multiplicity", "Benjamini-Hochberg",
               f"{n_tests} kiểm định có p-value; kiểm soát FDR ở {alpha}", n_tests=n_tests)

    for rel in results:
        if not rel.significant or rel.test is None or rel.test.effect is None:
            continue
        eff = abs(rel.test.effect)
        scope = f"pair:{rel.col_a}|{rel.col_b}"
        if eff < moderate:
            continue
        if rel.kind == "numeric~numeric" and eff >= 0.95:
            ctx.finding("relation.redundant", Severity.WARN,
                        f"'{rel.col_a}' và '{rel.col_b}' gần như đơn điệu hoàn toàn (|rho|={eff:.3f}): có thể trùng thông tin.",
                        scope=scope, metric={"effect": rel.test.effect, "q": rel.q_value},
                        suggestion="Giữ một cột, hoặc kiểm tra một cột có được tính từ cột kia không.")
        elif eff >= strong:
            ctx.finding("relation.strong", Severity.INFO,
                        f"Quan hệ mạnh giữa '{rel.col_a}' và '{rel.col_b}' ({rel.test.effect_name}={eff:.3f}, {rel.kind}).",
                        scope=scope, metric={"effect": rel.test.effect, "test": rel.test.name, "q": rel.q_value},
                        suggestion="Kiểm tra quan hệ này có phải nhân quả, đồng biến động, hay rò rỉ.")
        else:
            ctx.finding("relation.moderate", Severity.INFO,
                        f"Quan hệ vừa giữa '{rel.col_a}' và '{rel.col_b}' ({rel.test.effect_name}={eff:.3f}).",
                        scope=scope, metric={"effect": rel.test.effect, "test": rel.test.name, "q": rel.q_value})
    return results
