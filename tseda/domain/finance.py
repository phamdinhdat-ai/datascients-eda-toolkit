"""Plugin tài chính/thị trường: giá, khối lượng, lịch giao dịch. Chỉ là từ điển và ràng buộc."""
from __future__ import annotations

from tseda.core.registry import register_domain
from tseda.domain.base import DomainPlugin, find_columns


@register_domain("finance")
class FinanceDomain(DomainPlugin):
    name = "finance"
    description = "Giá và khối lượng giao dịch: OHLCV, mã chứng khoán, giá trị giao dịch"

    def name_hints(self) -> dict[str, list[str]]:
        return {
            "numeric": ["open", "high", "low", "close", "gia", "khoi_luong", "volume", "gtgd", "vol"],
            "datetime": ["ngay_gd", "trading_date", "date", "ngay"],
            "categorical": ["ma_ck", "symbol", "ticker", "san", "exchange"],
            "id": ["ma_ck", "ticker", "symbol"],
        }

    def constraints(self, columns, roles) -> list[dict]:
        rules: list[dict] = []
        cols = list(columns)
        o = find_columns(cols, "open", "gia_mo")
        hi = find_columns(cols, "high", "gia_cao")
        lo = find_columns(cols, "low", "gia_thap")
        cl = find_columns(cols, "close", "gia_dong")

        # OHLC: low <= open, close <= high (và low <= high)
        if lo and hi:
            rules.append({"type": "order", "lower": lo[0], "upper": hi[0], "name": f"{lo[0]} <= {hi[0]}"})
        if lo and o:
            rules.append({"type": "order", "lower": lo[0], "upper": o[0], "name": f"{lo[0]} <= {o[0]}"})
        if lo and cl:
            rules.append({"type": "order", "lower": lo[0], "upper": cl[0], "name": f"{lo[0]} <= {cl[0]}"})
        if o and hi:
            rules.append({"type": "order", "lower": o[0], "upper": hi[0], "name": f"{o[0]} <= {hi[0]}"})
        if cl and hi:
            rules.append({"type": "order", "lower": cl[0], "upper": hi[0], "name": f"{cl[0]} <= {hi[0]}"})

        for col in find_columns(cols, "volume", "khoi_luong", "vol"):
            if roles.get(col) is not None and roles[col].family == "numeric":
                rules.append({"type": "nonnegative", "column": col, "name": f"{col} không âm"})
        for col in find_columns(cols, "close", "gia_dong", "gia_khop"):
            if roles.get(col) is not None and roles[col].family == "numeric":
                rules.append({"type": "range", "column": col, "min": 0, "name": f"{col} > 0"})
        return rules
