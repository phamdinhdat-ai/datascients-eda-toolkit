"""Bản ghi dùng xuyên suốt: quyết định phương pháp, quan hệ cặp, kết quả kiểm định."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tseda.core.util import to_jsonable


@dataclass
class Decision:
    """Ghi lại một lựa chọn phương pháp và lý do, để báo cáo có phần 'đã làm gì và vì sao'."""
    scope: str
    step: str
    choice: str
    reason: str
    info: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "step": self.step,
            "choice": self.choice,
            "reason": self.reason,
            "info": to_jsonable(self.info),
        }


@dataclass
class TestResult:
    """Kết quả một kiểm định thống kê, đã kèm effect size và lý do chọn kiểm định."""
    name: str
    statistic: float | None
    p_value: float | None
    effect: float | None
    effect_name: str
    n: int
    reason: str = ""

    def to_dict(self) -> dict:
        return to_jsonable(self.__dict__)


@dataclass
class PairRelation:
    col_a: str
    col_b: str
    kind: str                  # ví dụ: numeric~numeric, categorical~categorical
    test: TestResult | None
    q_value: float | None = None   # sau Benjamini-Hochberg
    significant: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "col_a": self.col_a,
            "col_b": self.col_b,
            "kind": self.kind,
            "test": self.test.to_dict() if self.test else None,
            "q_value": to_jsonable(self.q_value),
            "significant": self.significant,
            "note": self.note,
        }
