"""Suy luận vai trò cho toàn bảng: làm sạch -> thống kê -> chấm điểm -> chọn vai trò có confidence."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tseda.core.config import Config
from tseda.core.roles import TIE_PRIORITY, Role, RoleGuess
from tseda.infer.clean import clean_series
from tseda.infer.detect import build_stats, score_roles


def _choose(scores: dict[Role, tuple[float, dict]]) -> RoleGuess:
    if not scores:
        return RoleGuess(Role.MIXED, 0.0, {"reason": "không có ứng viên vai trò"}, [], "inferred")
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1][0], TIE_PRIORITY.index(kv[0])))
    best_role, (best_score, evidence) = ranked[0]
    second = ranked[1][1][0] if len(ranked) > 1 else 0.0
    gap = best_score - second
    # Hai ứng viên sát điểm nhau thì confidence bị kéo xuống để người dùng xem lại.
    confidence = best_score * (0.7 + 0.3 * min(1.0, gap / 0.2))
    evidence = dict(evidence)
    evidence["gap_to_second"] = round(float(gap), 4)
    return RoleGuess(
        role=best_role,
        confidence=round(float(confidence), 4),
        evidence=evidence,
        alternatives=[(r, round(float(s), 4)) for r, (s, _) in ranked[1:4]],
        source="inferred",
    )


def infer_roles(
    df: pd.DataFrame,
    cfg: Config,
    schema: dict[str, str] | None = None,
    extra_hints: dict[str, list[str]] | None = None,
) -> tuple[dict[str, RoleGuess], dict[str, pd.Series], dict[str, dict]]:
    """Trả về (vai trò từng cột, cột đã làm sạch, thông tin làm sạch)."""
    schema = schema or {}
    hints = {k: list(v) for k, v in cfg.section("typing").get("name_hints", {}).items()}
    for key, values in (extra_hints or {}).items():
        hints.setdefault(key, []).extend(values)
    rng = np.random.default_rng(cfg["general.seed"])

    roles: dict[str, RoleGuess] = {}
    cleaned: dict[str, pd.Series] = {}
    clean_info: dict[str, dict] = {}
    for name in df.columns:
        series, info = clean_series(df[name], list(cfg["missing.sentinel_strings"]))
        cleaned[name] = series
        clean_info[name] = info

        if name in schema:
            try:
                role = Role(str(schema[name]).lower())
            except ValueError as exc:
                valid = ", ".join(r.value for r in Role)
                raise ValueError(f"Vai trò '{schema[name]}' của cột '{name}' không hợp lệ. Chọn một trong: {valid}") from exc
            roles[name] = RoleGuess(role, 1.0, {"declared": role.value}, [], "schema")
            continue

        stats = build_stats(name, series, info["sentinel_strings"], int(cfg["typing.sample_size"]), rng)
        roles[name] = _choose(score_roles(stats, cfg, hints))
    return roles, cleaned, clean_info
