from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import and_, or_

_LAT_TO_CYR = str.maketrans(
    {
        "A": "А",
        "a": "а",
        "B": "В",
        "E": "Е",
        "e": "е",
        "K": "К",
        "k": "к",
        "M": "М",
        "H": "Н",
        "h": "н",
        "O": "О",
        "o": "о",
        "P": "Р",
        "p": "р",
        "C": "С",
        "c": "с",
        "T": "Т",
        "t": "т",
        "X": "Х",
        "x": "х",
        "Y": "У",
        "y": "у",
    }
)
_CYR_TO_LAT = str.maketrans({v: k for k, v in _LAT_TO_CYR.items()})


def _tokens(query: str) -> list[str]:
    base = (query or "").strip()
    if not base:
        return []
    return [item for item in re.split(r"\s+", base) if item]


def _variants(token: str) -> list[str]:
    value = token.strip()
    if not value:
        return []
    result = {
        value,
        value.translate(_LAT_TO_CYR),
        value.translate(_CYR_TO_LAT),
    }
    return [item for item in result if item]


def build_ilike_filter(columns: Iterable, query: str):
    terms = _tokens(query)
    if not terms:
        return None

    and_parts = []
    columns_list = list(columns)
    for term in terms:
        token_parts = []
        for variant in _variants(term):
            pattern = f"%{variant}%"
            token_parts.extend(col.ilike(pattern) for col in columns_list)
        if token_parts:
            and_parts.append(or_(*token_parts))
    if not and_parts:
        return None
    return and_(*and_parts)


def _normalize_text(value: str) -> str:
    return value.translate(_LAT_TO_CYR).lower()


def text_matches_query(values: Iterable[str | None], query: str) -> bool:
    terms = [_normalize_text(term) for term in _tokens(query)]
    if not terms:
        return True
    haystack = " ".join((item or "") for item in values)
    normalized_haystack = _normalize_text(haystack)
    return all(term in normalized_haystack for term in terms)
