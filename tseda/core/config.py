"""Cấu hình: nạp YAML mặc định, gộp file người dùng, truy cập bằng khóa dạng dấu chấm."""
from __future__ import annotations

import copy
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

_MISSING = object()


def _deep_merge(base: dict, override: dict | None) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_default() -> dict:
    text = resources.files("tseda.core").joinpath("default_config.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


class Config:
    """Bọc một dict cấu hình. Truy cập bằng `cfg["typing.min_confidence"]` hoặc `cfg.get(...)`."""

    def __init__(self, data: dict | None = None):
        self._data = _deep_merge(load_default(), data or {})

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        with open(path, encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh) or {})

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, dotted: str) -> Any:
        value = self.get(dotted, _MISSING)
        if value is _MISSING:
            raise KeyError(f"Thiếu khóa cấu hình: {dotted}")
        return value

    def section(self, name: str) -> dict:
        return copy.deepcopy(self._data.get(name, {}))

    def to_dict(self) -> dict:
        return copy.deepcopy(self._data)
