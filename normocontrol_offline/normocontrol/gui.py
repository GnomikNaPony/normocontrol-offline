from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .config import DEFAULT_DB
from .db import Database
from .service import (
    add_mapping,
    import_source,
    preview_corrections,
    run_analysis,
    run_corrections,
    run_learning,
)


class NormControlApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Нормоконтроль Offline")
        self.root.geometry("1180x760")
        self.root.minsize(900, 600)
        self.db_path = tk.StringVar(value=str(DEFAULT_DB))
        self.status = tk.StringVar(value="Готово")
        self._build()
        self.refresh()

    def database(self) -> Database:
        return Database(self.db_path.get())

    def _build(self) -> None:
        style = ttk.Style()
        style.configure("Title.TLabel", font=("TkDefaultFont", 18, "bold"))
        style.configure("Muted.TLabel", foreground="#555555")

        header = ttk.Frame(self.root, padding=14)
        header.pack(fill="x")
        ttk.Label(header, text="Нормоконтроль Offline", style="Title.TLabel").pack(
            side="left"
        )
        ttk.Button(header, text="Выбрать базу", command=self.choose_database).pack(
            side="right"
        )

        database_bar = ttk.Frame(self.root, padding=(14, 0, 14, 10))
        database_bar.pack(fill="x")
        ttk.Label(database_bar, text="База:").pack(side="left")
        ttk.Entry(database_bar, textvariable=self.db_path).pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(database_bar, text="Обновить", command=self.refresh).pack(side="left")

        actions = ttk.Frame(self.root, padding=(14, 0, 14, 12))
        actions.pack(fill="x")
        for label, command in (
            ("Импорт документов", lambda: self.import_folder("document")),
            ("Импорт стандартов", lambda: self.import_folder("standard")),
            ("Импорт примеров до/после", lambda: self.import_folder("example")),
            ("Обучиться на примерах", self.learn),
            ("Правила обучения", self.show_rules),
            ("Проверить базу", self.analyze),
            ("Обновить ссылку", self.create_mapping),
            ("Выпустить исправленные копии", self.apply_corrections),
            ("Поиск", self.search),
        ):
            ttk.Button(actions, text=label, command=command).pack(
                side="left", padx=(0, 6), pady=3
            )

        self.summary = ttk.Label(
            self.root, text="", style="Muted.TLabel", padding=(14, 0, 14, 10)
        )
        self.summary.pack(fill="x")

        columns = ("severity", "file", "paragraph", "message", "original", "suggestion")
        frame = ttk.Frame(self.root, padding=(14, 0, 14, 8))
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=columns, show="headings")
        headings = {
            "severity": "Важность",
            "file": "Документ",
            "paragraph": "Абзац",
            "message": "Проверка",
            "original": "Найдено",
            "suggestion": "Предложение",
        }
        widths = {
            "severity": 80,
            "file": 220,
            "paragraph": 60,
            "message": 260,
            "original": 220,
            "suggestion": 220,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=50)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(self.root, textvariable=self.status, padding=(14, 6, 14, 12)).pack(
            fill="x"
        )

    def choose_database(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Создать или выбрать базу",
            defaultextension=".sqlite3",
            filetypes=[("SQLite", "*.sqlite3 *.db"), ("Все файлы", "*.*")],
        )
        if path:
            self.db_path.set(path)
            self.refresh()

    def import_folder(self, role: str) -> None:
        source = filedialog.askdirectory(title="Выберите папку с документами")
        if not source:
            return
        self._perform(
            "Импорт",
            lambda: import_source(self.database(), Path(source), role),
        )

    def learn(self) -> None:
        self._perform("Обучение", lambda: run_learning(self.database()))

    def analyze(self) -> None:
        self._perform(
            "Проверка",
            lambda: {"findings": run_analysis(self.database())},
        )

    def create_mapping(self) -> None:
        old = simpledialog.askstring(
            "Обновление ссылки", "Старая ссылка, например ГОСТ Р 2.105-2019:"
        )
        if not old:
            return
        new = simpledialog.askstring("Обновление ссылки", "Новая ссылка:")
        if not new:
            return
        try:
            add_mapping(self.database(), old, new)
            self.status.set(f"Добавлена замена: {old} -> {new}")
            self.analyze()
        except Exception as exc:
            messagebox.showerror("Ошибка", str(exc))

    def apply_corrections(self) -> None:
        output = filedialog.askdirectory(title="Папка для исправленных копий")
        if not output:
            return
        preview = preview_corrections(self.database())
        if not preview["items"]:
            messagebox.showinfo(
                "Исправление", "Подтвержденных замен для DOCX-документов не найдено."
            )
            return
        document_lines = "\n".join(
            f"- {item['title']}: {item['replacement_count']} замен"
            for item in preview["items"][:10]
        )
        if len(preview["items"]) > 10:
            document_lines += f"\n- еще документов: {len(preview['items']) - 10}"
        if not messagebox.askyesno(
            "Подтвердить изменения",
            "Будут созданы исправленные копии. Исходные документы не изменяются.\n\n"
            f"Документов: {preview['documents']}\n"
            f"Замен: {preview['replacements']}\n\n"
            f"{document_lines}\n\n"
            "Применить эти изменения?",
        ):
            self.status.set("Изменения отменены пользователем")
            return
        self._perform(
            "Исправление",
            lambda: run_corrections(self.database(), Path(output), confirmed=True),
        )

    def search(self) -> None:
        query = simpledialog.askstring("Поиск по базе", "Введите запрос:")
        if not query:
            return
        try:
            rows = self.database().rows(
                """
                SELECT documents.title, paragraph_fts.paragraph_index, paragraph_fts.text
                FROM paragraph_fts
                JOIN documents ON documents.id = paragraph_fts.document_id
                WHERE paragraph_fts MATCH ?
                LIMIT 100
                """,
                (query,),
            )
        except Exception as exc:
            messagebox.showerror("Ошибка поиска", str(exc))
            return
        window = tk.Toplevel(self.root)
        window.title(f"Поиск: {query}")
        window.geometry("900x600")
        text = tk.Text(window, wrap="word", padx=12, pady=12)
        text.pack(fill="both", expand=True)
        for row in rows:
            text.insert(
                "end",
                f"{row['title']} | абзац {row['paragraph_index']}\n{row['text']}\n\n",
            )
        text.configure(state="disabled")

    def show_rules(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Правила, извлеченные из примеров")
        window.geometry("1100x650")
        ttk.Label(
            window,
            text=(
                "Правила отключены по умолчанию. Включайте только универсальные "
                "исправления, не меняющие технический смысл."
            ),
            padding=12,
        ).pack(fill="x")
        columns = ("enabled", "confidence", "occurrences", "old", "new", "source")
        tree = ttk.Treeview(window, columns=columns, show="headings")
        labels = {
            "enabled": "Включено",
            "confidence": "Достоверность",
            "occurrences": "Примеры",
            "old": "Было",
            "new": "Стало",
            "source": "Источник",
        }
        widths = {
            "enabled": 70,
            "confidence": 90,
            "occurrences": 70,
            "old": 300,
            "new": 300,
            "source": 260,
        }
        for column in columns:
            tree.heading(column, text=labels[column])
            tree.column(column, width=widths[column], minwidth=60)
        tree.pack(fill="both", expand=True, padx=12)

        def load_rules() -> None:
            tree.delete(*tree.get_children())
            rows = self.database().rows(
                """
                SELECT id, enabled, confidence, occurrences, old_text, new_text, source
                FROM learned_rules
                ORDER BY enabled DESC, confidence DESC, occurrences DESC
                """
            )
            for row in rows:
                tree.insert(
                    "",
                    "end",
                    iid=str(row["id"]),
                    values=(
                        "да" if row["enabled"] else "нет",
                        f"{float(row['confidence']):.0%}",
                        row["occurrences"],
                        row["old_text"],
                        row["new_text"],
                        row["source"],
                    ),
                )

        def toggle_rule() -> None:
            selected = tree.selection()
            if not selected:
                return
            rule_id = int(selected[0])
            current = self.database().rows(
                "SELECT enabled FROM learned_rules WHERE id = ?", (rule_id,)
            )[0]["enabled"]
            if not current and not messagebox.askyesno(
                "Включить правило",
                "Применять это правило при последующих проверках?",
                parent=window,
            ):
                return
            self.database().execute(
                "UPDATE learned_rules SET enabled = ? WHERE id = ?",
                (0 if current else 1, rule_id),
            )
            load_rules()
            self.refresh()

        buttons = ttk.Frame(window, padding=12)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Включить / выключить выбранное", command=toggle_rule).pack(
            side="left"
        )
        ttk.Button(buttons, text="Закрыть", command=window.destroy).pack(side="right")
        tree.bind("<Double-1>", lambda _event: toggle_rule())
        load_rules()

    def _perform(self, title: str, operation) -> None:
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            result = operation()
            self.status.set(f"{title}: {result}")
            self.refresh()
        except Exception as exc:
            messagebox.showerror(f"{title}: ошибка", str(exc))
            self.status.set(f"{title}: ошибка")
        finally:
            self.root.configure(cursor="")

    def refresh(self) -> None:
        try:
            db = self.database()
            stats = db.stats()
            self.summary.configure(
                text=(
                    f"Документы: {stats['documents']}  |  ошибки импорта: {stats['errors']}  |  "
                    f"ссылки: {stats['references']}  |  разметка: {stats['annotations']}  |  "
                    f"обученные правила: {stats['learned_rules']}  |  замечания: {stats['findings']}"
                )
            )
            rows = db.rows(
                """
                SELECT findings.severity, documents.title, findings.paragraph_index,
                       findings.message, findings.original, findings.suggestion
                FROM findings
                JOIN documents ON documents.id = findings.document_id
                ORDER BY CASE findings.severity
                    WHEN 'high' THEN 1 WHEN 'medium' THEN 2
                    WHEN 'review' THEN 3 ELSE 4 END,
                    documents.title, findings.paragraph_index
                LIMIT 2000
                """
            )
            self.tree.delete(*self.tree.get_children())
            for row in rows:
                self.tree.insert(
                    "",
                    "end",
                    values=(
                        row["severity"],
                        row["title"],
                        row["paragraph_index"],
                        row["message"],
                        row["original"],
                        row["suggestion"],
                    ),
                )
        except Exception as exc:
            self.status.set(f"Не удалось открыть базу: {exc}")


def main() -> None:
    root = tk.Tk()
    NormControlApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
