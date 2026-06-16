from __future__ import annotations

from datetime import datetime
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


def preview_reference_mappings(db: Database) -> dict:
    mappings = _reference_mappings(db)
    documents = db.rows(
        """
        SELECT id, title, path FROM documents
        WHERE status = 'ready' AND extension = '.docx' AND role = 'document'
        ORDER BY title
        """
    )
    items: list[dict] = []
    total_replacements = 0
    for document in documents:
        source = Path(document["path"])
        replacements = count_docx_replacements(source, sorted(mappings))
        if not replacements:
            continue
        total = sum(item["count"] for item in replacements)
        total_replacements += total
        items.append(
            {
                "document_id": int(document["id"]),
                "title": document["title"],
                "source": str(source),
                "replacements": replacements,
                "replacement_count": total,
            }
        )
    return {
        "documents": len(items),
        "replacements": total_replacements,
        "items": items,
    }


def apply_reference_mappings(
    db: Database, output_directory: Path, confirmed: bool = False
) -> dict[str, int | list[str]]:
    if not confirmed:
        raise PermissionError("Применение изменений требует подтверждения пользователя")
    output_directory.mkdir(parents=True, exist_ok=True)
    mappings = _reference_mappings(db)
    documents = db.rows(
        """
        SELECT id, title, path FROM documents
        WHERE status = 'ready' AND extension = '.docx' AND role = 'document'
        ORDER BY title
        """
    )
    changed_files = 0
    replacements = 0
    skipped: list[str] = []
    report_items: list[dict] = []
    for document in documents:
        source = Path(document["path"])
        target = output_directory / source.parent.name / source.name
        details = replace_in_docx_detailed(source, target, sorted(mappings))
        changed = sum(item["count"] for item in details)
        if details:
            changed_files += 1
            replacements += changed
            report_items.append(
                {
                    "document_id": int(document["id"]),
                    "title": document["title"],
                    "source": str(source),
                    "target": str(target),
                    "replacements": details,
                    "replacement_count": changed,
                }
            )
        else:
            skipped.append(str(source))
    report_path = write_corrections_report(output_directory, report_items, skipped)
    return {
        "changed_files": changed_files,
        "replacements": replacements,
        "skipped": skipped,
        "report": str(report_path),
    }


def replace_in_docx(
    source: Path, target: Path, mappings: list[tuple[str, str]]
) -> int:
    details = replace_in_docx_detailed(source, target, mappings)
    return sum(item["count"] for item in details)


def replace_in_docx_detailed(
    source: Path, target: Path, mappings: list[tuple[str, str]]
) -> list[dict]:
    if not mappings:
        return []
    target.parent.mkdir(parents=True, exist_ok=True)
    replacement_counts: dict[tuple[str, str], int] = {}
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
                            key = (old_value, new_value)
                            replacement_counts[key] = replacement_counts.get(key, 0) + count
                output_archive.writestr(item, data)
        if replacement_counts:
            shutil.move(temporary_path, target)
        else:
            temporary_path.unlink(missing_ok=True)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return [
        {"old": old, "new": new, "count": count}
        for (old, new), count in sorted(replacement_counts.items())
    ]


def count_docx_replacements(
    source: Path, mappings: list[tuple[str, str]]
) -> list[dict]:
    if not mappings:
        return []
    replacement_counts: dict[tuple[str, str], int] = {}
    with ZipFile(source, "r") as archive:
        for item in archive.infolist():
            if not (item.filename.startswith("word/") and item.filename.endswith(".xml")):
                continue
            data = archive.read(item.filename)
            for old_value, new_value in mappings:
                count = data.count(escape(old_value).encode("utf-8"))
                if count:
                    key = (old_value, new_value)
                    replacement_counts[key] = replacement_counts.get(key, 0) + count
    return [
        {"old": old, "new": new, "count": count}
        for (old, new), count in sorted(replacement_counts.items())
    ]


def write_corrections_report(
    output_directory: Path, items: list[dict], skipped: list[str]
) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_path = output_directory / f"report_{timestamp}.md"
    lines = [
        "# Отчет нормоконтроля",
        "",
        f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Итог",
        "",
        f"- Изменено документов: {len(items)}",
        f"- Выполнено замен: {sum(item['replacement_count'] for item in items)}",
        f"- Пропущено без изменений: {len(skipped)}",
        "",
        "## Измененные документы",
        "",
    ]
    if not items:
        lines.append("Изменений не найдено.")
        lines.append("")
    for item in items:
        source = Path(item["source"]).resolve()
        target = Path(item["target"]).resolve()
        lines.extend(
            [
                f"### {item['title']}",
                "",
                f"- Исходный документ: {_markdown_file_link(source)}",
                f"- Исправленная копия: {_markdown_file_link(target)}",
                f"- Всего замен: {item['replacement_count']}",
                "",
                "| Старое значение | Новое значение | Количество |",
                "|---|---|---:|",
            ]
        )
        for replacement in item["replacements"]:
            lines.append(
                "| "
                f"{_table_text(replacement['old'])} | "
                f"{_table_text(replacement['new'])} | "
                f"{replacement['count']} |"
            )
        lines.append("")
    if skipped:
        lines.extend(["## Документы без примененных замен", ""])
        for path in skipped:
            lines.append(f"- {_markdown_file_link(Path(path).resolve())}")
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _reference_mappings(db: Database) -> set[tuple[str, str]]:
    return {
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


def _markdown_file_link(path: Path) -> str:
    return f"[{path.name}](<{path.as_uri()}>)"


def _table_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
