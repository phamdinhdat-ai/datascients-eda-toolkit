"""Báo cáo HTML tự chứa: không phụ thuộc CDN, ảnh nhúng base64, mọi chuỗi đều được escape."""
from __future__ import annotations

import base64
import html as h
import json
from datetime import datetime
from pathlib import Path

from tseda.core.finding import Severity

_CSS = """
:root{--bg:#fafafa;--fg:#1d1d1f;--muted:#6b6b6b;--card:#fff;--line:#e4e4e7;
--crit:#b42318;--warn:#b54708;--info:#175cd3;--ok:#067647}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#111214;--fg:#eaeaea;--muted:#9a9a9a;--card:#1b1c1f;--line:#2e2f33;--crit:#f97066;--warn:#fdb022;--info:#84caff;--ok:#75e0a7}}
:root[data-theme="dark"]{--bg:#111214;--fg:#eaeaea;--muted:#9a9a9a;--card:#1b1c1f;--line:#2e2f33;--crit:#f97066;--warn:#fdb022;--info:#84caff;--ok:#75e0a7}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:8px 0}h2{font-size:17px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.muted{color:var(--muted)}.cards{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:120px}
.card b{display:block;font-size:20px}
table{width:100%;border-collapse:collapse;background:var(--card);font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top;word-break:break-word}
th{color:var(--muted);font-weight:600}
.sev{font-weight:700;font-size:12px;padding:1px 6px;border-radius:4px;border:1px solid currentColor;white-space:nowrap}
.CRITICAL{color:var(--crit)}.WARN{color:var(--warn)}.INFO{color:var(--info)}
code{font-size:12px;background:var(--card);padding:0 3px;border-radius:3px}
pre{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);padding:8px;border-radius:6px;font-size:12px;overflow:auto}
details{margin:6px 0}summary{cursor:pointer}
.figs{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.figs figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px}
.figs img{width:100%;height:auto}figcaption{font-size:12px;color:var(--muted)}
.wrap{overflow-x:auto}
@media (max-width:600px){main{padding:12px}table{font-size:12px}}
"""


def _e(value) -> str:
    return h.escape("" if value is None else str(value))


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:.{digits}g}" if abs(value) < 1e-3 or abs(value) >= 1e6 else f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return _e(value)


def _short_json(obj, limit: int = 240) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_e(x)}</th>" for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _img(path: str | None) -> str:
    if not path or not Path(path).exists():
        return ""
    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f'<img alt="" src="data:image/png;base64,{data}">'


def _findings_section(report) -> str:
    order = sorted(report.findings, key=lambda f: -int(f.severity))
    if not order:
        return "<p class='muted'>Không có phát hiện nào.</p>"
    rows = []
    for f in order:
        rows.append([
            f'<span class="sev {f.severity.name}">{f.severity.name}</span>',
            f"<code>{_e(f.id)}</code>",
            _e(f.scope),
            _e(f.message),
            _e(f.suggestion),
            f"<code>{_e(_short_json(f.metric))}</code>",
        ])
    return _table(["Mức", "Mã", "Phạm vi", "Nội dung", "Gợi ý", "Số liệu"], rows)


def _columns_section(report) -> str:
    rows = []
    for c, g in list(report.roles.items())[:500]:
        prof = report.profiles.get(c, {})
        stats = prof.get("stats", {})
        highlights = []
        for key in ("mean", "median", "min", "max", "skew", "zero_share", "n_levels", "top_share",
                    "mean_len", "mean_tokens", "span_days", "n_robust_outliers", "min", "max"):
            if key in stats and stats[key] is not None:
                highlights.append(f"{key}={_fmt(stats[key])}")
        if prof.get("family") == "datetime" or g.family == "datetime":
            highlights.append(f"min={_e(stats.get('min'))}, max={_e(stats.get('max'))}")
        alt = ", ".join(f"{r.value}:{s:.2f}" for r, s in g.alternatives)
        rows.append([
            f"<code>{_e(c)}</code>",
            _e(g.role.value),
            _fmt(g.confidence, 2),
            _e(alt),
            _fmt(prof.get("missing_share", 0), 3),
            _e(" · ".join(highlights[:6])),
        ])
    return _table(["Cột", "Vai trò", "Confidence", "Phương án khác", "Tỷ lệ thiếu", "Thống kê chính"], rows)


def _relations_section(report) -> str:
    rel = [r for r in report.relations if r.test and r.test.effect is not None]
    if not rel:
        return "<p class='muted'>Không có cặp nào đủ điều kiện kiểm định.</p>"
    rel.sort(key=lambda r: -abs(r.test.effect))
    rows = []
    for r in rel[:40]:
        t = r.test
        rows.append([
            f"<code>{_e(r.col_a)}</code>", f"<code>{_e(r.col_b)}</code>", _e(r.kind), _e(t.name),
            f"{t.effect_name}={_fmt(t.effect, 3)}", _fmt(t.p_value, 3), _fmt(r.q_value, 3),
            "có" if r.significant else "không", _e(t.n),
        ])
    body = _table(["Cột A", "Cột B", "Loại cặp", "Kiểm định", "Effect", "p", "q (BH)", "Có ý nghĩa", "n"], rows)
    if report.vif:
        vif = sorted(report.vif.items(), key=lambda kv: -kv[1])
        body += "<h3>VIF</h3>" + _table(["Cột", "VIF"], [[f"<code>{_e(c)}</code>", _fmt(v, 3)] for c, v in vif])
    return body


def _capabilities_section(report) -> str:
    if not report.capabilities:
        return "<p class='muted'>Không capability nào được bật (dữ liệu không có cấu trúc thời gian, thực thể hay ràng buộc).</p>"
    parts = []
    for name, res in report.capabilities.items():
        summary = {k: v for k, v in res.items() if k not in ("series", "links", "rules")}
        parts.append(f"<h3>{_e(name)}</h3><pre>{_e(json.dumps(summary, ensure_ascii=False, default=str, indent=1))}</pre>")
        if name == "hierarchy" and res.get("links"):
            rows = [[_e(l["child"]), _e(l["parent"]), _e(l["violation_rows"]), _fmt(l["violation_share"], 4)]
                    for l in res["links"]]
            parts.append(_table(["Con", "Cha", "Dòng vi phạm", "Tỷ lệ"], rows))
        if name == "constraints" and res.get("rules"):
            rows = [[_e(r["name"]), _e(r["n_checked"]), _e(r["n_violations"]), _fmt(r["share"], 4)]
                    for r in res["rules"]]
            parts.append(_table(["Ràng buộc", "Số dòng kiểm tra", "Vi phạm", "Tỷ lệ"], rows))
        if name == "temporal":
            for s in res.get("series", [])[:20]:
                g = s.get("gaps", {})
                parts.append(f"<details><summary>Chuỗi: {_e(s['label'])} (n={s['n_obs']}, tần suất={_e(g.get('freq'))})</summary>"
                             f"<pre>{_e(json.dumps(s, ensure_ascii=False, default=str, indent=1))[:6000]}</pre></details>")
    return "".join(parts)


def _plan_section(report) -> str:
    if report.plan is None or not report.plan.steps:
        return "<p class='muted'>Không có đề xuất biến đổi.</p>"
    rows = []
    for s in report.plan.steps:
        rows.append([
            f"<code>{_e(s.id)}</code>", f"<code>{_e(s.column)}</code>", _e(s.op),
            "an toàn" if s.safe else "cần xác nhận",
            "đã chấp nhận" if s.accepted else "chưa chấp nhận",
            _e(s.reason), f"<code>{_e(_short_json(s.impact))}</code>",
        ])
    note = ("<p class='muted'>Framework chỉ đề xuất. Duyệt bằng <code>plan.accept([...])</code> rồi "
            "<code>report.apply_plan()</code>. File <code>transform_plan.yaml</code> để tái sử dụng.</p>")
    return note + _table(["Bước", "Cột", "Phép", "Mức", "Trạng thái", "Lý do", "Tác động"], rows)


def _decisions_section(report) -> str:
    if not report.decisions:
        return ""
    rows = [[_e(d.scope), _e(d.step), _e(d.choice), _e(d.reason)] for d in report.decisions[:800]]
    return ("<details><summary>Nhật ký phương pháp đã dùng và lý do (" + str(len(report.decisions)) + " mục)</summary>"
            + _table(["Phạm vi", "Bước", "Lựa chọn", "Lý do"], rows) + "</details>")


def _figures_section(report, max_figs: int) -> str:
    items = list(report.artifacts.items())[:max_figs]
    if not items:
        return "<p class='muted'>Không có biểu đồ (chưa truyền out_dir hoặc tắt stage viz).</p>"
    figs = "".join(f"<figure>{_img(path)}<figcaption>{_e(name)}</figcaption></figure>" for name, path in items)
    return f'<div class="figs">{figs}</div>'


def render_html(report) -> str:
    counts = {s.name: 0 for s in Severity}
    for f in report.findings:
        counts[f.severity.name] += 1
    cards = (
        f'<div class="card"><span class="muted">Số dòng</span><b>{report.shape[0]:,}</b></div>'
        f'<div class="card"><span class="muted">Số cột</span><b>{report.shape[1]}</b></div>'
        f'<div class="card"><span class="muted">CRITICAL</span><b class="CRITICAL">{counts["CRITICAL"]}</b></div>'
        f'<div class="card"><span class="muted">WARN</span><b class="WARN">{counts["WARN"]}</b></div>'
        f'<div class="card"><span class="muted">INFO</span><b class="INFO">{counts["INFO"]}</b></div>'
        f'<div class="card"><span class="muted">Capability</span><b>{len(report.capabilities)}</b></div>'
    )
    errors = ""
    if report.stage_errors:
        errors = "<h2>Lỗi trong quá trình chạy</h2>" + _table(
            ["Stage", "Lỗi"], [[_e(e["stage"]), _e(e["error"])] for e in report.stage_errors])
    max_figs = int(report.config.get("report", {}).get("max_plots", 40))
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EDA: {_e(report.name)}</title><style>{_CSS}</style></head>
<body><main>
<h1>Báo cáo EDA: {_e(report.name)}</h1>
<p class="muted">Nguồn: <code>{_e(report.source)}</code> · Stage: {_e(", ".join(report.stages_run))} · Tạo lúc {now}</p>
<div class="cards">{cards}</div>
{errors}
<h2>Phát hiện</h2>{_findings_section(report)}
<h2>Cột và vai trò</h2>{_columns_section(report)}
<h2>Quan hệ giữa các cột</h2>{_relations_section(report)}
<h2>Capability</h2>{_capabilities_section(report)}
<h2>Đề xuất biến đổi</h2>{_plan_section(report)}
<h2>Biểu đồ</h2>{_figures_section(report, max_figs)}
<h2>Phương pháp đã dùng</h2>{_decisions_section(report)}
</main></body></html>"""
