"""Kiểm thử đơn vị: xử lý văn bản/số/ngày tiếng Việt và các hàm thống kê."""
from collections import Counter

import numpy as np
import pandas as pd
import pytest

from tseda.stats import timeseries as ts
from tseda.stats.association import cramers_v_bias_corrected
from tseda.stats.multiplicity import benjamini_hochberg
from tseda.stats.tests import num_cat, num_num, trend
from tseda.text import dates as tdates
from tseda.text import lang, normalize, patterns
from tseda.text import numeric as tnum


# ---------- số ----------
def test_detect_locale_vi_and_en():
    assert tnum.detect_locale(["23.500", "1.234.567", "12.000"], default="en")[0] == "vi"
    assert tnum.detect_locale(["1,234", "2,500", "12.5"], default="vi")[0] == "en"


def test_detect_locale_tie_uses_default():
    assert tnum.detect_locale(["12", "7"], default="vi")[0] == "vi"


@pytest.mark.parametrize("text, expected", [
    ("1.5tr", 1_500_000.0),
    ("2 tỷ", 2_000_000_000.0),
    ("(1.200)", -1200.0),
    ("12,5", 12.5),
    ("12,5%", 12.5),
    ("3.500đ", 3500.0),
    ("chưa thu", None),
])
def test_parse_one_vi(text, expected):
    got = tnum.parse_one(text, "vi", {"tỷ": 1e9, "tr": 1e6, "k": 1e3}, ["đ", "vnd"])
    assert got == expected


# ---------- ngày ----------
def test_best_format_uses_data_when_unambiguous():
    values = ["15/10/2026", "01/02/2025", "20/11/2024", "03/04/2025"]
    best = tdates.best_format(values, ["%m/%d/%Y", "%d/%m/%Y"], dayfirst=False)
    assert best["format"] == "%d/%m/%Y"
    assert best["dayfirst_source"] == "data"
    assert best["ambiguous"] is False


def test_best_format_flags_ambiguous_when_all_days_le_12():
    values = ["01/02/2025", "03/04/2025", "05/06/2025"]
    best = tdates.best_format(values, ["%d/%m/%Y", "%m/%d/%Y"], dayfirst=True)
    assert best["ambiguous"] is True
    assert best["format"] == "%d/%m/%Y"


# ---------- văn bản ----------
def test_mask_compressed_and_full():
    assert patterns.mask("VCB-123") == "A-9"
    assert patterns.mask("VCB-123", compress=False) == "AAA-999"


def test_structured_kind_email_and_tax_code():
    assert patterns.structured_kind(["a@b.com", "x.y@z.vn"])[0] == "email"
    assert patterns.structured_kind(["0101234567-001", "0312345678-002"])[0] == "tax_code"
    assert patterns.structured_kind(["0912 345 678", "091.234.5678"])[0] == "vn_phone"


def test_variant_groups_accent_case_and_spacing():
    counts = Counter({"Hà Nội": 300, "Ha Noi": 20, "HÀ NỘI": 10, "Hà  Nội": 4, "Đà Nẵng": 150})
    groups = normalize.variant_groups(counts, similarity=0.9)
    assert len(groups) == 1
    g = groups[0]
    assert g["canonical"] == "Hà Nội"
    assert {m["value"] for m in g["members"]} == {"Hà Nội", "Ha Noi", "HÀ NỘI", "Hà  Nội"}


def test_variant_groups_do_not_merge_different_places():
    counts = Counter({"Hà Nội": 100, "Hồ Chí Minh": 100, "Đà Nẵng": 100})
    assert normalize.variant_groups(counts, similarity=0.9) == []


def test_mojibake_and_vi_marks():
    assert lang.has_mojibake("HÃ NỘI") is True
    assert lang.has_mojibake("Hà Nội") is False
    assert lang.vi_mark_ratio("Hà Nội") > 0


def test_nfc_detection():
    decomposed = "é"
    assert normalize.is_nfc(decomposed) is False
    assert normalize.is_nfc(normalize.nfc(decomposed)) is True


# ---------- thống kê ----------
def test_benjamini_hochberg_monotone_and_keeps_none():
    # Tính tay: p sắp xếp = [0.01, 0.03, 0.04, 0.5], q thô = [0.04, 0.06, 0.0533, 0.5],
    # làm đơn điệu từ cuối lên -> [0.04, 0.0533, 0.0533, 0.5]
    q = benjamini_hochberg([0.01, 0.04, 0.03, None, 0.5])
    assert q[3] is None
    assert q[0] == pytest.approx(0.04)
    assert q[1] == pytest.approx(0.04 * 4 / 3)
    assert q[2] == pytest.approx(0.04 * 4 / 3)
    assert q[4] == pytest.approx(0.5)


def test_cramers_v_perfect_association_is_high():
    table = np.array([[50, 0], [0, 50]])
    from scipy import stats as sps
    chi2, _, _, _ = sps.chi2_contingency(table, correction=False)
    assert cramers_v_bias_corrected(table, chi2) > 0.9


def test_num_num_spearman_monotone():
    x = pd.Series(np.arange(50, dtype=float))
    res = num_num(x, x**3)
    assert res.effect == pytest.approx(1.0)
    assert res.name == "spearman"


def test_num_cat_detects_group_difference():
    rng = np.random.default_rng(0)
    labels = pd.Series(["a"] * 60 + ["b"] * 60 + ["c"] * 60)
    values = pd.Series(np.concatenate([rng.normal(0, 1, 60), rng.normal(3, 1, 60), rng.normal(6, 1, 60)]))
    res = num_cat(values, labels)
    assert res.p_value is not None and res.p_value < 1e-10
    assert res.effect_name in ("eta2", "epsilon2")


def test_num_cat_collapses_rare_levels():
    labels = pd.Series(["a"] * 100 + ["b"] * 100 + ["rare"] * 2)
    values = pd.Series(np.concatenate([np.zeros(100), np.ones(100), [5.0, 5.0]]))
    res = num_cat(values, labels, min_n=30, min_count=5)
    assert res.n == 202


def test_trend_detects_increase():
    t = np.arange(100, dtype=float)
    y = t * 0.5 + np.random.default_rng(1).normal(0, 1, 100)
    res = trend(t, y)
    assert res.effect > 0.5 and res.p_value < 1e-6


def test_acf_white_noise_small_and_threshold():
    x = np.random.default_rng(2).normal(size=2000)
    vals = ts.acf(x, 5)
    assert vals[0] == pytest.approx(1.0)
    assert abs(vals[1]) < 0.1
    assert ts.acf_threshold(2000) == pytest.approx(1.96 / np.sqrt(2000))


def test_break_candidate_finds_step_change():
    rng = np.random.default_rng(3)
    x = np.concatenate([rng.normal(0, 1, 200), rng.normal(2, 1, 200)])
    brk = ts.break_candidate(x, min_segment=20)
    assert brk is not None
    assert abs(brk["index"] - 200) <= 15
    assert brk["p"] < 0.001


def test_break_candidate_random_walk_not_flagged():
    rng = np.random.default_rng(4)
    walk = np.cumsum(rng.normal(0, 1, 500))
    brk = ts.break_candidate(walk, min_segment=20)
    assert brk is not None
    assert brk["p"] > 0.001
