"""Đọc dữ liệu: CSV/TSV, JSON/JSONL, Parquet, Excel, SQL."""
from tseda.io.readers import load, read_csv, read_excel, read_json, read_parquet, read_sql

__all__ = ["load", "read_csv", "read_excel", "read_json", "read_parquet", "read_sql"]
