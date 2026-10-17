"""Thực thể dùng chung cho temporal, panel và dashboard: gộp biến thể an toàn, nhất quán giữa các capability."""
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from fixtures import make_bank_frame
from tseda import EDA
from tseda.capability.entity import entity_mapping


def _demo_frame():
    sys.path.insert(0, "examples")
    try:
        from quickstart import make_demo
    finally:
        sys.path.pop(0)
    return make_demo()


def test_variants_are_merged_for_entity_grouping():
    report = EDA(_demo_frame(), name="demo", domain="banking").run()
    panel = report.capabilities["panel"]
    temporal = report.capabilities["temporal"]
    assert panel["entity_column"] == temporal["entity_column"] == "chi_nhanh"
    # 'Hà Nội' và 'Ha Noi' là cùng một chi nhánh: chỉ còn 3 thực thể, không phải 4.
    assert panel["n_entities"] == 3
    m = temporal["entity_map"]
    # Cả hai biến thể cùng ánh xạ về một giá trị chuẩn (giá trị xuất hiện nhiều hơn).
    assert m["Hà Nội"] == m["Ha Noi"]


def test_bank_entity_is_unchanged():
    report = EDA(make_bank_frame(), name="bank", domain="finance").run()
    assert report.capabilities["temporal"]["entity_column"] == "ma_ck"
    assert report.capabilities["panel"]["entity_column"] == "ma_ck"
    assert report.stage_errors == []


def test_near_duplicate_names_are_not_merged_automatically():
    # Nhóm chỉ 'gần giống' (similar_key) là đề xuất, không tự gộp thực thể.
    ctx = SimpleNamespace(profiles={"ten": {"variant_groups": [
        {"canonical": "Nguyen Van An", "method": "similar_key",
         "members": [{"value": "Nguyen Van An", "count": 5}, {"value": "Nguyen Van Anh", "count": 2}]},
        {"canonical": "Hà Nội", "method": "accent_case_space",
         "members": [{"value": "Hà Nội", "count": 5}, {"value": "Ha Noi", "count": 2}]},
    ]}})
    mapping = entity_mapping(ctx, "ten")
    assert mapping["Ha Noi"] == mapping["Hà Nội"] == "Hà Nội"
    assert "Nguyen Van Anh" not in mapping
