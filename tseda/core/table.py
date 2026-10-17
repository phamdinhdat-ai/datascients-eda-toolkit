"""RawTable: bảng đầu vào giữ nguyên dữ liệu gốc, chưa ép kiểu."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class RawTable:
    df: pd.DataFrame
    name: str = "table"
    source: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        cols = [str(c).strip() for c in self.df.columns]
        seen: dict[str, int] = {}
        unique: list[str] = []
        renamed: dict[str, str] = {}
        for original, c in zip(self.df.columns, cols):
            if c == "":
                c = "unnamed"
            if c in seen:
                seen[c] += 1
                new = f"{c}_{seen[c]}"
                renamed[str(original)] = new
                c = new
            else:
                seen[c] = 1
            unique.append(c)
        self.df = self.df.copy()
        self.df.columns = unique
        if renamed:
            self.meta.setdefault("renamed_columns", {}).update(renamed)

    @classmethod
    def from_df(cls, df: pd.DataFrame, name: str = "table", source: str = "dataframe") -> "RawTable":
        return cls(df=df, name=name, source=source)

    @property
    def shape(self) -> tuple[int, int]:
        return self.df.shape

    @property
    def columns(self) -> list[str]:
        return list(self.df.columns)
