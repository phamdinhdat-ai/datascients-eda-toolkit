"""Đăng ký analyzer theo vai trò, theo cặp họ, theo capability.

Pipeline không biết cột nào là gì: nó tra registry. Muốn thêm kiểm tra mới,
chỉ cần viết hàm và gắn decorator tương ứng.
"""
from __future__ import annotations

from typing import Callable

from tseda.core.roles import Role

PROFILERS: dict[Role, Callable] = {}
PAIR_TESTS: dict[tuple[str, str], Callable] = {}
CAPABILITIES: dict[str, Callable] = {}
ADVISORS: list[Callable] = []
DOMAINS: dict[str, Callable] = {}


def register_profiler(*roles: Role) -> Callable:
    """fn(ctx, name, typed_series, guess, coerce_info) -> dict profile"""
    def deco(fn: Callable) -> Callable:
        for role in roles:
            PROFILERS[role] = fn
        return fn
    return deco


def register_pair(family_a: str, family_b: str) -> Callable:
    """fn(ctx, col_a, col_b, series_a, series_b) -> PairRelation | None. Đăng ký cả hai chiều."""
    def deco(fn: Callable) -> Callable:
        PAIR_TESTS[(family_a, family_b)] = fn
        PAIR_TESTS[(family_b, family_a)] = fn
        return fn
    return deco


def register_capability(name: str) -> Callable:
    """fn(ctx) -> dict | None. Trả None khi không đủ điều kiện kích hoạt."""
    def deco(fn: Callable) -> Callable:
        CAPABILITIES[name] = fn
        return fn
    return deco


def register_advisor(fn: Callable) -> Callable:
    """fn(ctx) -> list[TransformStep]"""
    ADVISORS.append(fn)
    return fn


def register_domain(name: str) -> Callable:
    def deco(factory: Callable) -> Callable:
        DOMAINS[name] = factory
        return factory
    return deco
