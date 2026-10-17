"""Kiểm thử đọc dữ liệu (CSV/JSON/SQL/…) và transform plan (duyệt, áp dụng, xuất/nạp)."""
import json

import pandas as pd
import pytest

from tseda.io.readers import load, read_csv, read_json, sniff_encoding, sniff_sep
from tseda.transform import ops
from tseda.transform.plan import TransformPlan, TransformStep


def test_csv_semicolon_and_latin_encoding(tmp_path):
    p = tmp_path / "x.csv"
    p.write_bytes("ten;so_tien\nHà Nội;1.500\nĐà Nẵng;2.000\n".encode("utf-8"))
    assert sniff_sep(p, sniff_encoding(p)) == ";"
    table = read_csv(p)
    assert table.shape == (2, 2)
    assert table.df["so_tien"].tolist() == ["1.500", "2.000"]  # chuỗi thô, chưa ép kiểu


def test_csv_keeps_na_literal_as_string(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\nNA,1\nnull,2\n", encoding="utf-8")
    table = read_csv(p)
    assert table.df["a"].tolist() == ["NA", "null"]


def test_duplicate_and_blank_column_names_are_renamed(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text(" a ,a,,\n1,2,3,4\n", encoding="utf-8")
    table = read_csv(p)
    assert len(set(table.columns)) == len(table.columns)
    assert table.columns[0] == "a"
    assert "renamed_columns" in table.meta


def test_json_records_are_flattened(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps([{"id": 1, "kh": {"ten": "A", "tuoi": 30}}, {"id": 2, "kh": {"ten": "B", "tuoi": 40}}]),
                 encoding="utf-8")
    table = read_json(p)
    assert "kh.ten" in table.columns and "kh.tuoi" in table.columns


def test_jsonl(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    assert load(p).shape == (2, 1)


def test_sqlite_via_connection_string(tmp_path):
    sqlalchemy = pytest.importorskip("sqlalchemy")
    db = tmp_path / "t.db"
    engine = sqlalchemy.create_engine(f"sqlite:///{db}")
    pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "c"]}).to_sql("t", engine, index=False)
    engine.dispose()
    table = load(f"sqlite:///{db}", query="select * from t")
    assert table.shape == (3, 2)
    assert table.meta["format"] == "sql"


def test_sql_file_requires_connection(tmp_path):
    p = tmp_path / "q.sql"
    p.write_text("select 1", encoding="utf-8")
    with pytest.raises(ValueError, match="connection"):
        load(p)


def test_unsupported_format(tmp_path):
    p = tmp_path / "x.xyz"
    p.write_text("a", encoding="utf-8")
    with pytest.raises(ValueError, match="Không hỗ trợ"):
        load(p)


# ---------- ops ----------
def test_parse_numeric_op_matches_locale():
    s = pd.Series(["23.500", "1.5tr", "chưa thu"])
    out = ops.parse_numeric(s, "vi", {"tr": 1e6}, [])
    assert out.iloc[0] == 23500
    assert out.iloc[1] == 1.5e6
    assert pd.isna(out.iloc[2])


def test_to_missing_and_canonicalize_and_boolean():
    s = pd.Series(["N/A", "Hà Nội", "Ha Noi", None])
    assert ops.to_missing(s, ["n/a"]).isna().iloc[0]
    assert ops.canonicalize(s, {"Ha Noi": "Hà Nội"}).tolist()[2] == "Hà Nội"
    b = ops.map_boolean(pd.Series(["Y", "N", "?"]), ["Y"], ["N"])
    assert b.tolist()[:2] == [True, False] and pd.isna(b.iloc[2])


def test_winsorize_and_log1p():
    s = pd.Series([1.0, 2.0, 3.0, 1000.0])
    w = ops.winsorize(s, 0.0, 0.75)
    assert w.max() < 1000
    assert ops.log1p(s).iloc[0] == pytest.approx(0.6931, rel=1e-3)


# ---------- plan ----------
def _plan():
    return TransformPlan([
        TransformStep(id="to_missing:a:1", column="a", op="to_missing", params={"values": ["N/A"]}, safe=True),
        TransformStep(id="parse_numeric:b:1", column="b", op="parse_numeric",
                      params={"locale": "vi", "suffix_map": {}, "currency": []}),
        TransformStep(id="log1p:c:1", column="c", op="log1p", params={}),
    ])


def test_plan_apply_only_accepted_and_original_untouched():
    df = pd.DataFrame({"a": ["N/A", "x"], "b": ["1.000", "2.000"], "c": ["1", "2"]})
    plan = _plan()
    plan.accept(["to_missing:a:1"])
    out, logs = plan.apply(df)
    assert out["a"].isna().iloc[0]
    assert df["a"].iloc[0] == "N/A"  # bản gốc không đổi
    statuses = {l.step_id: l.status for l in logs}
    assert statuses["parse_numeric:b:1"] == "skipped"
    assert statuses["to_missing:a:1"] == "applied"


def test_plan_apply_all_and_failure_is_reported():
    df = pd.DataFrame({"a": ["N/A"], "b": ["1"], "c": ["oops"]})
    plan = _plan()
    plan.accept()
    plan.add(TransformStep(id="bad:x:1", column="a", op="khong_co", params={}, accepted=True))
    out, logs = plan.apply(df)
    statuses = {l.step_id: l.status for l in logs}
    assert statuses["bad:x:1"] == "failed"
    assert statuses["to_missing:a:1"] == "applied"


def test_plan_roundtrip_yaml_and_json(tmp_path):
    plan = _plan()
    plan.accept(["to_missing:a:1"])
    for name in ("plan.yaml", "plan.json"):
        path = plan.save(tmp_path / name)
        loaded = TransformPlan.load(path)
        assert [s.id for s in loaded.steps] == [s.id for s in plan.steps]
        assert loaded.steps[0].accepted is True


def test_plan_summary_frame():
    df = _plan().summary()
    assert set(["id", "column", "op", "safe", "accepted"]).issubset(df.columns)
