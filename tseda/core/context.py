"""Context: trạng thái dùng chung cho một lần chạy EDA."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tseda.core.config import Config
from tseda.core.finding import Finding, Severity
from tseda.core.records import Decision, PairRelation
from tseda.core.roles import Role, RoleGuess
from tseda.core.table import RawTable


class Context:
    def __init__(
        self,
        table: RawTable,
        cfg: Config,
        schema: dict[str, str] | None = None,
        domain: Any = None,
        out_dir: str | Path | None = None,
    ):
        self.table = table
        self.cfg = cfg
        self.schema = dict(schema or {})          # {cột: tên role} khai báo thủ công
        self.domain = domain                      # plugin domain hoặc None
        self.out_dir = Path(out_dir) if out_dir else None
        self.rng = np.random.default_rng(cfg["general.seed"])

        self.roles: dict[str, RoleGuess] = {}
        self.cleaned: dict[str, pd.Series] = {}   # chuỗi đã làm sạch (NA cho sentinel), trước khi ép kiểu
        self.clean_info: dict[str, dict] = {}     # thông tin sentinel theo cột
        self.profiles: dict[str, dict] = {}
        self.coerce_info: dict[str, dict] = {}
        self.typed: dict[str, pd.Series] = {}     # cột đã ép kiểu, dùng cho mọi phân tích sau
        self.relations: list[PairRelation] = []
        self.capabilities: dict[str, dict] = {}
        self.findings: list[Finding] = []
        self.decisions: list[Decision] = []
        self.artifacts: dict[str, str] = {}
        self.quality: dict = {}
        self.vif: dict | None = None
        self.plan: Any = None                     # TransformPlan, gán ở stage transform
        self.stage_errors: list[dict] = []
        self.stages_run: list[str] = []

    # ---------- ghi nhận kết quả ----------
    def finding(
        self,
        id: str,
        severity: Severity,
        message: str,
        scope: str = "table",
        metric: dict | None = None,
        suggestion: str = "",
        evidence: list[str] | None = None,
    ) -> Finding:
        f = Finding(id=id, severity=severity, message=message, scope=scope,
                    metric=metric or {}, suggestion=suggestion, evidence=evidence or [])
        self.findings.append(f)
        return f

    def decide(self, scope: str, step: str, choice: str, reason: str, **info: Any) -> None:
        self.decisions.append(Decision(scope=scope, step=step, choice=choice, reason=reason, info=info))

    # ---------- truy cập dữ liệu ----------
    @property
    def df(self) -> pd.DataFrame:
        return self.table.df

    def raw(self, name: str) -> pd.Series:
        return self.table.df[name]

    def role(self, name: str) -> Role:
        return self.roles[name].role

    def columns_with(self, *families: str) -> list[str]:
        return [c for c, g in self.roles.items() if g.family in families]

    def sample_index(self, index: pd.Index, n: int | None = None) -> pd.Index:
        """Mẫu ngẫu nhiên có tái lập cố định theo seed, dùng khi n vượt ngưỡng kiểm định."""
        cap = n or int(self.cfg["general.max_n_for_tests"])
        if len(index) <= cap:
            return index
        chosen = self.rng.choice(len(index), size=cap, replace=False)
        return index[np.sort(chosen)]

    def today(self) -> pd.Timestamp:
        override = self.cfg.get("general.today")
        if override:
            return pd.Timestamp(override)
        return pd.Timestamp(date.today())

    def artifact_dir(self) -> Path | None:
        if self.out_dir is None:
            return None
        path = self.out_dir / "figures"
        path.mkdir(parents=True, exist_ok=True)
        return path
