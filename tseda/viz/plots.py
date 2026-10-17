"""Biểu đồ chọn theo vai trò cột. Dùng matplotlib (Agg), xuất PNG để nhúng vào báo cáo."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


PRIMARY = "#2F6F9F"
ACCENT = "#C0504D"
MUTED = "#8C8C8C"


def _save(fig, path: Path) -> str:
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return str(path)


def hist_numeric(x: pd.Series, title: str, path: Path) -> str:
    vals = pd.to_numeric(x, errors="coerce").dropna().astype(float)
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    ax.hist(vals, bins=min(60, max(10, int(np.sqrt(len(vals))))), color=PRIMARY, alpha=0.85)
    ax.axvline(vals.median(), color=ACCENT, lw=1.2, label=f"median={vals.median():.4g}")
    ax.axvline(vals.mean(), color=MUTED, lw=1.2, ls="--", label=f"mean={vals.mean():.4g}")
    ax.set_title(title)
    ax.legend(fontsize=8, frameon=False)
    return _save(fig, path)


def bar_categorical(counts: pd.Series, title: str, path: Path, top: int = 20) -> str:
    counts = counts.head(top)[::-1]
    fig, ax = plt.subplots(figsize=(6.4, max(2.5, 0.28 * len(counts) + 1)))
    ax.barh([str(i)[:40] for i in counts.index], counts.values, color=PRIMARY)
    ax.set_title(title)
    ax.tick_params(axis="y", labelsize=8)
    return _save(fig, path)


def box_by_category(values: pd.Series, labels: pd.Series, title: str, path: Path, top: int = 12) -> str:
    frame = pd.DataFrame({"v": pd.to_numeric(values, errors="coerce"), "c": labels.astype(str)}).dropna()
    order = frame["c"].value_counts().head(top).index.tolist()
    data = [frame.loc[frame["c"] == k, "v"].to_numpy() for k in order]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.boxplot(data, tick_labels=[str(k)[:14] for k in order], showfliers=False)
    ax.tick_params(axis="x", labelrotation=45, labelsize=7)
    ax.set_title(title)
    return _save(fig, path)


def missing_bar(profiles: dict, path: Path) -> str:
    items = sorted(((k, v["missing_share"]) for k, v in profiles.items()), key=lambda kv: kv[1])
    items = [kv for kv in items if kv[1] > 0][-30:]
    fig, ax = plt.subplots(figsize=(6.4, max(2.5, 0.25 * len(items) + 1)))
    if items:
        ax.barh([k[:30] for k, _ in items], [v for _, v in items], color=ACCENT)
    ax.set_xlim(0, 1)
    ax.set_title("Tỷ lệ thiếu theo cột")
    ax.tick_params(axis="y", labelsize=8)
    return _save(fig, path)


def corr_heatmap(corr: pd.DataFrame, path: Path) -> str:
    size = max(4, 0.5 * len(corr))
    fig, ax = plt.subplots(figsize=(size, size * 0.85))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), [c[:18] for c in corr.columns], rotation=45, ha="right", fontsize=7)
    ax.set_yticks(range(len(corr)), [c[:18] for c in corr.index], fontsize=7)
    for i in range(len(corr)):
        for j in range(len(corr)):
            ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center", fontsize=6)
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title("Tương quan Spearman")
    return _save(fig, path)


def series_line(times: pd.Series, values: pd.Series, title: str, path: Path, window: int = 20) -> str:
    frame = pd.DataFrame({"t": times, "v": pd.to_numeric(values, errors="coerce")}).dropna()
    frame = frame.sort_values("t").drop_duplicates("t")
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    ax.plot(frame["t"], frame["v"], color=MUTED, lw=0.8, label="giá trị")
    if len(frame) >= window:
        ax.plot(frame["t"], frame["v"].rolling(window, min_periods=1).mean(), color=PRIMARY, lw=1.4,
                label=f"trung bình trượt {window}")
    ax.set_title(title)
    ax.legend(fontsize=8, frameon=False)
    fig.autofmt_xdate()
    return _save(fig, path)


def build_figures(ctx) -> dict[str, str]:
    out_dir = ctx.artifact_dir()
    if out_dir is None:
        return {}
    max_plots = int(ctx.cfg["report.max_plots"])
    artifacts: dict[str, str] = {}

    def add(name: str, fn, *args, **kwargs) -> None:
        if len(artifacts) >= max_plots:
            return
        path = out_dir / f"{len(artifacts) + 1:02d}_{name}.png"
        try:
            artifacts[name] = fn(*args, path=path, **kwargs)
        except Exception as exc:  # noqa: BLE001 - lỗi vẽ không được làm hỏng báo cáo
            ctx.decide(name, "viz", "bỏ qua", f"{type(exc).__name__}: {exc}")

    if ctx.profiles:
        add("missing", missing_bar, ctx.profiles)

    numeric = [c for c, g in ctx.roles.items() if g.family == "numeric" and c in ctx.typed]
    categorical = [c for c, g in ctx.roles.items()
                   if g.family == "categorical" and c in ctx.typed and ctx.typed[c].nunique() <= 60]
    for c in numeric[:12]:
        add(f"hist_{_slug(c)}", hist_numeric, ctx.typed[c], f"Phân phối: {c}")
    for c in categorical[:8]:
        counts = ctx.typed[c].dropna().astype(str).value_counts()
        add(f"bar_{_slug(c)}", bar_categorical, counts, f"Tần suất: {c}")

    if categorical and numeric:
        cat, num = categorical[0], numeric[0]
        add(f"box_{_slug(num)}_by_{_slug(cat)}", box_by_category, ctx.typed[num], ctx.typed[cat],
            f"{num} theo {cat}")

    if len(numeric) >= 2:
        frame = pd.DataFrame({c: ctx.typed[c] for c in numeric[:20]}).astype(float)
        corr = frame.corr(method="spearman")
        if corr.notna().all().all():
            add("corr", corr_heatmap, corr)

    temporal = ctx.capabilities.get("temporal")
    if temporal and temporal.get("series") and numeric:
        tcol = temporal["time_column"]
        ecol = temporal.get("entity_column")
        times = ctx.typed[tcol]
        values = ctx.typed[numeric[0]]
        label = ""
        if ecol:
            # Không vẽ gộp nhiều thực thể vào một đường: chọn thực thể có nhiều quan sát nhất.
            top = ctx.typed[ecol].value_counts().idxmax()
            mask = ctx.typed[ecol] == top
            times, values, label = times[mask], values[mask], f" [{top}]"
        add(f"ts_{_slug(numeric[0])}", series_line, times, values,
            f"{numeric[0]} theo thời gian ({tcol}){label}")
    ctx.artifacts.update(artifacts)
    return artifacts


def _slug(text: str) -> str:
    import re
    import unicodedata
    norm = unicodedata.normalize("NFD", str(text)).replace("đ", "d").replace("Đ", "D")
    norm = "".join(c for c in norm if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-zA-Z0-9]+", "_", norm).strip("_").lower()[:40] or "col"
