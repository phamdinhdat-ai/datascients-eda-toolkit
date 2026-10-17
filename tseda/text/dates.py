"""Parse ngày: chọn định dạng tốt nhất, phát hiện mơ hồ dd/mm và mm/dd."""
from __future__ import annotations

import re
import warnings

import pandas as pd

_SLASH_DM = "%d/%m/%Y"
_SLASH_MD = "%m/%d/%Y"
_SLASH_DM_T = "%d/%m/%Y %H:%M:%S"
_SLASH_MD_T = "%m/%d/%Y %H:%M:%S"
_FIRST_PART = re.compile(r"^\s*(\d{1,2})[/.-](\d{1,2})[/.-]")


def _to_dt(texts: list, fmt: str) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(pd.Series(texts, dtype="object"), format=fmt, errors="coerce")


def best_format(values, formats: list[str], dayfirst: bool, threshold: float = 0.9, max_sample: int = 2000) -> dict:
    """Chọn định dạng có tỷ lệ parse cao nhất.

    Với chuỗi dạng dd/mm hoặc mm/dd: nếu có giá trị > 12 ở một vị trí thì thứ tự được suy ra từ dữ liệu.
    Nếu không có, dùng cấu hình `dayfirst` và đánh dấu `ambiguous` để người dùng xác nhận.
    """
    sample = [str(v).strip() for v in values if pd.notna(v) and str(v).strip() != ""][:max_sample]
    if not sample:
        return {"format": None, "rate": 0.0, "ambiguous": False, "dayfirst_used": dayfirst, "rates": {}}

    rates = {fmt: float(_to_dt(sample, fmt).notna().mean()) for fmt in formats}

    first_gt12 = second_gt12 = 0
    for s in sample:
        m = _FIRST_PART.match(s)
        if m:
            first_gt12 += int(m.group(1)) > 12
            second_gt12 += int(m.group(2)) > 12

    if first_gt12 > 0 and second_gt12 == 0:
        dayfirst_used, evidence_based = True, True
    elif second_gt12 > 0 and first_gt12 == 0:
        dayfirst_used, evidence_based = False, True
    else:
        dayfirst_used, evidence_based = dayfirst, False

    ambiguous = (
        not evidence_based
        and _SLASH_DM in rates and _SLASH_MD in rates
        and rates[_SLASH_DM] >= threshold and rates[_SLASH_MD] >= threshold
    )

    best = max(formats, key=lambda f: (rates[f], -formats.index(f)))
    # Khi cả hai thứ tự đều parse được, ưu tiên thứ tự đã suy ra.
    if rates[best] >= threshold and best in (_SLASH_DM, _SLASH_MD):
        best = _SLASH_DM if dayfirst_used else _SLASH_MD

    return {
        "format": best,
        "rate": rates.get(best, 0.0),
        "ambiguous": bool(ambiguous),
        "dayfirst_used": bool(dayfirst_used),
        "dayfirst_source": "data" if evidence_based else "config",
        "rates": {k: round(v, 4) for k, v in sorted(rates.items(), key=lambda kv: -kv[1])[:5]},
        "evidence": {"first_part_gt12": first_gt12, "second_part_gt12": second_gt12, "sample": len(sample)},
    }


def parse_dates(values: pd.Series, fmt: str | None) -> pd.Series:
    if fmt is None:
        return pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    texts = [None if pd.isna(x) else str(x).strip() for x in values]
    out = _to_dt(texts, fmt)
    out.index = values.index
    return out.astype("datetime64[ns]")
