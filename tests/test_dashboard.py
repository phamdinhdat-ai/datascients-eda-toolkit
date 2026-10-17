"""Kiểm thử dashboard: payload hợp lệ, HTML tự chứa, an toàn khi nhúng dữ liệu, và xử lý bảng nhỏ/suy biến."""
import json
import re
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest

from fixtures import make_bank_frame
from tseda import EDA
from tseda.core.config import Config, load_default
from tseda.dashboard.payload import build_payload
from tseda.dashboard.render import render_dashboard


@pytest.fixture(scope="module")
def bank_report():
    return EDA(make_bank_frame(), name="bank_test", domain="finance").run()


def _embedded(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="tseda-data">(.*?)</script>', html, re.S)
    assert m, "thiếu khối dữ liệu nhúng"
    return json.loads(m.group(1).replace("<\\/", "</").replace("<\\!--", "<!--"))


def test_payload_has_expected_structure(bank_report):
    payload = build_payload(bank_report, Config(load_default()))
    assert payload["kpis"]["rows"] == len(bank_report.typed)
    names = [c["name"] for c in payload["columns"]]
    assert "gia_mo" in names and "ngay_gd" in names
    for c in payload["columns"]:
        assert len(c["values"]) == payload["meta"]["sample_rows"]
    kinds = {c["name"]: c["kind"] for c in payload["columns"]}
    assert kinds["gia_mo"] == "numeric"
    assert kinds["co_no_xau"] == "boolean"
    assert kinds["ngay_gd"] == "datetime"
    assert payload["meta"]["time_column"] == "ngay_gd"
    assert payload["meta"]["entity_column"] == "ma_ck"


def test_numbers_are_finite_and_json_safe(bank_report):
    html = render_dashboard(bank_report)
    data = _embedded(html)  # json.loads sẽ lỗi nếu có NaN/Infinity
    for c in data["columns"]:
        for v in c["values"]:
            assert v is None or not (isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))))


def test_html_is_self_contained_and_escaped(bank_report):
    html = render_dashboard(bank_report)
    # Không tải tài nguyên bên ngoài.
    assert not re.search(r'(src|href)="https?://', html)
    assert "<link" not in html.lower() or "rel=\"stylesheet\"" not in html.lower()
    # Dữ liệu không được đóng thẻ script sớm.
    assert html.count("</script>") == 2


def test_hostile_strings_cannot_break_out_of_script():
    df = pd.DataFrame({
        "ten": ["</script><img src=x onerror=alert(1)>", "<!-- ẩn", "bình thường"] * 20,
        "gia": np.linspace(1, 100, 60),
    })
    report = EDA(df, name="hostile").run()
    html = render_dashboard(report)
    assert html.count("</script>") == 2
    # Khối JSON không được phép có thẻ thoát ra ngoài; chuỗi "<img" nằm trong JSON là vô hại
    # vì khối có type="application/json" và giao diện chèn dữ liệu bằng textContent.
    assert "</script><img" not in html
    data = _embedded(html)
    assert any("</script>" in (v or "") for v in data["columns"][0]["values"])


def test_sampling_is_declared_for_large_tables():
    n = 5000
    df = pd.DataFrame({"x": np.arange(n, dtype=float), "nhom": ["A", "B"] * (n // 2)})
    report = EDA(df, name="big", config={"dashboard": {"max_rows": 500}}).run()
    payload = build_payload(report, Config(report.config))
    assert payload["meta"]["sampled"] is True
    assert payload["meta"]["sample_rows"] == 500
    assert payload["meta"]["total_rows"] == n


def test_tiny_and_degenerate_tables_render():
    for df in [
        pd.DataFrame({"x": [1.0]}),
        pd.DataFrame({"x": ["a"] * 5}),
        pd.DataFrame({"x": [None, None, None]}),
        pd.DataFrame(),
    ]:
        report = EDA(df, name="deg").run()
        html = render_dashboard(report)
        assert "<html" in html and html.count("</script>") == 2


def test_column_cap_is_declared(bank_report):
    data = load_default()
    data["dashboard"]["max_columns"] = 4
    cfg = Config(data)
    payload = build_payload(bank_report, cfg)
    assert len(payload["columns"]) == 4
    assert payload["meta"]["columns_truncated"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="cần Node để kiểm tra cú pháp JS")
def test_dashboard_js_parses(tmp_path):
    from importlib import resources
    js = resources.files("tseda.dashboard").joinpath("assets", "dashboard.js")
    f = tmp_path / "dashboard.js"
    f.write_text(js.read_text(encoding="utf-8"), encoding="utf-8")
    res = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_save_writes_dashboard(tmp_path, bank_report):
    written = bank_report.save(tmp_path)
    assert (tmp_path / "dashboard.html").exists()
    assert written["dashboard_html"].endswith("dashboard.html")
