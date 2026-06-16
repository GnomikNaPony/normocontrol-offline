from __future__ import annotations

import argparse
import json
from pathlib import Path

from .db import Database
from .service import (
    add_mapping,
    cleanup_training_data,
    import_source,
    preview_corrections,
    run_analysis,
    run_corrections,
    run_learning,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Офлайн-нормоконтроль документов")
    parser.add_argument("--db", default="data/normocontrol.sqlite3", help="Путь к SQLite")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("source")
    import_parser.add_argument(
        "--role",
        choices=["document", "standard", "example", "scheme"],
        default="document",
    )

    subparsers.add_parser("analyze")
    learn_parser = subparsers.add_parser("learn")
    learn_parser.add_argument(
        "--keep-examples",
        action="store_true",
        help="Не очищать текст примеров из базы после обучения",
    )
    subparsers.add_parser("cleanup")
    subparsers.add_parser("stats")

    mapping_parser = subparsers.add_parser("map")
    mapping_parser.add_argument("old")
    mapping_parser.add_argument("new")

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("output")
    apply_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Подтвердить применение изменений и выпуск исправленных копий",
    )

    subparsers.add_parser("preview")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=20)

    subparsers.add_parser("findings")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    db = Database(arguments.db)
    if arguments.command == "init":
        result = {"database": str(db.path)}
    elif arguments.command == "import":
        result = import_source(db, Path(arguments.source), arguments.role)
    elif arguments.command == "analyze":
        result = {"findings": run_analysis(db)}
    elif arguments.command == "learn":
        result = run_learning(db, compact_examples=not arguments.keep_examples)
    elif arguments.command == "cleanup":
        result = cleanup_training_data(db)
    elif arguments.command == "stats":
        result = db.stats()
    elif arguments.command == "map":
        add_mapping(db, arguments.old, arguments.new)
        result = {"mapping": f"{arguments.old} -> {arguments.new}"}
    elif arguments.command == "apply":
        if arguments.confirm:
            result = run_corrections(db, Path(arguments.output), confirmed=True)
        else:
            result = preview_corrections(db)
            result["not_applied"] = True
            result["message"] = "Изменения не применены. Повторите apply с --confirm."
    elif arguments.command == "preview":
        result = preview_corrections(db)
    elif arguments.command == "search":
        result = [
            dict(row)
            for row in db.rows(
                """
                SELECT documents.title, paragraph_fts.paragraph_index, paragraph_fts.text
                FROM paragraph_fts
                JOIN documents ON documents.id = paragraph_fts.document_id
                WHERE paragraph_fts MATCH ?
                LIMIT ?
                """,
                (arguments.query, arguments.limit),
            )
        ]
    elif arguments.command == "findings":
        result = [
            dict(row)
            for row in db.rows(
                """
                SELECT findings.severity, documents.title, findings.paragraph_index,
                       findings.message, findings.original, findings.suggestion
                FROM findings
                JOIN documents ON documents.id = findings.document_id
                ORDER BY CASE findings.severity
                    WHEN 'high' THEN 1 WHEN 'medium' THEN 2
                    WHEN 'review' THEN 3 ELSE 4 END,
                    documents.title, findings.paragraph_index
                """
            )
        ]
    else:
        raise RuntimeError(f"Неизвестная команда: {arguments.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
