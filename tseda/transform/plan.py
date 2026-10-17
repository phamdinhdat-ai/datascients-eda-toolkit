"""TransformPlan: danh sách biến đổi được đề xuất, duyệt từng bước, áp dụng và xuất ra file.

Nguyên tắc: framework chỉ ĐỀ XUẤT. Mặc định không bước nào được chấp nhận.
Chỉ các bước `safe` và được bật `transform.auto_accept_safe` mới được chấp nhận tự động.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from tseda.transform.ops import OPS


@dataclass
class TransformStep:
    id: str
    column: str
    op: str
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    impact: dict[str, Any] = field(default_factory=dict)
    reversible: bool = True
    safe: bool = False          # không làm mất thông tin và không đổi nghĩa (ví dụ parse số chắc chắn)
    accepted: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class ApplyLog:
    step_id: str
    column: str
    op: str
    status: str                 # applied | skipped | failed
    message: str = ""


class TransformPlan:
    def __init__(self, steps: list[TransformStep] | None = None):
        self.steps: list[TransformStep] = list(steps or [])

    # ---------- duyệt ----------
    def add(self, step: TransformStep) -> None:
        self.steps.append(step)

    def accept(self, ids: list[str] | None = None) -> None:
        for s in self.steps:
            if ids is None or s.id in ids:
                s.accepted = True

    def reject(self, ids: list[str]) -> None:
        for s in self.steps:
            if s.id in ids:
                s.accepted = False

    def auto_accept_safe(self) -> None:
        for s in self.steps:
            if s.safe:
                s.accepted = True

    def accepted(self) -> list[TransformStep]:
        return [s for s in self.steps if s.accepted]

    # ---------- áp dụng ----------
    def apply(self, df: pd.DataFrame, only_accepted: bool = True) -> tuple[pd.DataFrame, list[ApplyLog]]:
        """Áp dụng theo thứ tự đề xuất trên một bản sao. DataFrame gốc không bị thay đổi."""
        out = df.copy()
        logs: list[ApplyLog] = []
        for step in self.steps:
            if only_accepted and not step.accepted:
                logs.append(ApplyLog(step.id, step.column, step.op, "skipped", "chưa được chấp nhận"))
                continue
            if step.column not in out.columns:
                logs.append(ApplyLog(step.id, step.column, step.op, "skipped", "không có cột"))
                continue
            fn = OPS.get(step.op)
            if fn is None:
                logs.append(ApplyLog(step.id, step.column, step.op, "failed", f"không có phép '{step.op}'"))
                continue
            try:
                out[step.column] = fn(out[step.column], **step.params)
                logs.append(ApplyLog(step.id, step.column, step.op, "applied"))
            except Exception as exc:  # noqa: BLE001
                logs.append(ApplyLog(step.id, step.column, step.op, "failed", f"{type(exc).__name__}: {exc}"))
        return out, logs

    # ---------- xuất / nạp ----------
    def to_dict(self) -> dict:
        return {"version": 1, "steps": [s.to_dict() for s in self.steps]}

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        if path.suffix.lower() in (".yaml", ".yml"):
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        else:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "TransformPlan":
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) if path.suffix.lower() in (".yaml", ".yml") else json.loads(text)
        return cls([TransformStep(**s) for s in data.get("steps", [])])

    def summary(self) -> pd.DataFrame:
        rows = [{"id": s.id, "column": s.column, "op": s.op, "safe": s.safe,
                 "accepted": s.accepted, "reason": s.reason, **{f"impact.{k}": v for k, v in s.impact.items()}}
                for s in self.steps]
        return pd.DataFrame(rows)
