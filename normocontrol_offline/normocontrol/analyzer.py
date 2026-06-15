from __future__ import annotations

import re

from .db import Database
from .references import canonicalize_reference


DOUBLE_SPACE = re.compile(r"(?<=[A-Za-zА-Яа-яЁё]) {2,3}(?=[A-Za-zА-Яа-яЁё])")
SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,.;:!?])")
ASCII_HYPHEN_WITHOUT_SPACES = re.compile(r"(?<=\D)-(?=\D)")


def analyze_all(db: Database) -> int:
    db.execute("DELETE FROM findings")
    documents = db.rows(
        "SELECT id FROM documents WHERE status = 'ready' AND role = 'document'"
    )
    total = 0
    for document in documents:
        total += analyze_document(db, int(document["id"]))
    return total


def analyze_document(db: Database, document_id: int) -> int:
    paragraphs = db.rows(
        """
        SELECT paragraph_index, text
        FROM paragraphs
        WHERE document_id = ?
        ORDER BY paragraph_index
        """,
        (document_id,),
    )
    mappings = {
        canonicalize_reference(row["old_value"]): row["new_value"]
        for row in db.rows("SELECT old_value, new_value FROM reference_mappings WHERE enabled = 1")
    }
    learned_rules = db.rows(
        """
        SELECT old_text, new_text, confidence, occurrences
        FROM learned_rules
        WHERE enabled = 1
        """
    )
    findings: list[dict] = []
    for row in paragraphs:
        index = int(row["paragraph_index"])
        text = row["text"]
        spacing_matches = list(DOUBLE_SPACE.finditer(text))
        if "\t" not in text and len(spacing_matches) <= 3:
            for match in spacing_matches:
                if len(match.group(0)) <= 3:
                    findings.append(
                        {
                            "paragraph_index": index,
                            "category": "spacing",
                            "severity": "low",
                            "message": "Несколько пробелов внутри текста",
                            "original": match.group(0),
                            "suggestion": " ",
                        }
                    )
        for match in SPACE_BEFORE_PUNCTUATION.finditer(text):
            findings.append(
                {
                    "paragraph_index": index,
                    "category": "punctuation",
                    "severity": "medium",
                    "message": "Пробел перед знаком препинания",
                    "original": match.group(0),
                    "suggestion": match.group(1),
                }
            )
        for rule in learned_rules:
            if text == rule["old_text"]:
                findings.append(
                    {
                        "paragraph_index": index,
                        "category": "learned",
                        "severity": "review",
                        "message": (
                            "Найдено совпадение с исправленным ранее фрагментом "
                            f"(достоверность {float(rule['confidence']):.0%}, "
                            f"примеров {int(rule['occurrences'])})"
                        ),
                        "original": text,
                        "suggestion": rule["new_text"],
                    }
                )

    references = db.rows(
        "SELECT paragraph_index, raw, canonical FROM refs WHERE document_id = ?",
        (document_id,),
    )
    for reference in references:
        replacement = mappings.get(reference["canonical"])
        if replacement:
            findings.append(
                {
                    "paragraph_index": int(reference["paragraph_index"]),
                    "category": "outdated_reference",
                    "severity": "high",
                    "message": "Ссылка на замененный документ",
                    "original": reference["raw"],
                    "suggestion": replacement,
                }
            )

    db.add_findings(document_id, findings)
    return len(findings)
