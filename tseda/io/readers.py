"""Đọc dữ liệu từ CSV/TSV, JSON/JSONL, Parquet, Excel và SQL (chuỗi kết nối hoặc file .sql).

CSV được đọc hết dạng chuỗi để suy luận vai trò tự quyết định kiểu, giống như dữ liệu thô.
Các nguồn có kiểu gốc (SQL, Parquet, Excel, JSON) giữ nguyên kiểu gốc.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd

from tseda.core.table import RawTable

ENCODINGS = ["utf-8-sig", "utf-8", "utf-16", "cp1258", "cp1252", "latin-1"]
_SQL_SCHEMES = ("sqlite://", "postgresql", "mysql", "mssql", "oracle", "duckdb://")


def sniff_encoding(path: Path, sample_bytes: int = 1_000_000) -> str:
    raw = path.read_bytes()[:sample_bytes]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    for enc in ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def sniff_sep(path: Path, encoding: str) -> str:
    with open(path, encoding=encoding, errors="replace") as fh:
        sample = fh.read(64_000)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def read_csv(path: str | Path, encoding: str | None = None, sep: str | None = None) -> RawTable:
    path = Path(path)
    enc = encoding or sniff_encoding(path)
    delim = sep or sniff_sep(path, enc)
    df = pd.read_csv(
        path,
        sep=delim,
        encoding=enc,
        dtype=str,
        keep_default_na=False,
        na_filter=False,
        low_memory=False,
    )
    return RawTable(df=df, name=path.stem, source=str(path),
                    meta={"format": "csv", "encoding": enc, "sep": delim})


def read_json(path: str | Path) -> RawTable:
    path = Path(path)
    if path.suffix.lower() in (".jsonl", ".ndjson"):
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        df = pd.json_normalize(records, sep=".")
        fmt = "jsonl"
    else:
        obj: Any = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(obj, dict) and obj and all(isinstance(v, list) for v in obj.values()) \
                and len({len(v) for v in obj.values()}) == 1:
            df = pd.DataFrame(obj)
        elif isinstance(obj, dict) and len(obj) == 1 and isinstance(next(iter(obj.values())), list):
            df = pd.json_normalize(next(iter(obj.values())), sep=".")
        elif isinstance(obj, list):
            df = pd.json_normalize(obj, sep=".")
        else:
            df = pd.json_normalize([obj], sep=".")
        fmt = "json"
    return RawTable(df=df, name=path.stem, source=str(path), meta={"format": fmt})


def read_parquet(path: str | Path) -> RawTable:
    path = Path(path)
    return RawTable(df=pd.read_parquet(path), name=path.stem, source=str(path), meta={"format": "parquet"})


def read_excel(path: str | Path, sheet: str | int | None = 0) -> RawTable:
    path = Path(path)
    return RawTable(df=pd.read_excel(path, sheet_name=sheet), name=f"{path.stem}:{sheet}",
                    source=str(path), meta={"format": "excel", "sheet": sheet})


def read_sql(connection: str, query: str | None = None, sql_file: str | Path | None = None,
             max_rows: int | None = None, chunksize: int = 100_000, engine_kwargs: dict | None = None) -> RawTable:
    """Đọc theo chunk và dừng khi đủ max_rows. Cần cài sqlalchemy."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Cần cài sqlalchemy: pip install 'tseda[sql]'") from exc

    if sql_file is not None:
        query = Path(sql_file).read_text(encoding="utf-8")
    if not query:
        raise ValueError("Cần truyền query hoặc sql_file")

    engine = create_engine(connection, **(engine_kwargs or {}))
    frames: list[pd.DataFrame] = []
    total = 0
    with engine.connect() as conn:
        for chunk in pd.read_sql_query(text(query), conn, chunksize=chunksize):
            if max_rows is not None and total + len(chunk) > max_rows:
                chunk = chunk.iloc[: max_rows - total]
            frames.append(chunk)
            total += len(chunk)
            if max_rows is not None and total >= max_rows:
                break
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    name = Path(sql_file).stem if sql_file else "query"
    return RawTable(df=df, name=name, source=connection,
                    meta={"format": "sql", "rows_read": total, "truncated": bool(max_rows and total >= max_rows)})


def load(source: Any, *, query: str | None = None, connection: str | None = None,
         max_rows: int | None = None, **kwargs: Any) -> RawTable:
    """Điểm vào thống nhất. Nhận DataFrame, đường dẫn file, file .sql, hoặc chuỗi kết nối + query."""
    if isinstance(source, RawTable):
        return source
    if isinstance(source, pd.DataFrame):
        return RawTable.from_df(source, name=kwargs.get("name", "dataframe"))
    if isinstance(source, str) and source.lower().startswith(_SQL_SCHEMES):
        return read_sql(source, query=query, max_rows=max_rows)

    path = Path(source)
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv", ".txt"):
        return read_csv(path, encoding=kwargs.get("encoding"), sep=kwargs.get("sep"))
    if suffix in (".json", ".jsonl", ".ndjson"):
        return read_json(path)
    if suffix == ".parquet":
        return read_parquet(path)
    if suffix in (".xlsx", ".xls", ".xlsm"):
        return read_excel(path, sheet=kwargs.get("sheet", 0))
    if suffix == ".sql":
        if not connection:
            raise ValueError("Đọc file .sql cần truyền connection=<chuỗi kết nối>")
        return read_sql(connection, sql_file=path, max_rows=max_rows)
    raise ValueError(f"Không hỗ trợ định dạng '{suffix}'")
