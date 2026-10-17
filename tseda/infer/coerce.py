"""Ép kiểu cột theo vai trò đã suy luận. Đây là nguồn sự thật duy nhất cho mọi phân tích sau này."""
from __future__ import annotations

import pandas as pd

from tseda.core.roles import Role, RoleGuess
from tseda.text import dates as tdates
from tseda.text import numeric as tnum


def _bool_map(pairs: list[list[str]]) -> dict[str, bool]:
    mapping: dict[str, bool] = {}
    for t, f in pairs:
        if t:
            mapping[t.lower()] = True
        if f:
            mapping[f.lower()] = False
    return mapping


def _resolve_locale(guess: RoleGuess, cleaned: pd.Series, cfg) -> str:
    if cfg["numeric.locale"] != "auto":
        return str(cfg["numeric.locale"])
    if guess.evidence.get("locale"):
        return str(guess.evidence["locale"])
    values = cleaned.dropna().astype(str).tolist()
    locale, _ = tnum.detect_locale(values, str(cfg["numeric.default_locale"]), list(cfg["numeric.currency_tokens"]))
    return locale


def coerce(cleaned: pd.Series, guess: RoleGuess, cfg) -> tuple[pd.Series, dict]:
    role = guess.role
    info: dict = {"role": role.value}
    n_present = int(cleaned.notna().sum())

    if role in (Role.NUMERIC_STORED_AS_TEXT, Role.MIXED) and not pd.api.types.is_numeric_dtype(cleaned):
        locale = _resolve_locale(guess, cleaned, cfg)
        suffix = dict(cfg["numeric.suffix_map"])
        currency = list(cfg["numeric.currency_tokens"])
        numeric, ok = tnum.parse_series(cleaned, locale, suffix, currency)
        parsed = int(ok.sum())
        info.update({
            "locale": locale,
            "parsed": parsed,
            "parse_rate": round(parsed / n_present, 4) if n_present else 0.0,
            "unparsed_examples": tnum.unparsed_examples(cleaned, ok),
        })
        if role == Role.MIXED:
            info["text_part_count"] = int(n_present - parsed)
        return numeric, info

    if role == Role.DATETIME and not pd.api.types.is_datetime64_any_dtype(cleaned):
        fmt = guess.evidence.get("format")
        if fmt is None:
            best = tdates.best_format(cleaned.dropna().tolist(), list(cfg["typing.date_formats"]),
                                      bool(cfg["general.dayfirst"]), float(cfg["typing.parse_threshold"]))
            fmt = best["format"]
            info.update({"ambiguous": best["ambiguous"], "dayfirst_used": best["dayfirst_used"]})
        parsed = tdates.parse_dates(cleaned, fmt)
        info.update({
            "format": fmt,
            "parse_rate": round(float(parsed.notna().sum() / n_present), 4) if n_present else 0.0,
            "ambiguous": bool(guess.evidence.get("ambiguous", info.get("ambiguous", False))),
        })
        return parsed, info

    if role == Role.BOOLEAN:
        if pd.api.types.is_bool_dtype(cleaned):
            return cleaned.astype("boolean"), info
        mapping = _bool_map(cfg["typing.boolean_pairs"])
        values = cleaned.map(lambda x: None if x is None or pd.isna(x) else mapping.get(str(x).lower()))
        unknown = int(values.isna().sum() - cleaned.isna().sum())
        info["unmapped"] = max(unknown, 0)
        return pd.Series(values, index=cleaned.index, dtype="boolean"), info

    if role in (Role.NUMERIC_CONTINUOUS, Role.NUMERIC_COUNT) or (
        role in (Role.CONSTANT, Role.ID) and pd.api.types.is_numeric_dtype(cleaned)
    ):
        return pd.to_numeric(cleaned, errors="coerce").astype("float64"), info

    if role == Role.DATETIME:
        return pd.to_datetime(cleaned, errors="coerce"), info

    return cleaned.astype("object"), info
