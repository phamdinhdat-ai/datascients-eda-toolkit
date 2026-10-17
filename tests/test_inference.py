"""Kiểm thử suy luận vai trò và ép kiểu trên dữ liệu có lỗi đã biết."""
import numpy as np
import pandas as pd
import pytest

from fixtures import make_bank_frame
from tseda.core.config import Config
from tseda.core.roles import Role
from tseda.infer.clean import clean_series
from tseda.infer.coerce import coerce
from tseda.infer.infer import infer_roles


@pytest.fixture(scope="module")
def bank_roles():
    df = make_bank_frame()
    roles, cleaned, info = infer_roles(df, Config())
    return df, roles, cleaned, info


EXPECTED = {
    "ma_giao_dich": Role.ID,
    "ma_ck": Role.CATEGORICAL_NOMINAL,
    "ngay_gd": Role.DATETIME,
    "gia_mo": Role.NUMERIC_STORED_AS_TEXT,
    "gia_cao": Role.NUMERIC_STORED_AS_TEXT,
    "gia_thap": Role.NUMERIC_STORED_AS_TEXT,
    "gia_dong": Role.NUMERIC_STORED_AS_TEXT,
    "khoi_luong": Role.NUMERIC_STORED_AS_TEXT,
    "so_tien": Role.MIXED,
    "chi_nhanh": Role.CATEGORICAL_NOMINAL,
    "vung": Role.CATEGORICAL_NOMINAL,
    "muc_rui_ro": Role.CATEGORICAL_ORDINAL,
    "co_no_xau": Role.BOOLEAN,
    "du_no": Role.NUMERIC_STORED_AS_TEXT,
    "ghi_chu": Role.CATEGORICAL_NOMINAL,  # 4 câu lặp lại: là category, không phải văn bản tự do
}


@pytest.mark.parametrize("column, role", list(EXPECTED.items()))
def test_bank_roles_match_planted_truth(bank_roles, column, role):
    _, roles, _, _ = bank_roles
    assert roles[column].role == role, f"{column}: {roles[column].role} (alt {roles[column].alternatives})"


def test_sentinels_become_missing(bank_roles):
    _, _, cleaned, info = bank_roles
    assert info["gia_dong"]["sentinel_strings"] >= 1
    assert cleaned["gia_dong"].isna().sum() == info["gia_dong"]["sentinel_strings"]
    assert info["chi_nhanh"]["sentinel_strings"] >= 1


def test_numeric_text_coerces_with_vi_locale(bank_roles):
    _, roles, cleaned, _ = bank_roles
    typed, info = coerce(cleaned["gia_mo"], roles["gia_mo"], Config())
    assert info["locale"] == "vi"
    assert info["parse_rate"] == 1.0
    assert typed.dropna().iloc[0] > 1000  # '23.500' phải thành 23500, không phải 23.5


def test_mixed_column_reports_text_part(bank_roles):
    _, roles, cleaned, _ = bank_roles
    typed, info = coerce(cleaned["so_tien"], roles["so_tien"], Config())
    assert 0.6 < info["parse_rate"] < 0.9
    assert info["text_part_count"] > 0


def test_native_dtypes_are_recognised():
    df = pd.DataFrame({
        "gia": np.random.default_rng(0).lognormal(3, 1, 300),
        "so_luong": np.random.default_rng(1).integers(0, 5, 300),
        "dat": np.random.default_rng(2).random(300) > 0.5,
        "ngay": pd.date_range("2024-01-01", periods=300, freq="D"),
        "ma": [f"K{i:05d}" for i in range(300)],
    })
    roles, _, _ = infer_roles(df, Config())
    assert roles["gia"].role == Role.NUMERIC_CONTINUOUS
    assert roles["so_luong"].role in (Role.CATEGORICAL_ORDINAL, Role.CATEGORICAL_NOMINAL, Role.NUMERIC_COUNT)
    assert roles["dat"].role == Role.BOOLEAN
    assert roles["ngay"].role == Role.DATETIME
    assert roles["ma"].role == Role.ID


def test_schema_override_wins():
    df = pd.DataFrame({"x": ["1", "2", "3"] * 20})
    roles, _, _ = infer_roles(df, Config(), schema={"x": "categorical_nominal"})
    assert roles["x"].role == Role.CATEGORICAL_NOMINAL
    assert roles["x"].source == "schema"
    assert roles["x"].confidence == 1.0


def test_schema_invalid_role_raises():
    df = pd.DataFrame({"x": ["1", "2"]})
    with pytest.raises(ValueError, match="không hợp lệ"):
        infer_roles(df, Config(), schema={"x": "khong_ton_tai"})


def test_all_missing_column_is_empty():
    df = pd.DataFrame({"x": ["", "N/A", "null", None]})
    roles, _, _ = infer_roles(df, Config())
    assert roles["x"].role == Role.EMPTY


def test_constant_column():
    df = pd.DataFrame({"x": ["A"] * 50})
    roles, _, _ = infer_roles(df, Config())
    assert roles["x"].role == Role.CONSTANT


def test_clean_series_only_touches_strings():
    s = pd.Series([1, 2, -1])
    out, info = clean_series(s, ["-1"])
    assert info["sentinel_strings"] == 0
    assert out.tolist() == [1, 2, -1]


def test_free_text_with_many_unique_values_is_text_free():
    rng = np.random.default_rng(5)
    words = ["hồ", "sơ", "vay", "tài", "sản", "bảo", "đảm", "chậm", "trả", "lãi", "khách", "hàng", "gia", "hạn"]
    texts = [" ".join(rng.choice(words, size=14)) + f" ref{i}" for i in range(400)]
    roles, _, _ = infer_roles(pd.DataFrame({"mo_ta": texts}), Config())
    assert roles["mo_ta"].role == Role.TEXT_FREE


def test_person_names_are_text_short():
    rng = np.random.default_rng(6)
    first = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng"]
    mid = ["Văn", "Thị", "Minh", "Quốc", "Ngọc"]
    last = ["An", "Bình", "Cường", "Dũng", "Hà", "Khánh", "Linh", "Mai", "Nam", "Oanh", "Phúc", "Quang"]
    names = [f"{rng.choice(first)} {rng.choice(mid)} {rng.choice(last)} {i}" for i in range(400)]
    roles, _, _ = infer_roles(pd.DataFrame({"ten": names}), Config())
    assert roles["ten"].role in (Role.TEXT_SHORT, Role.TEXT_FREE)
    assert roles["ten"].role == Role.TEXT_SHORT
