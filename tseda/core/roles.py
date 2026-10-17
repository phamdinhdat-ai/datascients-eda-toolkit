"""Vai trò ngữ nghĩa của cột và nhóm họ (family) dùng để chọn phương pháp."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    EMPTY = "empty"
    CONSTANT = "constant"
    BOOLEAN = "boolean"
    ID = "id"
    DATETIME = "datetime"
    NUMERIC_CONTINUOUS = "numeric_continuous"
    NUMERIC_COUNT = "numeric_count"
    NUMERIC_STORED_AS_TEXT = "numeric_stored_as_text"
    CATEGORICAL_NOMINAL = "categorical_nominal"
    CATEGORICAL_ORDINAL = "categorical_ordinal"
    TEXT_SHORT = "text_short"
    TEXT_FREE = "text_free"
    STRUCTURED_TEXT = "structured_text"
    MIXED = "mixed"


# Family: nhóm vai trò dùng để tra cứu kiểm định. Thêm role mới chỉ cần gán family.
FAMILY: dict[Role, str] = {
    Role.EMPTY: "empty",
    Role.CONSTANT: "constant",
    Role.BOOLEAN: "boolean",
    Role.ID: "id",
    Role.DATETIME: "datetime",
    Role.NUMERIC_CONTINUOUS: "numeric",
    Role.NUMERIC_COUNT: "numeric",
    Role.NUMERIC_STORED_AS_TEXT: "numeric",
    Role.CATEGORICAL_NOMINAL: "categorical",
    Role.CATEGORICAL_ORDINAL: "categorical",
    Role.TEXT_SHORT: "text",
    Role.TEXT_FREE: "text",
    Role.STRUCTURED_TEXT: "text",
    Role.MIXED: "mixed",
}


def family_of(role: Role) -> str:
    return FAMILY[role]


# Thứ tự ưu tiên khi hai vai trò có điểm bằng nhau (vai trò cụ thể hơn đứng trước).
TIE_PRIORITY: list[Role] = [
    Role.EMPTY,
    Role.CONSTANT,
    Role.BOOLEAN,
    Role.STRUCTURED_TEXT,
    Role.DATETIME,
    Role.NUMERIC_STORED_AS_TEXT,
    Role.NUMERIC_COUNT,
    Role.NUMERIC_CONTINUOUS,
    Role.CATEGORICAL_ORDINAL,
    Role.CATEGORICAL_NOMINAL,
    Role.ID,
    Role.TEXT_FREE,
    Role.TEXT_SHORT,
    Role.MIXED,
]


@dataclass
class RoleGuess:
    role: Role
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    alternatives: list[tuple[Role, float]] = field(default_factory=list)
    source: str = "inferred"  # inferred | schema

    @property
    def family(self) -> str:
        return family_of(self.role)

    def to_dict(self) -> dict:
        return {
            "role": self.role.value,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "alternatives": [(r.value, round(float(s), 4)) for r, s in self.alternatives],
            "evidence": self.evidence,
        }
