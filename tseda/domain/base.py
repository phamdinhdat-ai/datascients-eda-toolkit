"""Giao diện plugin domain.

Plugin CHỈ cung cấp: gợi ý tên cột (name hints) và ràng buộc nghiệp vụ.
Core chạy đầy đủ khi không có plugin nào. Không có logic thống kê trong plugin.
"""
from __future__ import annotations

from typing import Iterable

from tseda.core.roles import RoleGuess


class DomainPlugin:
    name: str = "base"
    description: str = ""

    def name_hints(self) -> dict[str, list[str]]:
        """Gợi ý tên cột theo vai trò, ví dụ {'numeric': ['du_no', 'npl']}. Chỉ là tín hiệu phụ."""
        return {}

    def constraints(self, columns: Iterable[str], roles: dict[str, RoleGuess]) -> list[dict]:
        """Ràng buộc áp dụng cho các cột có trong bảng. Xem capability/constraints.py để biết định dạng."""
        return []


def find_columns(columns: Iterable[str], *keywords: str) -> list[str]:
    """Tìm cột có chứa một trong các từ khóa (không phân biệt hoa thường, bỏ dấu)."""
    import unicodedata

    def norm(text: str) -> str:
        t = unicodedata.normalize("NFD", text).replace("đ", "d").replace("Đ", "D")
        return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()

    keys = [norm(k) for k in keywords]
    return [c for c in columns if any(k in norm(c) for k in keys)]
