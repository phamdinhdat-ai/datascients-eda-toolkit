"""Kiểm thử end-to-end: chạy đầy đủ pipeline trên dữ liệu có lỗi đã gài và kiểm tra các phát hiện."""
import json

import numpy as np
import pandas as pd
import pytest

from fixtures import write_csv
from tseda import EDA, Severity


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("bank")
    path = write_csv(tmp / "bank.csv")
    return EDA(path, out_dir=tmp / "out", domain="finance").run()


def _ids(report):
    return {f.id for f in report.findings}


def test_no_stage_errors(report):
    assert report.stage_errors == []
    assert report.stages_run == ["typing", "quality", "profile", "relate", "capability", "transform", "viz"]


def test_planted_duplicate_rows_detected(report):
    assert report.quality["duplicate_rows"] == 3


def test_planted_variants_detected(report):
    f = [x for x in report.findings if x.id == "categorical.variants"]
    assert f and f[0].scope == "chi_nhanh"
    groups = f[0].metric["examples"]
    assert any(g["canonical"] == "Hà Nội" for g in groups)


def test_planted_mixed_column_detected(report):
    assert any(x.id == "mixed.column" and x.scope == "so_tien" for x in report.findings)


def test_planted_frozen_series_detected(report):
    stale = [x for x in report.findings if x.id == "temporal.stale"]
    assert stale, "không phát hiện chuỗi đóng băng của HPG"
    assert any(x.metric["longest"] >= 16 for x in stale)


def test_planted_missing_trading_days_detected(report):
    series = {s["label"]: s for s in report.capabilities["temporal"]["series"]}
    assert series["FPT"]["gaps"]["n_missing"] == 15
    assert series["VCB"]["gaps"]["n_missing"] == 0


def test_entity_is_symbol_not_branch(report):
    assert report.capabilities["panel"]["entity_column"] == "ma_ck"
    assert report.capabilities["temporal"]["entity_column"] == "ma_ck"


def test_planted_ohlc_violations_counted(report):
    rules = {r["name"]: r for r in report.capabilities["constraints"]["rules"]}
    assert rules["gia_thap <= gia_cao"]["n_violations"] == 5
    assert rules["gia_mo <= gia_cao"]["n_violations"] == 5


def test_hierarchy_confirmed(report):
    links = report.capabilities["hierarchy"]["links"]
    assert any(l["child"] == "chi_nhanh" and l["parent"] == "vung" and l["violation_rows"] == 0 for l in links)


def test_duplicate_keys_is_critical(report):
    crit = [x for x in report.findings if x.id == "panel.duplicate_keys"]
    assert crit and crit[0].severity == Severity.CRITICAL


def test_no_false_break_on_price_random_walk(report):
    breaks = [x for x in report.findings if x.id == "temporal.break"]
    assert len(breaks) == 0


def test_relations_use_multiplicity_correction(report):
    tested = [r for r in report.relations if r.test and r.test.p_value is not None]
    assert tested
    assert all(r.q_value is not None for r in tested)
    assert any(d.step == "multiplicity" for d in report.decisions)


def test_plan_is_not_auto_accepted(report):
    assert report.plan.steps
    assert not any(s.accepted for s in report.plan.steps if not s.safe)


def test_apply_plan_only_accepted(report):
    cleaned, logs = report.apply_plan()
    assert all(l.status == "skipped" for l in logs)
    assert cleaned.shape == report.cleaned.shape


def test_apply_accepted_parse_numeric(report):
    plan = report.plan
    plan.accept([s.id for s in plan.steps if s.op == "parse_numeric" and s.column == "gia_mo"])
    out, logs = report.apply_plan(plan)
    applied = [l for l in logs if l.status == "applied"]
    assert applied
    assert pd.api.types.is_float_dtype(out["gia_mo"])
    assert out["gia_mo"].dropna().iloc[0] > 1000
    plan.reject([s.id for s in plan.steps])


def test_html_report_escapes_and_has_sections(report, tmp_path):
    html = report.to_html(tmp_path / "r.html")
    assert "Báo cáo EDA" in html
    assert "<script" not in html
    assert "Phương pháp đã dùng" in html
    assert html.count("data:image/png;base64") >= 3


def test_save_writes_artifacts(report, tmp_path):
    written = report.save(tmp_path / "out")
    assert json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))["shape"][0] == report.shape[0]
    assert (tmp_path / "out" / "findings.csv").exists()
    assert (tmp_path / "out" / "transform_plan.yaml").exists()
    assert "report_html" in written


def test_stage_subset_skips_capabilities(tmp_path):
    path = write_csv(tmp_path / "b.csv")
    rep = EDA(path).run(stages=["typing", "profile"])
    assert rep.capabilities == {}
    assert rep.relations == []
    assert rep.stages_run == ["typing", "profile"]


def test_unknown_stage_raises(tmp_path):
    path = write_csv(tmp_path / "b.csv")
    with pytest.raises(ValueError, match="Stage không tồn tại"):
        EDA(path).run(stages=["khong_co"])


def test_numeric_only_table_runs():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"a": rng.normal(size=300), "b": rng.normal(size=300) * 2 + 1,
                       "c": rng.integers(0, 1000, 300).astype(float)})
    rep = EDA(df).run()
    assert rep.stage_errors == []
    assert rep.vif is not None
    assert all(r.role.value in ("numeric_continuous", "numeric_count") for r in rep.roles.values())


def test_tiny_and_degenerate_tables_do_not_crash():
    for df in [pd.DataFrame({"x": ["1"]}), pd.DataFrame({"x": [], "y": []}),
               pd.DataFrame({"x": [None] * 5, "y": ["a"] * 5})]:
        rep = EDA(df).run()
        assert rep.stage_errors == [], rep.stage_errors


def test_banking_domain_constraints():
    df = pd.DataFrame({
        "npl_ratio": ["1.5", "2.0", "150", "0.5"] * 10,
        "du_no_nhom": ["100", "200", "300", "400"] * 10,
        "tong_du_no": ["600", "600", "600", "999"] * 10,
    })
    rep = EDA(df, domain="banking").run()
    names = {r["name"] for r in rep.capabilities["constraints"]["rules"]}
    assert any("npl_ratio" in n for n in names)
    viol = [f for f in rep.findings if f.id == "constraint.violation" and "npl_ratio" in f.scope]
    assert viol and viol[0].metric["n_violations"] == 10


def test_retail_product_constraint():
    df = pd.DataFrame({
        "so_luong": ["2", "3", "4"] * 20,
        "don_gia": ["10", "10", "10"] * 20,
        "thanh_tien": ["20", "30", "41"] * 20,
    })
    rep = EDA(df, domain="retail").run()
    rules = {r["name"]: r for r in rep.capabilities["constraints"]["rules"]}
    key = [k for k in rules if "thanh_tien" in k][0]
    assert rules[key]["n_violations"] == 20
