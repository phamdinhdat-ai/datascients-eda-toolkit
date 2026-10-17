"""Mẫu cấu trúc (pattern masking) và nhận diện chuỗi có cấu trúc (email, URL, SĐT, MST, JSON)."""
from __future__ import annotations

import json
import re
from collections import Counter

import pandas as pd


def mask(text: str, compress: bool = True) -> str:
    """'VCB-123 ab' -> 'A-9_a' (compress) hoặc 'AAA-999_aa' (không nén)."""
    out: list[str] = []
    for ch in str(text):
        if ch.isdigit():
            out.append("9")
        elif ch.isalpha():
            out.append("A" if ch.isupper() else "a")
        elif ch.isspace():
            out.append("_")
        else:
            out.append(ch)
    if not compress:
        return "".join(out)
    compressed: list[str] = []
    for ch in out:
        if compressed and ch == compressed[-1] and ch in "A9a_":
            continue
        compressed.append(ch)
    return "".join(compressed)


def top_patterns(values: pd.Series, k: int = 5, compress: bool = True) -> list[dict]:
    """Mẫu phổ biến nhất. Tính trên giá trị duy nhất rồi nhân số đếm, nhanh hơn nhiều trên cột lớn."""
    unique_counts = values.astype(str).value_counts()
    counts: Counter = Counter()
    for value, c in unique_counts.items():
        counts[mask(value, compress=compress)] += int(c)
    total = sum(counts.values()) or 1
    return [{"pattern": p, "count": c, "share": round(c / total, 4)} for p, c in counts.most_common(k)]


_REGEX = {
    "email": re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$"),
    "url": re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE),
    # SĐT Việt Nam: 0912 345 678, 091.234.5678, +84 912 345 678 (không có dấu gạch ngang)
    "vn_phone": re.compile(r"^(\+84|0)[\s.]?\d{2,3}[\s.]?\d{3}[\s.]?\d{3,4}$"),
    # MST: 10 chữ số, hoặc 10 chữ số + '-' + 3 chữ số chi nhánh
    "tax_code": re.compile(r"^\d{10}(-\d{3})?$"),
}


def _is_json(text: str) -> bool:
    t = text.strip()
    if not (t.startswith("{") or t.startswith("[")):
        return False
    try:
        json.loads(t)
        return True
    except (ValueError, TypeError):
        return False


def structured_kind(values: list[str], threshold: float = 0.8) -> tuple[str | None, float, dict[str, float]]:
    """Trả về (loại, tỷ lệ khớp, tỷ lệ theo từng loại). Loại None nếu không loại nào đạt ngưỡng."""
    if not values:
        return None, 0.0, {}
    rates: dict[str, float] = {}
    for kind, rx in _REGEX.items():
        rates[kind] = sum(bool(rx.match(v.strip())) for v in values) / len(values)
    rates["json"] = sum(_is_json(v) for v in values) / len(values)
    best = max(rates, key=rates.get)
    if rates[best] >= threshold:
        return best, rates[best], rates
    return None, rates[best], rates
