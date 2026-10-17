"""Pipeline: điều phối các stage theo thứ tự cố định. Lỗi ở một stage được ghi lại, không làm hỏng cả lần chạy."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from tseda.core.config import Config
from tseda.core.context import Context
from tseda.core.finding import Severity
from tseda.core.result import EDAReport
from tseda.core.table import RawTable

STAGE_ORDER = ["typing", "quality", "profile", "relate", "capability", "transform", "viz"]


def _stage_typing(ctx: Context) -> None:
    from tseda.infer.coerce import coerce
    from tseda.infer.infer import infer_roles

    hints = ctx.domain.name_hints() if ctx.domain is not None else None
    roles, cleaned, clean_info = infer_roles(ctx.df, ctx.cfg, ctx.schema, hints)
    ctx.roles, ctx.cleaned, ctx.clean_info = roles, cleaned, clean_info
    for c, guess in roles.items():
        typed, info = coerce(cleaned[c], guess, ctx.cfg)
        ctx.typed[c] = typed
        ctx.coerce_info[c] = info
        ctx.decide(c, "role", guess.role.value,
                   "suy luận từ bằng chứng dữ liệu" if guess.source == "inferred" else "khai báo thủ công (schema)",
                   confidence=guess.confidence, alternatives=[(r.value, s) for r, s in guess.alternatives],
                   coerce=info)
    if ctx.domain is not None:
        ctx.decide("table", "domain", ctx.domain.name, ctx.domain.description)


def _stage_quality(ctx: Context) -> None:
    from tseda.quality.checks import run_quality
    ctx.quality = run_quality(ctx)


def _stage_profile(ctx: Context) -> None:
    import tseda.profile.profilers  # noqa: F401 - nạp để đăng ký
    from tseda.core.registry import PROFILERS

    for c, guess in ctx.roles.items():
        fn = PROFILERS[guess.role]
        ctx.profiles[c] = fn(ctx, c, ctx.typed[c], guess, ctx.coerce_info[c])


def _stage_relate(ctx: Context) -> None:
    from tseda.relate.pairs import run_pairs
    from tseda.relate.vif import vif_report

    ctx.relations = run_pairs(ctx)
    ctx.vif = vif_report(ctx, float(ctx.cfg["relate.vif_threshold"]))


def _stage_capability(ctx: Context) -> None:
    import tseda.capability  # noqa: F401 - nạp để đăng ký
    from tseda.core.registry import CAPABILITIES

    for name, fn in CAPABILITIES.items():
        try:
            res = fn(ctx)
        except Exception as exc:  # noqa: BLE001 - một capability lỗi không chặn các capability khác
            ctx.stage_errors.append({"stage": f"capability:{name}", "error": f"{type(exc).__name__}: {exc}",
                                     "traceback": traceback.format_exc(limit=3)})
            ctx.finding("pipeline.capability_failed", Severity.WARN,
                        f"Capability '{name}' lỗi và bị bỏ qua: {exc}", scope="table")
            continue
        if res is not None:
            ctx.capabilities[name] = res


def _stage_transform(ctx: Context) -> None:
    import tseda.transform.advisor  # noqa: F401 - nạp để đăng ký
    from tseda.core.registry import ADVISORS
    from tseda.transform.plan import TransformPlan

    steps = []
    for advisor in ADVISORS:
        steps.extend(advisor(ctx))
    plan = TransformPlan(steps)
    if ctx.cfg["transform.auto_accept_safe"]:
        plan.auto_accept_safe()
    ctx.plan = plan


def _stage_viz(ctx: Context) -> None:
    from tseda.viz.plots import build_figures
    build_figures(ctx)


STAGES: dict[str, Callable[[Context], None]] = {
    "typing": _stage_typing,
    "quality": _stage_quality,
    "profile": _stage_profile,
    "relate": _stage_relate,
    "capability": _stage_capability,
    "transform": _stage_transform,
    "viz": _stage_viz,
}


def _resolve_domain(domain: Any):
    if domain is None:
        return None
    from tseda.domain import get_domain
    from tseda.domain.base import DomainPlugin
    if isinstance(domain, DomainPlugin):
        return domain
    return get_domain(str(domain))


class EDA:
    """Điểm vào chính.

    >>> report = EDA("data.csv", out_dir="out").run()
    >>> report.summary()
    """

    def __init__(
        self,
        source: Any,
        *,
        config: dict | str | Path | Config | None = None,
        schema: dict[str, str] | None = None,
        domain: Any = None,
        name: str | None = None,
        out_dir: str | Path | None = None,
        query: str | None = None,
        connection: str | None = None,
        max_rows: int | None = None,
        **load_kwargs: Any,
    ):
        from tseda.io.readers import load

        if isinstance(source, RawTable):
            table = source
        else:
            table = load(source, query=query, connection=connection, max_rows=max_rows, **load_kwargs)
        if name:
            table.name = name
        if isinstance(config, Config):
            cfg = config
        elif isinstance(config, (str, Path)):
            cfg = Config.from_file(config)
        else:
            cfg = Config(config or {})
        plugin = _resolve_domain(domain if domain is not None else cfg.get("general.domain"))
        self.table = table
        self.cfg = cfg
        self.ctx = Context(table, cfg, schema=schema, domain=plugin, out_dir=out_dir)

    def run(self, stages: list[str] | None = None) -> EDAReport:
        requested = list(stages) if stages else list(self.cfg["general.stages"])
        unknown = set(requested) - set(STAGE_ORDER)
        if unknown:
            raise ValueError(f"Stage không tồn tại: {sorted(unknown)}. Hợp lệ: {STAGE_ORDER}")
        for name in STAGE_ORDER:
            if name not in requested:
                continue
            try:
                STAGES[name](self.ctx)
                self.ctx.stages_run.append(name)
            except Exception as exc:  # noqa: BLE001
                self.ctx.stage_errors.append({"stage": name, "error": f"{type(exc).__name__}: {exc}",
                                              "traceback": traceback.format_exc(limit=4)})
                self.ctx.finding("pipeline.stage_failed", Severity.CRITICAL,
                                 f"Stage '{name}' lỗi: {exc}", scope="table")
                if name == "typing":
                    break  # không có vai trò thì các stage sau vô nghĩa
        return self._report()

    def _report(self) -> EDAReport:
        ctx = self.ctx
        return EDAReport(
            name=self.table.name,
            source=self.table.source,
            shape=(int(ctx.df.shape[0]), int(ctx.df.shape[1])),
            config=self.cfg.to_dict(),
            roles=ctx.roles,
            profiles=ctx.profiles,
            relations=ctx.relations,
            vif=ctx.vif,
            capabilities=ctx.capabilities,
            quality=ctx.quality,
            findings=ctx.findings,
            decisions=ctx.decisions,
            artifacts=ctx.artifacts,
            plan=ctx.plan,
            stage_errors=ctx.stage_errors,
            stages_run=ctx.stages_run,
            cleaned=pd.DataFrame(ctx.cleaned) if ctx.cleaned else pd.DataFrame(),
            typed=pd.DataFrame(ctx.typed) if ctx.typed else pd.DataFrame(),
            out_dir=ctx.out_dir,
            meta={"renamed_columns": self.table.meta.get("renamed_columns", {}),
                  "source_meta": {k: v for k, v in self.table.meta.items() if k != "renamed_columns"}},
        )
