from __future__ import annotations

from pathlib import Path

from .analyzer import analyze_all
from .corrections import apply_reference_mappings, preview_reference_mappings
from .db import Database
from .extractors import (
    ExtractionError,
    extract_document,
    iter_supported_files,
    sha256_file,
)
from .learning import learn_from_examples
from .references import canonicalize_reference, find_references


VALID_ROLES = {"document", "standard", "example", "scheme"}


def import_source(db: Database, source: Path, role: str) -> dict[str, int]:
    if role not in VALID_ROLES:
        raise ValueError(f"Неизвестная роль: {role}")
    imported = 0
    errors = 0
    for path in iter_supported_files(source):
        digest = sha256_file(path)
        try:
            extracted = extract_document(path)
            document_id = db.upsert_document(path, role, digest, extracted)
            references = []
            for paragraph_index, paragraph in enumerate(extracted.paragraphs):
                references.extend(
                    (paragraph_index, reference)
                    for reference in find_references(paragraph)
                )
            db.replace_references(document_id, references)
            imported += 1
        except (ExtractionError, OSError) as exc:
            db.upsert_document(path, role, digest, None, str(exc))
            errors += 1
    return {"imported": imported, "errors": errors}


def add_mapping(db: Database, old_value: str, new_value: str) -> None:
    old_value = canonicalize_reference(old_value)
    new_value = new_value.strip()
    if not old_value or not new_value:
        raise ValueError("Старая и новая ссылки обязательны")
    with db.connect() as connection:
        connection.execute(
            """
            INSERT INTO reference_mappings(old_value, new_value)
            VALUES (?, ?)
            ON CONFLICT(old_value) DO UPDATE SET new_value=excluded.new_value, enabled=1
            """,
            (old_value, new_value),
        )


def run_analysis(db: Database) -> int:
    return analyze_all(db)


def run_learning(db: Database) -> dict[str, int]:
    return learn_from_examples(db)


def preview_corrections(db: Database) -> dict:
    return preview_reference_mappings(db)


def run_corrections(db: Database, output_directory: Path, confirmed: bool = False):
    return apply_reference_mappings(db, output_directory, confirmed=confirmed)
