"""Plugin ngân hàng: từ điển tên cột tiếng Việt/Anh và ràng buộc số liệu cơ bản.

Ràng buộc chỉ áp dụng khi tìm thấy cột tương ứng. Ngưỡng là mặc định hợp lý, có thể ghi đè
trong cấu hình `constraints.custom`.
"""
from __future__ import annotations

from tseda.core.registry import register_domain
from tseda.domain.base import DomainPlugin, find_columns


@register_domain("banking")
class BankingDomain(DomainPlugin):
    name = "banking"
    description = "Số liệu ngân hàng: dư nợ, huy động, nợ xấu, tỷ lệ an toàn vốn, cho vay/tiền gửi"

    def name_hints(self) -> dict[str, list[str]]:
        return {
            "numeric": ["du_no", "huy_dong", "tien_gui", "npl", "car", "ldr", "lai_suat", "lai suat",
                        "no_xau", "dư nợ", "tỷ lệ", "ty_le", "von", "tai_san"],
            "datetime": ["ngay_bao_cao", "ngay_gd", "ky_bao_cao", "eom", "eoq"],
            "categorical": ["chi_nhanh", "nhom_no", "loai_khach_hang", "san_pham", "ma_nhtm"],
            "id": ["so_tai_khoan", "so_hop_dong", "cif", "ma_khach_hang"],
        }

    def constraints(self, columns, roles) -> list[dict]:
        rules: list[dict] = []
        cols = list(columns)

        for c in find_columns(cols, "npl_ratio", "ty_le_no_xau", "ty le no xau", "nợ xấu tỷ lệ"):
            rules.append({"type": "range", "column": c, "min": 0, "max": 100,
                          "name": f"{c} trong [0, 100]"})
        for c in find_columns(cols, "car", "ty_le_an_toan"):
            if roles.get(c) is not None and roles[c].family == "numeric":
                rules.append({"type": "range", "column": c, "min": 0, "max": 100,
                              "name": f"{c} trong [0, 100]"})
        for c in find_columns(cols, "du_no", "outstanding", "huy_dong", "tien_gui", "deposit"):
            if roles.get(c) is not None and roles[c].family == "numeric":
                rules.append({"type": "nonnegative", "column": c, "name": f"{c} không âm"})

        # Đẳng thức: tổng dư nợ theo nhóm nợ bằng tổng các thành phần nếu có đủ cột.
        total = find_columns(cols, "tong_du_no", "du_no_tong", "total_loans")
        parts = find_columns(cols, "du_no_nhom", "du_no_trong_han", "du_no_qua_han", "no_xau_nhom")
        if total and len(parts) >= 2:
            rules.append({"type": "identity", "columns": parts, "total": total[0], "tol": 0.001,
                          "name": f"{total[0]} = tổng {len(parts)} thành phần"})

        # Cờ kéo theo: có nợ xấu thì phải có nhóm nợ.
        nx = find_columns(cols, "no_xau_flag", "is_npl")
        nhom = find_columns(cols, "nhom_no")
        if nx and nhom:
            rules.append({"type": "implies",
                          "if": {"column": nx[0], "op": "==", "value": 1},
                          "then": {"column": nhom[0], "op": "notna"},
                          "name": f"{nx[0]}=1 thì {nhom[0]} không rỗng"})
        return rules
