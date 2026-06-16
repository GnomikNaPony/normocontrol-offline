from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "normocontrol.sqlite3"
DEFAULT_REPORTS = ROOT / "reports"

PROMPTS = [
    {
        "name": "checks_ru",
        "prompt": (
            "Ты помощник нормоконтроля. Используй только выдержки. "
            "Назови 5 автоматических проверок для ИЭ и программ. "
            "Каждая строка должна начинаться с 'Проверять'. Без рассуждений."
        ),
    },
    {
        "name": "reference_update",
        "prompt": (
            "Ты помощник нормоконтроля. Нужно обновить ссылку на замененный "
            "нормативный документ. Опиши 4 безопасных шага, чтобы не изменить "
            "исходные документы. Ответ кратко."
        ),
    },
    {
        "name": "report_requirements",
        "prompt": (
            "Ты помощник нормоконтроля. Какие данные должен содержать отчет "
            "после исправления копий документов? Назови 5 пунктов."
        ),
    },
]

REQUIRED_TERMS = {
    "checks_ru": ["провер", "оформ", "ссыл", "схем", "содерж"],
    "reference_update": ["ссыл", "коп", "подтверж", "отчет"],
    "report_requirements": ["исход", "коп", "замен", "отчет", "документ"],
}


def rows(db_path: Path, query: str, params: tuple = ()) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(query, params).fetchall()
    finally:
        connection.close()


def stats(db_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(db_path)
    try:
        return {
            "documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "errors": connection.execute(
                "SELECT COUNT(*) FROM documents WHERE status = 'error'"
            ).fetchone()[0],
            "references": connection.execute("SELECT COUNT(*) FROM refs").fetchone()[0],
            "annotations": connection.execute("SELECT COUNT(*) FROM annotations").fetchone()[0],
            "findings": connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0],
            "learned_rules": connection.execute("SELECT COUNT(*) FROM learned_rules").fetchone()[0],
        }
    finally:
        connection.close()


def role_counts(db_path: Path) -> dict[str, int]:
    return {
        row["role"]: row["count"]
        for row in rows(
            db_path,
            "SELECT role, COUNT(*) AS count FROM documents GROUP BY role ORDER BY role",
        )
    }


def finding_counts(db_path: Path) -> dict[str, int]:
    return {
        row["category"]: row["count"]
        for row in rows(
            db_path,
            "SELECT category, COUNT(*) AS count FROM findings GROUP BY category ORDER BY category",
        )
    }


def learned_rule_buckets(db_path: Path) -> dict[str, int]:
    buckets = {
        "0.00-0.25": 0,
        "0.25-0.50": 0,
        "0.50-0.75": 0,
        "0.75-1.00": 0,
    }
    for row in rows(db_path, "SELECT confidence FROM learned_rules"):
        confidence = float(row["confidence"])
        if confidence < 0.25:
            buckets["0.00-0.25"] += 1
        elif confidence < 0.50:
            buckets["0.25-0.50"] += 1
        elif confidence < 0.75:
            buckets["0.50-0.75"] += 1
        else:
            buckets["0.75-1.00"] += 1
    return buckets


def learned_rule_occurrences(db_path: Path) -> dict[str, int]:
    result = rows(
        db_path,
        """
        SELECT occurrences, COUNT(*) AS count
        FROM learned_rules
        GROUP BY occurrences
        ORDER BY occurrences
        """,
    )
    return {str(row["occurrences"]): row["count"] for row in result}


def standards_context(db_path: Path) -> str:
    parts = rows(
        db_path,
        """
        SELECT d.title, p.text
        FROM paragraphs p
        JOIN documents d ON d.id = p.document_id
        WHERE d.role = 'standard'
          AND (
            p.text LIKE '%нормоконтроль%' OR
            p.text LIKE '%оформлен%' OR
            p.text LIKE '%содержание%' OR
            p.text LIKE '%схем%' OR
            p.text LIKE '%эксплуатационн%'
          )
        LIMIT 12
        """,
    )
    chunks = [f"{row['title']}: {row['text']}" for row in parts]
    return "\n".join(chunks[:12])


def run_llm(prompt: str, context: str, timeout: int) -> tuple[str, str, float, str]:
    full_prompt = (
        f"{prompt}\n\nВыдержки из локальной базы:\n{context}\n\nОтвет:"
    )
    command = [
        "llama-completion",
        "-hf",
        "Qwen/Qwen3-0.6B-GGUF:Q8_0",
        "--jinja",
        "--reasoning",
        "off",
        "--reasoning-budget",
        "0",
        "-st",
        "--no-display-prompt",
        "--no-warmup",
        "--no-perf",
        "-ngl",
        "99",
        "-c",
        "4096",
        "-n",
        "220",
        "--temp",
        "0.1",
        "-p",
        full_prompt,
    ]
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    elapsed = time.perf_counter() - started
    raw_output = result.stdout.strip()
    output = clean_model_output(raw_output)
    return output, raw_output, elapsed, result.stderr[-2000:]


def clean_model_output(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = text.replace("[end of text]", "")
    return text.strip()


def score_output(name: str, output: str) -> dict:
    lower = output.lower()
    terms = REQUIRED_TERMS[name]
    hits = sum(1 for term in terms if term in lower)
    line_count = len([line for line in output.splitlines() if line.strip()])
    return {
        "term_hits": hits,
        "term_total": len(terms),
        "score": round(hits / max(len(terms), 1), 3),
        "line_count": line_count,
        "char_count": len(output),
    }


def write_csv(path: Path, fieldnames: list[str], records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def plot_bar(path: Path, title: str, values: dict[str, int], ylabel: str) -> None:
    plt.figure(figsize=(9, 5))
    names = list(values.keys())
    counts = list(values.values())
    plt.bar(names, counts, color="#1E5942")
    plt.title(title)
    plt.ylabel(ylabel)
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def plot_llm(path: Path, records: list[dict]) -> None:
    labels = [f"{item['prompt']} #{item['run']}" for item in records]
    scores = [float(item["score"]) for item in records]
    seconds = [float(item["seconds"]) for item in records]
    fig, axis_score = plt.subplots(figsize=(12, 5))
    axis_score.bar(labels, scores, color="#1E5942", label="score")
    axis_score.set_ylim(0, 1.05)
    axis_score.set_ylabel("Доля найденных ключевых терминов")
    axis_score.tick_params(axis="x", rotation=45)
    axis_time = axis_score.twinx()
    axis_time.plot(labels, seconds, color="#B8652B", marker="o", label="seconds")
    axis_time.set_ylabel("Время ответа, сек.")
    plt.title("Стабильность локальной LLM")
    fig.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close(fig)


def write_markdown_report(
    path: Path,
    db_stats: dict[str, int],
    roles: dict[str, int],
    findings: dict[str, int],
    rule_buckets: dict[str, int],
    rule_occurrences: dict[str, int],
    llm_records: list[dict],
) -> None:
    lines = [
        "# Отчет прогона нормоконтроля",
        "",
        f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## База",
        "",
    ]
    for key, value in db_stats.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Документы по типам", ""])
    for key, value in roles.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Замечания по категориям", ""])
    if findings:
        for key, value in findings.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- замечаний нет")
    lines.extend(["", "## Обучение правил", ""])
    lines.append("Речь идет не о fine-tuning весов LLM, а об извлечении проверяемых правил из пар документов.")
    lines.append("")
    lines.append("### Достоверность правил")
    lines.append("")
    for key, value in rule_buckets.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "### Повторяемость правил", ""])
    for key, value in rule_occurrences.items():
        lines.append(f"- {key} совпадений: {value}")
    lines.extend(["", "## Прогоны локальной LLM", ""])
    lines.append("| Prompt | Run | Score | Seconds | Lines | Chars |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for item in llm_records:
        lines.append(
            f"| {item['prompt']} | {item['run']} | {item['score']} | "
            f"{item['seconds']} | {item['line_count']} | {item['char_count']} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--reports", default=str(DEFAULT_REPORTS))
    parser.add_argument("--runs", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    reports_dir = Path(args.reports).resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)
    context = standards_context(db_path)

    llm_records: list[dict] = []
    raw_outputs: list[dict] = []
    for prompt in PROMPTS:
        for run_index in range(1, args.runs + 1):
            output, raw_output, seconds, stderr_tail = run_llm(
                prompt["prompt"], context, args.timeout
            )
            score = score_output(prompt["name"], output)
            record = {
                "prompt": prompt["name"],
                "run": run_index,
                "seconds": round(seconds, 3),
                **score,
            }
            llm_records.append(record)
            raw_outputs.append(
                {
                    **record,
                    "output": output,
                    "raw_output": raw_output,
                    "stderr_tail": stderr_tail,
                }
            )

    current_stats = stats(db_path)
    roles = role_counts(db_path)
    findings = finding_counts(db_path)
    rule_buckets = learned_rule_buckets(db_path)
    rule_occurrences = learned_rule_occurrences(db_path)

    write_csv(
        reports_dir / "llm_runs.csv",
        ["prompt", "run", "seconds", "term_hits", "term_total", "score", "line_count", "char_count"],
        llm_records,
    )
    (reports_dir / "llm_outputs.json").write_text(
        json.dumps(raw_outputs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    plot_bar(reports_dir / "documents_by_role.png", "Документы по типам", roles, "Количество")
    plot_bar(reports_dir / "findings_by_category.png", "Замечания по категориям", findings, "Количество")
    plot_bar(
        reports_dir / "learned_rules_confidence.png",
        "Обучение правил: достоверность",
        rule_buckets,
        "Количество правил",
    )
    plot_bar(
        reports_dir / "learned_rules_occurrences.png",
        "Обучение правил: повторяемость",
        rule_occurrences,
        "Количество правил",
    )
    plot_bar(
        reports_dir / "database_stats.png",
        "Метрики базы",
        {key: value for key, value in current_stats.items() if key != "documents"},
        "Количество",
    )
    plot_llm(reports_dir / "llm_runs.png", llm_records)
    write_markdown_report(
        reports_dir / "evaluation_report.md",
        current_stats,
        roles,
        findings,
        rule_buckets,
        rule_occurrences,
        llm_records,
    )
    print(
        json.dumps(
            {
                "reports": str(reports_dir),
                "stats": current_stats,
                "llm_runs": len(llm_records),
                "average_score": round(
                    sum(item["score"] for item in llm_records) / max(len(llm_records), 1),
                    3,
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
