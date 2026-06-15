from __future__ import annotations

import difflib
import re
from collections import defaultdict
from pathlib import Path

from .db import Database


REVISION_SUFFIX = re.compile(
    r"(?:[\s_.-]+пересмотр[\s_.-]+\d{4}|[\s_.-]+изм(?:енение)?[\s_.-]*\d+)$",
    re.IGNORECASE,
)
YEAR = re.compile(r"\b(20\d{2})\b")


def _group_key(filename: str) -> str:
    stem = Path(filename).stem
    stem = REVISION_SUFFIX.sub("", stem)
    return re.sub(r"[^А-ЯA-Z0-9]+", "", stem.upper())


def _revision_rank(filename: str, mtime: float) -> tuple[int, float]:
    years = [int(value) for value in YEAR.findall(filename)]
    return (max(years, default=0), mtime)


def learn_from_examples(db: Database) -> dict[str, int]:
    db.execute("DELETE FROM learned_rules")
    rows = db.rows(
        """
        SELECT id, title, mtime
        FROM documents
        WHERE role = 'example' AND status = 'ready'
        ORDER BY title
        """
    )
    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        groups[_group_key(row["title"])].append(row)

    learned: dict[tuple[str, str], dict] = {}
    pairs = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda row: _revision_rank(row["title"], float(row["mtime"])))
        before, after = group[0], group[-1]
        if before["id"] == after["id"]:
            continue
        pairs += 1
        _learn_pair(db, before, after, learned)

    with db.connect() as connection:
        for (old_text, new_text), item in learned.items():
            connection.execute(
                """
                INSERT INTO learned_rules(old_text, new_text, source, confidence, occurrences)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(old_text, new_text) DO UPDATE SET
                    source=excluded.source,
                    confidence=MAX(learned_rules.confidence, excluded.confidence),
                    occurrences=learned_rules.occurrences + excluded.occurrences
                """,
                (
                    old_text,
                    new_text,
                    item["source"],
                    item["confidence"],
                    item["occurrences"],
                ),
            )
    return {"pairs": pairs, "rules": len(learned)}


def _learn_pair(db: Database, before, after, learned: dict) -> None:
    old = [
        row["text"]
        for row in db.rows(
            "SELECT text FROM paragraphs WHERE document_id = ? ORDER BY paragraph_index",
            (before["id"],),
        )
    ]
    new = [
        row["text"]
        for row in db.rows(
            "SELECT text FROM paragraphs WHERE document_id = ? ORDER BY paragraph_index",
            (after["id"],),
        )
    ]
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    source = f"{before['title']} -> {after['title']}"
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or i2 - i1 != 1 or j2 - j1 != 1:
            continue
        old_text, new_text = old[i1], new[j1]
        if old_text == new_text or min(len(old_text), len(new_text)) < 4:
            continue
        similarity = difflib.SequenceMatcher(a=old_text, b=new_text).ratio()
        if similarity < 0.45:
            continue
        key = (old_text, new_text)
        if key not in learned:
            learned[key] = {
                "source": source,
                "confidence": similarity,
                "occurrences": 1,
            }
        else:
            learned[key]["occurrences"] += 1
            learned[key]["confidence"] = max(learned[key]["confidence"], similarity)
