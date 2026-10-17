"""Ghép template, CSS, JS và dữ liệu thành một file HTML duy nhất."""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from tseda.core.config import Config, load_default
from tseda.dashboard.payload import build_payload


def _asset(name: str) -> str:
    return resources.files("tseda.dashboard").joinpath("assets", name).read_text(encoding="utf-8")


def _embed_json(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # Ngăn chuỗi dữ liệu đóng thẻ <script> sớm hoặc mở comment HTML.
    return raw.replace("</", "<\\/").replace("<!--", "<\\!--")


def render_dashboard(report, cfg: Config | dict | None = None) -> str:
    if cfg is None:
        cfg = Config(load_default())
    elif isinstance(cfg, dict):
        cfg = Config(cfg)
    payload = build_payload(report, cfg)
    title = f"tseda · {payload['meta']['name']}"
    template = _asset("dashboard.html")
    html = (template
            .replace("__TITLE__", _escape_title(title))
            .replace("__CSS__", _asset("dashboard.css"))
            .replace("__DATA__", _embed_json(payload))
            .replace("__JS__", _asset("dashboard.js")))
    return html


def _escape_title(text: str) -> str:
    import html as h
    return h.escape(text, quote=True)


def write_dashboard(report, path: str | Path, cfg: Config | dict | None = None) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_dashboard(report, cfg), encoding="utf-8")
    return out
