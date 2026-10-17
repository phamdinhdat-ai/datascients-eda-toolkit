"""tseda: EDA thích ứng cho dữ liệu bảng (số, category, text, ngày, cờ, ID; có capability chuỗi thời gian, panel, phân cấp, ràng buộc).

Ví dụ:
    from tseda import EDA
    report = EDA("data.csv", out_dir="out/eda").run()
    report.summary()
    report.filter("WARN")
    report.plan.accept()           # duyệt đề xuất
    cleaned, logs = report.apply_plan()
"""
from tseda.core.config import Config
from tseda.core.finding import Finding, Severity
from tseda.core.pipeline import EDA
from tseda.core.result import EDAReport
from tseda.core.roles import Role, RoleGuess
from tseda.core.table import RawTable
from tseda.io.readers import load
from tseda.transform.plan import TransformPlan, TransformStep

__version__ = "0.1.0"

__all__ = [
    "EDA", "EDAReport", "Config", "Finding", "Severity", "Role", "RoleGuess",
    "RawTable", "load", "TransformPlan", "TransformStep", "__version__",
]
