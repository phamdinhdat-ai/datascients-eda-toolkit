"""Đơn vị kết quả chung: Finding (một phát hiện có bằng chứng và gợi ý)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from tseda.core.util import to_jsonable


class Severity(IntEnum):
    INFO = 0
    WARN = 1
    CRITICAL = 2


@dataclass
class Finding:
    id: str
    severity: Severity
    message: str
    scope: str = "table"          # tên cột, "table", hoặc "pair:a|b"
    metric: dict[str, Any] = field(default_factory=dict)
    suggestion: str = ""
    evidence: list[str] = field(default_factory=list)  # tên artifact liên quan

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "severity": self.severity.name,
            "scope": self.scope,
            "message": self.message,
            "metric": to_jsonable(self.metric),
            "suggestion": self.suggestion,
            "evidence": list(self.evidence),
        }
