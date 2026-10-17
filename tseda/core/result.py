"""EDAReport: kết quả có cấu trúc của một lần chạy, có thể truy vấn, xuất file và áp dụng transform plan."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from tseda.core.finding import Finding, Severity
from tseda.core.records import Decision, PairRelation
from tseda.core.roles import RoleGuess
from tseda.core.util import to_jsonable


@dataclass
class EDAReport:
    name: str
    source: str
    shape: tuple[int, int]
    config: dict
    roles: dict[str, RoleGuess]
    profiles: dict[str, dict]
    relations: list[PairRelation]
    vif: dict | None
    capabilities: dict[str, dict]
    quality: dict
    findings: list[Finding]
    decisions: list[Decision]
    artifacts: dict[str, str]
    plan: Any
    stage_errors: list[dict]
    stages_run: list[str]
    cleaned: pd.DataFrame
    typed: pd.DataFrame
    out_dir: Path | None = None
    meta: dict = field(default_factory=dict)

    # ---------- truy vấn ----------
    def findings_df(self, min_severity: Severity | str | None = None, scope: str | None = None) -> pd.DataFrame:
        rows = []
        threshold = None
        if isinstance(min_severity, str):
            threshold = Severity[min_severity.upper()]
        elif isinstance(min_severity, Severity):
            threshold = min_severity
        for f in self.findings:
            if threshold is not None and f.severity < threshold:
                continue
            if scope is not None and f.scope != scope:
                continue
            rows.append({"severity": f.severity.name, "id": f.id, "scope": f.scope, "message": f.message,
                         "suggestion": f.suggestion})
        df = pd.DataFrame(rows, columns=["severity", "id", "scope", "message", "suggestion"])
        order = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
        return df.sort_values(by="severity", key=lambda s: s.map(order), kind="stable").reset_index(drop=True)

    def filter(self, severity: str) -> pd.DataFrame:
        return self.findings_df(min_severity=severity.upper())

    def roles_df(self) -> pd.DataFrame:
        rows = []
        for c, g in self.roles.items():
            prof = self.profiles.get(c, {})
            rows.append({"column": c, "role": g.role.value, "confidence": g.confidence, "source": g.source,
                         "alternatives": ", ".join(f"{r.value}:{s:.2f}" for r, s in g.alternatives),
                         "missing_share": prof.get("missing_share")})
        return pd.DataFrame(rows)

    def summary(self) -> pd.DataFrame:
        counts = self.findings_df()["severity"].value_counts()
        return pd.DataFrame({
            "severity": ["CRITICAL", "WARN", "INFO"],
            "count": [int(counts.get(s, 0)) for s in ("CRITICAL", "WARN", "INFO")],
        })

    def relations_df(self) -> pd.DataFrame:
        rows = []
        for r in self.relations:
            t = r.test
            rows.append({"col_a": r.col_a, "col_b": r.col_b, "kind": r.kind,
                         "test": t.name if t else None, "effect": t.effect if t else None,
                         "effect_name": t.effect_name if t else None, "p_value": t.p_value if t else None,
                         "q_value": r.q_value, "significant": r.significant, "n": t.n if t else None})
        return pd.DataFrame(rows)

    def capability_names(self) -> list[str]:
        return list(self.capabilities.keys())

    # ---------- transform ----------
    def apply_plan(self, plan: Any = None, accepted_only: bool = True) -> tuple[pd.DataFrame, list]:
        """Áp dụng plan lên dữ liệu đã làm sạch chuỗi (sentinel đã là NA)."""
        p = plan or self.plan
        if p is None:
            return self.cleaned.copy(), []
        return p.apply(self.cleaned, only_accepted=accepted_only)

    # ---------- xuất ----------
    def to_dict(self) -> dict:
        return to_jsonable({
            "name": self.name,
            "source": self.source,
            "shape": list(self.shape),
            "stages_run": self.stages_run,
            "stage_errors": self.stage_errors,
            "roles": {c: g.to_dict() for c, g in self.roles.items()},
            "profiles": self.profiles,
            "relations": [r.to_dict() for r in self.relations],
            "vif": self.vif,
            "capabilities": self.capabilities,
            "quality": self.quality,
            "findings": [f.to_dict() for f in self.findings],
            "decisions": [d.to_dict() for d in self.decisions],
            "artifacts": self.artifacts,
            "transform_plan": self.plan.to_dict() if self.plan is not None else None,
            "config": self.config,
            "meta": self.meta,
        })

    def to_html(self, path: str | Path | None = None) -> str:
        from tseda.report.html import render_html
        html = render_html(self)
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(html, encoding="utf-8")
        return html

    def to_dashboard(self, path: str | Path | None = None) -> str:
        """Dashboard tương tác (lọc, biểu đồ, bảng dữ liệu) dưới dạng một file HTML tự chứa."""
        from tseda.dashboard.render import render_dashboard
        html = render_dashboard(self, self.config_obj())
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(html, encoding="utf-8")
        return html

    def config_obj(self):
        from tseda.core.config import Config
        return Config(self.config)

    def save(self, out_dir: str | Path) -> dict[str, str]:
        """Ghi toàn bộ kết quả: HTML, JSON, CSV phát hiện/vai trò, plan, dữ liệu đã làm sạch."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        written: dict[str, str] = {}

        html_path = out / "report.html"
        self.to_html(html_path)
        written["report_html"] = str(html_path)

        dash_path = out / "dashboard.html"
        self.to_dashboard(dash_path)
        written["dashboard_html"] = str(dash_path)

        json_path = out / "report.json"
        json_path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        written["report_json"] = str(json_path)

        findings_path = out / "findings.csv"
        self.findings_df().to_csv(findings_path, index=False, quoting=csv.QUOTE_MINIMAL)
        written["findings_csv"] = str(findings_path)

        roles_path = out / "roles.csv"
        self.roles_df().to_csv(roles_path, index=False)
        written["roles_csv"] = str(roles_path)

        if self.plan is not None:
            plan_path = self.plan.save(out / "transform_plan.yaml")
            written["transform_plan"] = str(plan_path)
        return written

    def print_summary(self) -> None:
        print(f"== EDA: {self.name} | {self.shape[0]} dòng x {self.shape[1]} cột | các stage: {', '.join(self.stages_run)}")
        print("Vai trò:")
        for c, g in self.roles.items():
            print(f"  - {c}: {g.role.value} (confidence={g.confidence:.2f})")
        print(f"Capability bật: {', '.join(self.capability_names()) or 'không có'}")
        print("Phát hiện:")
        df = self.findings_df()
        for _, row in df.head(30).iterrows():
            print(f"  [{row['severity']}] {row['scope']}: {row['message']}")
        if len(df) > 30:
            print(f"  ... còn {len(df) - 30} phát hiện, xem report.findings_df()")
        if self.stage_errors:
            print("Lỗi stage:")
            for e in self.stage_errors:
                print(f"  - {e['stage']}: {e['error']}")
