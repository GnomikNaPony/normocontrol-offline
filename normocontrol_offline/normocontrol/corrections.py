from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .db import Database


EDITABLE_WORD_PARTS = (
    "word/document.xml",
    "word/footnotes.xml",
    "word/endnotes.xml",
)


def apply_reference_mappings(
    db: Database, output_directory: Path
) -> dict[str, int | list[str]]:
    output_directory.mkdir(parents=True, exist_ok=True)
    mappings = {
        (row["raw"], row["new_value"])
        for row in db.rows(
            """
            SELECT DISTINCT refs.raw, reference_mappings.new_value
            FROM refs
            JOIN reference_mappings ON reference_mappings.old_value = refs.canonical
            WHERE reference_mappings.enabled = 1
            """
        )
    }
    documents = db.rows(
        """
        SELECT path FROM documents
        WHERE status = 'ready' AND extension = '.docx' AND role = 'document'
        """
    )
    changed_files = 0
    replacements = 0
    skipped: list[str] = []
    for document in documents:
        source = Path(document["path"])
        target = output_directory / source.parent.name / source.name
        changed = replace_in_docx(source, target, sorted(mappings))
        if changed:
            changed_files += 1
            replacements += changed
        else:
            skipped.append(str(source))
    return {
        "changed_files": changed_files,
        "replacements": replacements,
        "skipped": skipped,
    }


def replace_in_docx(
    source: Path, target: Path, mappings: list[tuple[str, str]]
) -> int:
    if not mappings:
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    replacement_count = 0
    with tempfile.NamedTemporaryFile(
        dir=target.parent, suffix=".docx", delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with ZipFile(source, "r") as input_archive, ZipFile(
            temporary_path, "w", compression=ZIP_DEFLATED
        ) as output_archive:
            for item in input_archive.infolist():
                data = input_archive.read(item.filename)
                if item.filename.startswith("word/") and item.filename.endswith(".xml"):
                    for old_value, new_value in mappings:
                        old = escape(old_value).encode("utf-8")
                        new = escape(new_value).encode("utf-8")
                        count = data.count(old)
                        if count:
                            data = data.replace(old, new)
                            replacement_count += count
                output_archive.writestr(item, data)
        if replacement_count:
            shutil.move(temporary_path, target)
        else:
            temporary_path.unlink(missing_ok=True)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return replacement_count
