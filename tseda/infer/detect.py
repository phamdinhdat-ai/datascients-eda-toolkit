"""Thống kê cột và bộ chấm điểm vai trò.

Mỗi vai trò có một hàm chấm điểm trả về (điểm 0..1, bằng chứng). Điểm càng cao càng hợp lý.
Tên cột chỉ cộng thêm một chút (name hint), không bao giờ quyết định một mình.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tseda.core.roles import Role
from tseda.text import dates as tdates
from tseda.text import numeric as tnum
from tseda.text import patterns as tpat


@dataclass
class ColStats:
    name: str
    n_rows: int
    n_null: int
    n_sentinel: int
    n_valid: int
    nunique: int
    unique_ratio: float
    native: str                       # numeric | bool | datetime | string
    int_like: bool = False
    has_decimals: bool = False
    nonneg: bool = False
    values: list[str] = field(default_factory=list)   # mẫu chuỗi, dùng cho cột string
    value_counts: dict[str, int] = field(default_factory=dict)
    mean_tokens: float = 0.0
    mean_len: float = 0.0
    len_cv: float = 0.0
    dominant_len_share: float = 0.0
    leading_zero_share: float = 0.0
    nums: pd.Series | None = None     # giá trị số cho cột numeric native
    name_norm: str = ""


def _norm_name(name: str) -> str:
    text = unicodedata.normalize("NFD", str(name)).replace("đ", "d").replace("Đ", "D")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _native_kind(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    return "string"


def build_stats(name: str, cleaned: pd.Series, sentinel_count: int, sample_size: int, rng: np.random.Generator) -> ColStats:
    n_rows = len(cleaned)
    valid = cleaned[cleaned.notna()]
    n_valid = len(valid)
    kind = _native_kind(cleaned)
    st = ColStats(
        name=name,
        n_rows=n_rows,
        n_null=int(n_rows - n_valid - sentinel_count),
        n_sentinel=int(sentinel_count),
        n_valid=n_valid,
        nunique=int(valid.nunique(dropna=True)) if n_valid else 0,
        unique_ratio=0.0,
        native=kind,
        name_norm=_norm_name(name),
    )
    st.unique_ratio = st.nunique / n_valid if n_valid else 0.0
    if n_valid == 0:
        return st

    if kind in ("numeric", "bool"):
        nums = pd.to_numeric(valid, errors="coerce").astype("float64").dropna()
        st.nums = nums
        st.int_like = bool(len(nums) and np.all(np.isclose(nums, np.round(nums))))
        st.has_decimals = not st.int_like
        st.nonneg = bool(len(nums) and (nums >= 0).all())
        return st

    if kind == "datetime":
        return st

    strs = [str(v).strip() for v in valid.tolist()]
    st.value_counts = {k: int(v) for k, v in pd.Series(strs).value_counts().head(500).items()}
    if len(strs) > sample_size:
        idx = np.sort(rng.choice(len(strs), size=sample_size, replace=False))
        sample = [strs[i] for i in idx]
    else:
        sample = strs
    st.values = sample
    st.int_like = all(re.fullmatch(r"[+-]?\d+", t) for t in sample)
    st.has_decimals = any(re.search(r"\d[.,]\d", t) for t in sample)
    st.nonneg = all(not t.startswith("-") for t in sample)
    lens = np.array([len(t) for t in strs], dtype=float)
    toks = np.array([len(t.split()) for t in strs], dtype=float)
    st.mean_len = float(lens.mean())
    st.mean_tokens = float(toks.mean())
    st.len_cv = float(lens.std() / lens.mean()) if lens.mean() > 0 else 0.0
    _, counts = np.unique(lens, return_counts=True)
    st.dominant_len_share = float(counts.max() / len(lens))
    st.leading_zero_share = float(sum(bool(re.fullmatch(r"0\d+", t)) for t in sample) / len(sample))
    return st


# ---------- bộ chấm điểm ----------

def _hit(st: ColStats, hints: list[str]) -> bool:
    return any(h and h in st.name_norm for h in (_norm_name(x) for x in hints))


def _bool_map(pairs: list[list[str]]) -> dict[str, bool]:
    mapping: dict[str, bool] = {}
    for t, f in pairs:
        if t:
            mapping[t.lower()] = True
        if f:
            mapping[f.lower()] = False
    return mapping


def score_roles(st: ColStats, cfg, hints: dict[str, list[str]]) -> dict[Role, tuple[float, dict]]:
    out: dict[Role, tuple[float, dict]] = {}
    if st.n_valid == 0:
        out[Role.EMPTY] = (1.0, {"n_valid": 0})
        return out
    if st.nunique == 1:
        out[Role.CONSTANT] = (0.95, {"only_value": st.values[0] if st.values else float(st.nums.iloc[0])})
        return out

    parse_th = float(cfg["typing.parse_threshold"])
    id_th = float(cfg["typing.id_unique_ratio"])

    # --- boolean ---
    if st.native == "bool":
        out[Role.BOOLEAN] = (1.0, {"native": True})
    elif st.native == "numeric" and st.nunique == 2 and st.nums is not None and set(np.unique(st.nums)) <= {0.0, 1.0}:
        out[Role.BOOLEAN] = (0.9, {"values": "0/1"})
    elif st.native == "string" and st.nunique == 2:
        mapping = _bool_map(cfg["typing.boolean_pairs"])
        toks = {v.lower() for v in st.values}
        if toks and toks <= set(mapping):
            out[Role.BOOLEAN] = (0.95, {"tokens": sorted(toks)})

    # --- datetime ---
    if st.native == "datetime":
        out[Role.DATETIME] = (1.0, {"native": True})
    elif st.native == "string" and st.values:
        best = tdates.best_format(st.values, list(cfg["typing.date_formats"]), bool(cfg["general.dayfirst"]), parse_th)
        if best["format"] and best["rate"] >= parse_th:
            score = best["rate"] * (0.85 if best["ambiguous"] else 1.0) + (0.05 if _hit(st, hints["datetime"]) else 0.0)
            out[Role.DATETIME] = (min(score, 1.0), {"format": best["format"], "rate": round(best["rate"], 4),
                                                    "ambiguous": best["ambiguous"],
                                                    "dayfirst_used": best["dayfirst_used"]})

    # --- identifier ---
    if st.n_valid >= 10 and st.unique_ratio >= id_th:
        if st.native == "numeric" and st.int_like:
            s = 0.75 if _hit(st, hints["id"]) else 0.5
            out[Role.ID] = (s, {"unique_ratio": round(st.unique_ratio, 4), "int_like": True})
        elif st.native == "string" and st.dominant_len_share >= 0.8 and st.mean_tokens <= 1.2:
            s = 0.9 + (0.05 if _hit(st, hints["id"]) else 0.0)
            out[Role.ID] = (min(s, 1.0), {"unique_ratio": round(st.unique_ratio, 4),
                                          "dominant_len_share": round(st.dominant_len_share, 3)})

    # --- số (native) ---
    if st.native == "numeric" and st.nums is not None and len(st.nums):
        n_valid = st.n_valid
        uniq_ratio = st.unique_ratio
        if st.int_like and st.nunique <= int(cfg["numeric.low_card_integer_max"]) and n_valid >= 30:
            vals = np.sort(np.unique(st.nums))
            consecutive = bool(np.all(np.diff(vals) == 1))
            out[Role.CATEGORICAL_ORDINAL if consecutive else Role.CATEGORICAL_NOMINAL] = (
                0.6, {"n_levels": st.nunique, "consecutive_ints": consecutive, "native_int": True})
            out[Role.NUMERIC_COUNT] = (0.45, {"n_levels": st.nunique})
        elif st.int_like:
            is_count = st.nonneg and (uniq_ratio <= float(cfg["numeric.count_max_unique_ratio"])
                                      or _hit(st, ["count", "so_luong", "qty", "sl", "dem", "so_lan"]))
            if is_count:
                out[Role.NUMERIC_COUNT] = (0.85, {"unique_ratio": round(uniq_ratio, 4), "nonneg": True})
            out[Role.NUMERIC_CONTINUOUS] = (0.8 if not is_count else 0.5, {"int_like": True,
                                                                             "unique_ratio": round(uniq_ratio, 4)})
        else:
            out[Role.NUMERIC_CONTINUOUS] = (0.85, {"has_decimals": True})

    # --- chuỗi: số lưu dạng văn bản, hỗn hợp, phân loại, văn bản, cấu trúc ---
    if st.native == "string" and st.values:
        locale, lock_info = tnum.detect_locale(st.values, str(cfg["numeric.default_locale"]),
                                               list(cfg["numeric.currency_tokens"]))
        if cfg["numeric.locale"] != "auto":
            locale = str(cfg["numeric.locale"])
        suffix = dict(cfg["numeric.suffix_map"])
        currency = list(cfg["numeric.currency_tokens"])
        num_rate = tnum.parse_rate(pd.Series(st.values, dtype="object"), locale, suffix, currency)
        leading_zero_codes = st.leading_zero_share >= 0.5

        if num_rate >= parse_th and not leading_zero_codes:
            out[Role.NUMERIC_STORED_AS_TEXT] = (num_rate, {"locale": locale, "parse_rate": round(num_rate, 4),
                                                           "locale_votes": lock_info["votes"]})
        elif 0.3 <= num_rate < parse_th:
            out[Role.MIXED] = (0.75, {"parse_rate_numeric": round(num_rate, 4)})

        kind, rate, _ = tpat.structured_kind(st.values, float(cfg["text.structured_match_threshold"]))
        if kind:
            out[Role.STRUCTURED_TEXT] = (rate, {"kind": kind, "rate": round(rate, 4)})

        # Category: cardinality tương đối thấp VÀ (câu ngắn HOẶC ít level tuyệt đối).
        # Cột có vài chục câu lặp lại vẫn là category, không phải văn bản tự do.
        is_categorical_like = st.unique_ratio <= float(cfg["categorical.high_cardinality_ratio"]) and (
            st.mean_tokens <= float(cfg["text.free_text_min_mean_tokens"]) or st.nunique <= 50)
        if is_categorical_like and Role.NUMERIC_STORED_AS_TEXT not in out:
            nominal = 0.8
            ordinal_hit = _ordinal_hit(st.values, cfg)
            if ordinal_hit:
                out[Role.CATEGORICAL_ORDINAL] = (0.85, {"matched_lexicon": ordinal_hit})
            out[Role.CATEGORICAL_NOMINAL] = (nominal, {"n_levels": st.nunique,
                                                        "unique_ratio": round(st.unique_ratio, 4)})

        if st.unique_ratio > float(cfg["categorical.high_cardinality_ratio"]) or st.mean_tokens > float(
                cfg["text.free_text_min_mean_tokens"]):
            free = st.mean_tokens >= float(cfg["text.free_text_min_mean_tokens"]) and \
                st.mean_len > float(cfg["text.short_text_max_mean_len"])
            if free:
                out[Role.TEXT_FREE] = (0.8, {"mean_tokens": round(st.mean_tokens, 2), "mean_len": round(st.mean_len, 1)})
            else:
                out[Role.TEXT_SHORT] = (0.7, {"mean_tokens": round(st.mean_tokens, 2), "mean_len": round(st.mean_len, 1)})

        if 0.3 <= num_rate < parse_th or _mixed_types(st.values, locale, suffix, currency):
            out.setdefault(Role.MIXED, (0.7, {"parse_rate_numeric": round(num_rate, 4)}))

    return out


def _ordinal_hit(values: list[str], cfg) -> list[str] | None:
    present = {v.lower() for v in values}
    best: list[str] | None = None
    for lex in cfg["categorical.ordinal_lexicons"]:
        hits = [t for t in lex if t.lower() in present]
        if len(hits) >= 2 and (best is None or len(hits) > len(best)):
            best = hits
    return best


def _mixed_types(values: list[str], locale: str, suffix: dict, currency: list[str]) -> bool:
    """Cột có cả giá trị 'thuần số' lẫn 'thuần chữ' với tỷ lệ đáng kể."""
    numeric = sum(bool(re.fullmatch(r"[\d\s.,+-]+", v)) for v in values)
    alpha = sum(bool(re.search(r"[^\W\d_]", v)) and not re.search(r"\d", v) for v in values)
    n = len(values) or 1
    return numeric / n >= 0.2 and alpha / n >= 0.2
