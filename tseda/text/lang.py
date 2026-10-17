"""Nhận diện tín hiệu ngôn ngữ đơn giản (có dấu tiếng Việt hay không). Chỉ để báo cáo."""
from __future__ import annotations

import re

VI_MARKED = set(
    "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
)
# Ký tự thường gặp khi dữ liệu UTF-8 bị đọc nhầm bảng mã (mojibake).
_MOJIBAKE = re.compile(r"[ÃÂÄÆÐÑ][\x80-\xbf€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ]|Ã.|Â.|Ä.|Æ.")
# Ký tự nằm ngoài Latin cơ bản + Latin-1 + dấu tiếng Việt: hay gặp ở dữ liệu lỗi mã hóa.
_ODD = re.compile(r"[Ā-ſƀ-ɏḀ-ỿ]")


def vi_mark_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(c.lower() in VI_MARKED for c in letters) / len(letters)


def has_mojibake(text: str) -> bool:
    return bool(_MOJIBAKE.search(text))


def language_signals(values) -> dict:
    texts = [str(v) for v in values]
    n = len(texts) or 1
    with_marks = sum(vi_mark_ratio(t) > 0 for t in texts)
    ascii_only = sum(t.isascii() and any(c.isalpha() for c in t) for t in texts)
    mojibake = sum(has_mojibake(t) for t in texts)
    odd = sum(bool(_ODD.search(t)) for t in texts)
    return {
        "share_vi_marked": round(with_marks / n, 4),
        "share_ascii_letters": round(ascii_only / n, 4),
        "share_possible_mojibake": round(mojibake / n, 4),
        "share_unusual_latin_chars": round(odd / n, 4),
    }
