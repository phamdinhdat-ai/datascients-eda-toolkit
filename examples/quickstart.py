"""Ví dụ nhanh: chạy EDA trên một bảng nhỏ có lỗi và xem kết quả.

    python examples/quickstart.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

from tseda import EDA

OUT = Path("out/quickstart")


def make_demo() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 400
    return pd.DataFrame({
        "ma_kh": [f"KH{i:05d}" for i in range(n)],
        "ngay": pd.date_range("2024-01-01", periods=n, freq="D").strftime("%d/%m/%Y"),
        "so_du": [f"{v:,.0f}".replace(",", ".") for v in rng.lognormal(15, 1, n)],
        "chi_nhanh": rng.choice(["Hà Nội", "Ha Noi", "Hồ Chí Minh", "Đà Nẵng"], n),
        "co_vay": rng.choice(["Y", "N"], n),
        "ghi_chu": rng.choice(["khách hàng thanh toán đúng hạn", "cần theo dõi thêm"], n),
    })


if __name__ == "__main__":
    df = make_demo()
    report = EDA(df, name="demo", out_dir=OUT, domain="banking").run()
    report.print_summary()
    print("\nBáo cáo HTML:", OUT / "report.html")
    report.save(OUT)
