"""Chuẩn hóa chuỗi tiếng Việt: NFC, bỏ dấu, khóa so khớp, gom biến thể gần giống."""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter, defaultdict


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", str(text))


def spacing(text: str) -> str:
    return re.sub(r"\s+", " ", nfc(text)).strip()


def strip_accents(text: str) -> str:
    text = nfc(text).replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def match_key(text: str) -> str:
    """Khóa so khớp: không dấu, chữ thường, bỏ dấu câu và khoảng trắng thừa."""
    key = strip_accents(text).lower()
    key = re.sub(r"[^\w\s]", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def is_nfc(text: str) -> bool:
    return unicodedata.normalize("NFC", text) == text


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.parent[rj] = ri


def variant_groups(counts: Counter, similarity: float = 0.9, max_keys: int = 300) -> list[dict]:
    """Gom các giá trị là biến thể của nhau.

    Bước 1: cùng khóa so khớp (khác dấu, hoa thường, khoảng trắng).
    Bước 2: khóa gần giống nhau (lỗi gõ) theo SequenceMatcher trên tối đa `max_keys` khóa phổ biến.
    Kết quả chỉ là ĐỀ XUẤT, không tự áp dụng.
    """
    by_key: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for value, count in counts.items():
        by_key[match_key(value)].append((value, count))

    keys = sorted(by_key, key=lambda k: -sum(c for _, c in by_key[k]))[:max_keys]
    uf = _UnionFind(len(keys))
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            if not a or not b or abs(len(a) - len(b)) > 2:
                continue
            matcher = difflib.SequenceMatcher(None, a, b)
            if matcher.quick_ratio() >= similarity and matcher.ratio() >= similarity:
                uf.union(i, j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(keys)):
        clusters[uf.find(idx)].append(idx)

    groups: list[dict] = []
    for members_idx in clusters.values():
        if len(members_idx) < 2 and len(by_key[keys[members_idx[0]]]) < 2:
            continue
        members: list[tuple[str, int]] = []
        for idx in members_idx:
            members.extend(by_key[keys[idx]])
        members.sort(key=lambda vc: -vc[1])
        canonical = members[0][0]
        if len(members) < 2:
            continue
        groups.append({
            "canonical": canonical,
            "members": [{"value": v, "count": int(c)} for v, c in members],
            "total_count": int(sum(c for _, c in members)),
            "method": "accent_case_space" if len({match_key(v) for v, _ in members}) == 1 else "similar_key",
        })
    groups.sort(key=lambda g: -g["total_count"])
    return groups
