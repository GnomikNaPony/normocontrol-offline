from __future__ import annotations

import re
from dataclasses import dataclass


STANDARD_PATTERNS = [
    re.compile(
        r"\bГОСТ(?:\s+Р|\s+РВ)?(?:\s+[А-ЯA-Z]{2,8})?\s+\d[\d.]*[-–—]\d{2,4}",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:НП|ОСТ|СТО|РД|РДЭО|СП|СНиП|ПНАЭ|ФНП)[-.\s]*\d[\d./-]*\d",
        re.IGNORECASE,
    ),
    re.compile(r"\bИ[-–—]\d{2}[-–—]\d{2}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:ИЭ|КУ|ПП|ТП)"
        r"(?:[./](?:[А-ЯA-Z][А-ЯA-Z0-9-]*|\d+)){2,5}"
        r"(?: [А-ЯA-Z][А-ЯA-Z0-9-]{1,7})?"
        r"(?:[./](?:[А-ЯA-Z][А-ЯA-Z0-9-]*|\d+)){1,3}\b",
        re.IGNORECASE,
    ),
]


@dataclass(frozen=True, slots=True)
class Reference:
    raw: str
    canonical: str


def canonicalize_reference(value: str) -> str:
    value = value.upper().replace("–", "-").replace("—", "-")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*-\s*", "-", value)
    value = re.sub(r"\s*\.\s*", ".", value)
    return value.strip(" \t\n.,;:")


def find_references(text: str) -> list[Reference]:
    found: dict[str, Reference] = {}
    for pattern in STANDARD_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(0).strip().rstrip(".,;:")
            canonical = canonicalize_reference(raw)
            found.setdefault(canonical, Reference(raw, canonical))
    return list(found.values())
