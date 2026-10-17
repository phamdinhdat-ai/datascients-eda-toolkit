"""Dữ liệu tổng hợp có lỗi cố ý đã biết trước, để kiểm thử độ chính xác của suy luận và phát hiện.

Lỗi được gài có chủ đích:
  - ngày dd/mm/yyyy, chuỗi thời gian theo 4 mã (panel), FPT thiếu ~15 ngày giao dịch
  - giá số kiểu Việt (23.500), có sentinel 'N/A' và '-'
  - so_tien: 75% parse được (có hậu tố tr/tỷ), 25% là chữ -> cột hỗn hợp
  - chi_nhanh có biến thể: 'Hà Nội', 'Ha Noi', 'HÀ NỘI'
  - HPG có 16 ngày khối lượng đóng băng liên tiếp
  - 5 dòng gia_cao < gia_thap (vi phạm OHLC), 3 dòng trùng hoàn toàn
  - vung là hàm của chi_nhanh (phân cấp nhất quán)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SYMBOLS = ["VCB", "ACB", "HPG", "FPT"]
BRANCH_VUNG = {"Hà Nội": "Bắc", "Ha Noi": "Bắc", "HÀ NỘI": "Bắc",
               "Hồ Chí Minh": "Nam", "Cần Thơ": "Nam", "Đà Nẵng": "Trung"}
BRANCH_WEIGHTS = [("Hà Nội", 0.3), ("Ha Noi", 0.04), ("HÀ NỘI", 0.02),
                  ("Hồ Chí Minh", 0.3), ("Đà Nẵng", 0.2), ("Cần Thơ", 0.14)]
TEXT_NOTES = [
    "Khách hàng đã thanh toán đúng hạn trong kỳ báo cáo này",
    "Cần theo dõi thêm tình hình tài chính của doanh nghiệp",
    "Hồ sơ tài sản bảo đảm đã được bổ sung đầy đủ",
    "Chậm trả lãi hai kỳ liên tiếp, đã gửi thông báo nhắc nợ",
]


def _vi_int(x: int) -> str:
    return f"{x:,}".replace(",", ".")


def make_bank_frame(seed: int = 7, with_issues: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", "2024-06-28")
    rows: list[dict] = []
    gd = 0
    for sym in SYMBOLS:
        base = float(rng.integers(20000, 90000))
        returns = rng.normal(0, 0.012, len(dates))
        closes = base * np.exp(np.cumsum(returns))
        keep = np.ones(len(dates), dtype=bool)
        if sym == "FPT":
            drop = rng.choice(len(dates) - 5, size=15, replace=False) + 2
            keep[drop] = False
        for i, dt in enumerate(dates):
            if not keep[i]:
                continue
            c = closes[i]
            o = c * (1 + rng.normal(0, 0.004))
            h = max(o, c) * (1 + abs(rng.normal(0, 0.003)))
            lo = min(o, c) * (1 - abs(rng.normal(0, 0.003)))
            vol = int(rng.lognormal(12, 0.5))
            if sym == "HPG" and 200 <= i < 216:
                vol = 1500000
            gd += 1
            branch = rng.choice([b for b, _ in BRANCH_WEIGHTS], p=[w for _, w in BRANCH_WEIGHTS])
            r = rng.random()
            if r < 0.5:
                tien = str(int(rng.integers(100000, 9000000)))
            elif r < 0.75:
                k = int(rng.integers(1, 9))
                tien = f"{k}tr" if rng.random() < 0.5 else f"{k} tỷ"
            else:
                tien = str(rng.choice(["chưa thu", "tạm giữ", "đang xử lý"]))
            rows.append({
                "ma_giao_dich": f"GD{gd:06d}",
                "ma_ck": sym,
                "ngay_gd": dt.strftime("%d/%m/%Y"),
                "gia_mo": _vi_int(int(round(o, -1))),
                "gia_cao": _vi_int(int(round(h, -1))),
                "gia_thap": _vi_int(int(round(lo, -1))),
                "gia_dong": _vi_int(int(round(c, -1))) if rng.random() > 0.01 else "N/A",
                "khoi_luong": str(vol),
                "so_tien": tien,
                "chi_nhanh": str(branch) if rng.random() > 0.05 else "-",
                "vung": "",
                "muc_rui_ro": str(rng.choice(["thấp", "trung bình", "cao"], p=[0.5, 0.35, 0.15])),
                "co_no_xau": str(rng.choice(["Y", "N"], p=[0.08, 0.92])),
                "du_no": f"{float(rng.lognormal(16, 0.8)):.2f}",
                "so_lan_giao_dich": str(int(rng.integers(0, 6))),
                "ghi_chu": str(rng.choice(TEXT_NOTES)),
            })
    df = pd.DataFrame(rows)
    df["vung"] = df["chi_nhanh"].map(lambda b: BRANCH_VUNG.get(b, ""))
    # Gài vi phạm OHLC: gia_cao < gia_thap ở 5 dòng
    if with_issues:
        idx = df.sample(5, random_state=seed).index
        for i in idx:
            low = int(df.loc[i, "gia_thap"].replace(".", ""))
            df.loc[i, "gia_cao"] = _vi_int(low - 500)
        # 3 dòng trùng hoàn toàn
        df = pd.concat([df, df.sample(3, random_state=seed + 1)], ignore_index=True)
    return df


def write_csv(path, df: pd.DataFrame | None = None, sep: str = ",", encoding: str = "utf-8") -> str:
    df = make_bank_frame() if df is None else df
    df.to_csv(path, index=False, sep=sep, encoding=encoding)
    return str(path)
