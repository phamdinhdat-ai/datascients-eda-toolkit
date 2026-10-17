"""Plugin bán lẻ: số lượng, đơn giá, thành tiền."""
from __future__ import annotations

from tseda.core.registry import register_domain
from tseda.domain.base import DomainPlugin, find_columns


@register_domain("retail")
class RetailDomain(DomainPlugin):
    name = "retail"
    description = "Bán lẻ: đơn hàng, số lượng, đơn giá, thành tiền, khuyến mại"

    def name_hints(self) -> dict[str, list[str]]:
        return {
            "numeric": ["so_luong", "qty", "don_gia", "unit_price", "thanh_tien", "amount", "gia_ban"],
            "datetime": ["ngay_don", "order_date", "ngay_ban"],
            "categorical": ["cua_hang", "store", "danh_muc", "category", "khu_vuc"],
            "id": ["ma_don", "order_id", "ma_sp", "sku"],
        }

    def constraints(self, columns, roles) -> list[dict]:
        rules: list[dict] = []
        cols = list(columns)
        qty = find_columns(cols, "so_luong", "qty", "quantity")
        price = find_columns(cols, "don_gia", "unit_price", "gia_ban")
        amount = find_columns(cols, "thanh_tien", "amount", "line_total")
        for c in qty + price:
            rules.append({"type": "nonnegative", "column": c, "name": f"{c} không âm"})
        if qty and price and amount:
            rules.append({"type": "product", "columns": [qty[0], price[0]], "total": amount[0], "tol": 0.001,
                          "name": f"{amount[0]} = {qty[0]} x {price[0]}"})
        return rules
