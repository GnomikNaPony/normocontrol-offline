from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from .extractors import Annotation, ExtractedDocument
from .references import Reference


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'document',
    title TEXT NOT NULL,
    extension TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    mtime REAL NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'ready',
    error TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paragraphs (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    paragraph_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    UNIQUE(document_id, paragraph_index)
);

CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    paragraph_index INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refs (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    paragraph_index INTEGER NOT NULL,
    raw TEXT NOT NULL,
    canonical TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS refs_canonical_idx ON refs(canonical);

CREATE TABLE IF NOT EXISTS reference_mappings (
    id INTEGER PRIMARY KEY,
    old_value TEXT NOT NULL UNIQUE,
    new_value TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS learned_rules (
    id INTEGER PRIMARY KEY,
    old_text TEXT NOT NULL,
    new_text TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 0,
    UNIQUE(old_text, new_text)
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    paragraph_index INTEGER,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    original TEXT,
    suggestion TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS paragraph_fts USING fts5(
    text,
    document_id UNINDEXED,
    paragraph_index UNINDEXED,
    tokenize='unicode61'
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def upsert_document(
        self,
        path: Path,
        role: str,
        sha256: str,
        extracted: ExtractedDocument | None,
        error: str | None = None,
    ) -> int:
        status = "error" if error else "ready"
        text = extracted.text if extracted else ""
        metadata = extracted.metadata if extracted else {}
        resolved_path = str(path.resolve())
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM documents WHERE path = ?", (resolved_path,)
            ).fetchone()
            if existing is None:
                existing = connection.execute(
                    """
                    SELECT id FROM documents
                    WHERE sha256 = ? AND role = ? AND title = ? AND path != ?
                    ORDER BY imported_at DESC LIMIT 1
                    """,
                    (sha256, role, path.name, resolved_path),
                ).fetchone()
            if existing is not None:
                document_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE documents SET
                        path = ?, role = ?, title = ?, extension = ?, sha256 = ?,
                        mtime = ?, text = ?, metadata_json = ?, status = ?,
                        error = ?, imported_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        resolved_path,
                        role,
                        path.name,
                        path.suffix.lower(),
                        sha256,
                        path.stat().st_mtime,
                        text,
                        json.dumps(metadata, ensure_ascii=False),
                        status,
                        error,
                        document_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO documents
                        (path, role, title, extension, sha256, mtime, text, metadata_json, status, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolved_path,
                        role,
                        path.name,
                        path.suffix.lower(),
                        sha256,
                        path.stat().st_mtime,
                        text,
                        json.dumps(metadata, ensure_ascii=False),
                        status,
                        error,
                    ),
                )
                document_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            for table in ("paragraphs", "annotations", "refs", "findings"):
                connection.execute(f"DELETE FROM {table} WHERE document_id = ?", (document_id,))
            connection.execute(
                "DELETE FROM paragraph_fts WHERE document_id = ?", (document_id,)
            )
            if extracted:
                connection.executemany(
                    "INSERT INTO paragraphs(document_id, paragraph_index, text) VALUES (?, ?, ?)",
                    [
                        (document_id, index, paragraph)
                        for index, paragraph in enumerate(extracted.paragraphs)
                    ],
                )
                connection.executemany(
                    "INSERT INTO paragraph_fts(text, document_id, paragraph_index) VALUES (?, ?, ?)",
                    [
                        (paragraph, document_id, index)
                        for index, paragraph in enumerate(extracted.paragraphs)
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO annotations(document_id, paragraph_index, kind, text)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (document_id, item.paragraph_index, item.kind, item.text)
                        for item in extracted.annotations
                    ],
                )
            return int(document_id)

    def replace_references(
        self, document_id: int, references: Iterable[tuple[int, Reference]]
    ) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM refs WHERE document_id = ?", (document_id,))
            connection.executemany(
                """
                INSERT INTO refs(document_id, paragraph_index, raw, canonical)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (document_id, paragraph_index, reference.raw, reference.canonical)
                    for paragraph_index, reference in references
                ],
            )

    def rows(self, query: str, parameters: tuple = ()):
        with self.connect() as connection:
            return connection.execute(query, parameters).fetchall()

    def execute(self, query: str, parameters: tuple = ()) -> None:
        with self.connect() as connection:
            connection.execute(query, parameters)

    def add_findings(self, document_id: int, findings: list[dict]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM findings WHERE document_id = ?", (document_id,))
            connection.executemany(
                """
                INSERT INTO findings(
                    document_id, paragraph_index, category, severity,
                    message, original, suggestion
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        item.get("paragraph_index"),
                        item["category"],
                        item["severity"],
                        item["message"],
                        item.get("original"),
                        item.get("suggestion"),
                    )
                    for item in findings
                ],
            )

    def stats(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                "documents": connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0],
                "errors": connection.execute(
                    "SELECT COUNT(*) FROM documents WHERE status = 'error'"
                ).fetchone()[0],
                "references": connection.execute("SELECT COUNT(*) FROM refs").fetchone()[0],
                "annotations": connection.execute(
                    "SELECT COUNT(*) FROM annotations"
                ).fetchone()[0],
                "findings": connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0],
                "learned_rules": connection.execute(
                    "SELECT COUNT(*) FROM learned_rules"
                ).fetchone()[0],
            }
