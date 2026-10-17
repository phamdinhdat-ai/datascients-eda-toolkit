"""Parse số từ chuỗi: tự nhận locale (1.234,5 hay 1,234.5), hậu tố đơn vị (tr, tỷ, k), ký hiệu tiền tệ."""
from __future__ import annotations

import re
from collections import Counter

import pandas as pd

_DOT_DEC = re.compile(r"^[+-]?\d+\.\d{1,2}$")
_DOT_THOU = re.compile(r"^[+-]?\d{1,3}(\.\d{3})+$")
_COM_DEC = re.compile(r"^[+-]?\d+,\d{1,2}$")
_COM_THOU = re.compile(r"^[+-]?\d{1,3}(,\d{3})+$")
_PLAIN = re.compile(r"^[+-]?\d+(\.\d+)?$")


def _clean_token(text: str, currency: list[str]) -> str:
    t = str(text).strip().replace(" ", " ").lower()
    for tok in sorted(currency, key=len, reverse=True):
        t = t.replace(tok.lower(), "")
    return t.strip()


def detect_locale(values, default: str = "vi", currency: list[str] | None = None) -> tuple[str, dict]:
    """Bỏ phiếu theo mẫu. 'vi' = dấu chấm nghìn, dấu phẩy thập phân. 'en' = ngược lại."""
    currency = currency or []
    votes = Counter()
    for raw in values:
        t = _clean_token(raw, currency).replace(" ", "")
        if _DOT_DEC.match(t):
            votes["en"] += 1
        elif _COM_THOU.match(t):
            votes["en"] += 1
        elif _COM_DEC.match(t):
            votes["vi"] += 1
        elif _DOT_THOU.match(t):
            votes["vi"] += 1
    en, vi = votes["en"], votes["vi"]
    if en == vi:
        locale = default
        reason = "không đủ bằng chứng, dùng locale mặc định"
    else:
        locale = "en" if en > vi else "vi"
        reason = f"bỏ phiếu: en={en}, vi={vi}"
    return locale, {"votes": {"en": en, "vi": vi}, "reason": reason}


def parse_one(text: str, locale: str, suffix_map: dict, currency: list[str]) -> float | None:
    t = _clean_token(text, currency)
    if not t:
        return None
    negative = t.startswith("(") and t.endswith(")")
    t = t.strip("()").strip()
    t = t.replace("%", "").strip()
    mult = 1.0
    for suf in sorted(suffix_map, key=len, reverse=True):
        s = suf.lower()
        if t.endswith(s) and len(t) > len(s) and (t[-len(s) - 1].isdigit() or t[-len(s) - 1] == " "):
            mult = float(suffix_map[suf])
            t = t[: -len(s)].strip()
            break
    t = t.replace(" ", "")
    if locale == "vi":
        # vi: dấu phẩy là thập phân nếu có. Dấu chấm là nghìn chỉ khi đúng nhóm 3 chữ số (23.500), còn lại là thập phân (1.5).
        if "," in t:
            t = t.replace(".", "").replace(",", ".")
        elif _DOT_THOU.fullmatch(t):
            t = t.replace(".", "")
    else:
        t = t.replace(",", "")
    if not _PLAIN.match(t):
        return None
    value = float(t) * mult
    return -value if negative else value


def parse_series(values: pd.Series, locale: str, suffix_map: dict, currency: list[str]) -> tuple[pd.Series, pd.Series]:
    """Trả về (giá trị float, mask parse được). Tính trên giá trị duy nhất để nhanh."""
    raw = values.astype("object")
    uniq = pd.unique(raw.dropna())
    lookup: dict = {}
    for u in uniq:
        lookup[u] = parse_one(str(u), locale, suffix_map, currency)
    parsed = raw.map(lambda x: lookup.get(x) if pd.notna(x) else None)
    ok = parsed.notna() & raw.notna()
    numeric = pd.to_numeric(parsed, errors="coerce").astype("float64")
    return numeric, ok


def parse_rate(values: pd.Series, locale: str, suffix_map: dict, currency: list[str]) -> float:
    if len(values) == 0:
        return 0.0
    _, ok = parse_series(values, locale, suffix_map, currency)
    return float(ok.mean())


def unparsed_examples(values: pd.Series, ok: pd.Series, k: int = 10) -> list[dict]:
    bad = values[~ok & values.notna()].astype(str)
    counts = Counter(bad)
    return [{"value": v, "count": int(c)} for v, c in counts.most_common(k)]
