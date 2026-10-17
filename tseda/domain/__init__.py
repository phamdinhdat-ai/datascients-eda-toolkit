"""Plugin domain. Thêm plugin mới: tạo class kế thừa DomainPlugin, gắn @register_domain("ten")."""
from __future__ import annotations

from tseda.core.registry import DOMAINS
from tseda.domain import banking, finance, retail  # noqa: F401 - nạp để đăng ký


def get_domain(name: str):
    if name not in DOMAINS:
        raise ValueError(f"Không có plugin domain '{name}'. Có sẵn: {sorted(DOMAINS)}")
    return DOMAINS[name]()


def available_domains() -> list[str]:
    return sorted(DOMAINS)
