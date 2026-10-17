"""Làm sạch nhẹ trước khi suy luận: khoảng trắng, NBSP, chuỗi sentinel (N/A, null, chưa có...)."""
from __future__ import annotations

from collections import Counter

import pandas as pd


def _is_string_like(s: pd.Series) -> bool:
    return not (
        pd.api.types.is_numeric_dtype(s)
        or pd.api.types.is_bool_dtype(s)
        or pd.api.types.is_datetime64_any_dtype(s)
    )


def clean_series(series: pd.Series, sentinel_strings: list[str]) -> tuple[pd.Series, dict]:
    """Trả về (series đã làm sạch, thông tin). Chuỗi sentinel và chuỗi rỗng được đổi thành NA.

    Sentinel dạng số (-1, 9999...) KHÔNG tự đổi thành NA vì có thể là giá trị thật.
    Chúng được báo cáo ở bước profile số để người dùng xác nhận.
    """
    info: dict = {"sentinel_strings": 0, "sentinel_examples": []}
    if not _is_string_like(series):
        return series, info

    sentinels = {s.strip().lower() for s in sentinel_strings}
    cleaned_values: list = []
    sentinel_hits: Counter = Counter()
    for x in series.tolist():
        if x is None or (not isinstance(x, str) and pd.isna(x)):
            cleaned_values.append(None)
            continue
        text = str(x).replace(" ", " ").strip()
        if text == "":
            cleaned_values.append(None)
        elif text.lower() in sentinels:
            cleaned_values.append(None)
            sentinel_hits[text] += 1
        else:
            cleaned_values.append(text)

    n_sentinel = int(sum(sentinel_hits.values()))
    info["sentinel_strings"] = n_sentinel
    info["sentinel_examples"] = [{"value": v, "count": int(c)} for v, c in sentinel_hits.most_common(5)]
    cleaned = pd.Series(cleaned_values, index=series.index, dtype="object", name=series.name)
    return cleaned, info
