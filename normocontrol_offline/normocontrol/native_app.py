from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from .config import DEFAULT_DB
from .db import Database
from .service import (
    add_mapping,
    import_source,
    preview_corrections,
    run_analysis,
    run_corrections,
)


ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")

ROLES = {
    "Документы": "document",
    "Стандарты": "standard",
    "Примеры": "example",
    "Схемы": "scheme",
}


class ProgressDialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.title(title)
        self.geometry("360x150")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=20, weight="bold")).pack(
            padx=24, pady=(28, 14)
        )
        self.progress = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=28)
        self.progress.start()
        ctk.CTkLabel(self, text="Операция выполняется локально").pack(pady=10)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Нормоконтроль")
        self.geometry("1080x720")
        self.minsize(900, 620)
        self.configure(fg_color="#F4F4F0")
        self.db = Database(DEFAULT_DB)
        self.results: queue.Queue = queue.Queue()
        self._build()
        self.refresh()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=32, pady=(28, 20))
        ctk.CTkLabel(
            header,
            text="Нормоконтроль",
            font=ctk.CTkFont(size=34, weight="bold"),
            text_color="#16221C",
        ).pack(side="left")
        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right")
        ctk.CTkButton(
            right,
            text="База",
            command=self.choose_database,
            width=78,
            height=34,
            corner_radius=10,
            fg_color="#E7ECE8",
            hover_color="#D8E0DA",
            text_color="#16221C",
        ).pack(side="right", padx=(12, 0))
        self.status = ctk.CTkLabel(
            right,
            text=f"База: {self.db.path.name}",
            text_color="#607168",
            width=320,
            anchor="e",
        )
        self.status.pack(side="right")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=32, pady=(0, 20))
        buttons = (
            ("Добавить материалы", self.add_materials, "#E7ECE8", "#16221C"),
            ("Проверить базу", self.analyze, "#1E5942", "#FFFFFF"),
            ("Обновить ссылку", self.map_reference, "#E7ECE8", "#16221C"),
            ("Исправленные копии", self.apply, "#E7ECE8", "#16221C"),
        )
        for text, command, color, text_color in buttons:
            ctk.CTkButton(
                actions,
                text=text,
                command=command,
                height=44,
                corner_radius=12,
                fg_color=color,
                hover_color="#D8E0DA" if color != "#1E5942" else "#174A36",
                text_color=text_color,
                font=ctk.CTkFont(size=14, weight="bold"),
            ).pack(side="left", padx=(0, 10))

        self.cards = ctk.CTkFrame(self, fg_color="transparent")
        self.cards.pack(fill="x", padx=32, pady=(0, 20))

        panel = ctk.CTkFrame(self, fg_color="#FFFFFF", corner_radius=16)
        panel.pack(fill="both", expand=True, padx=32, pady=(0, 28))
        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=22, pady=(20, 8))
        ctk.CTkLabel(
            top, text="Последние замечания", font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")
        self.findings_text = ctk.CTkTextbox(
            panel,
            corner_radius=12,
            fg_color="#F7F8F6",
            border_width=0,
            font=ctk.CTkFont(size=13),
            wrap="word",
        )
        self.findings_text.pack(fill="both", expand=True, padx=18, pady=(4, 18))

    def refresh(self) -> None:
        for child in self.cards.winfo_children():
            child.destroy()
        stats = self.db.stats()
        labels = (
            ("Документы", stats["documents"]),
            ("Ссылки", stats["references"]),
            ("Правила", stats["learned_rules"]),
            ("Замечания", stats["findings"]),
        )
        for label, value in labels:
            card = ctk.CTkFrame(self.cards, fg_color="#FFFFFF", corner_radius=14)
            card.pack(side="left", fill="x", expand=True, padx=(0, 10))
            ctk.CTkLabel(
                card,
                text=str(value),
                font=ctk.CTkFont(size=28, weight="bold"),
                text_color="#1E5942",
            ).pack(anchor="w", padx=18, pady=(14, 0))
            ctk.CTkLabel(card, text=label, text_color="#66736C").pack(
                anchor="w", padx=18, pady=(0, 14)
            )
        rows = self.db.rows(
            """
            SELECT findings.severity, documents.title, findings.message,
                   findings.original, findings.suggestion
            FROM findings JOIN documents ON documents.id = findings.document_id
            ORDER BY CASE findings.severity WHEN 'high' THEN 1
                WHEN 'medium' THEN 2 ELSE 3 END, documents.title LIMIT 120
            """
        )
        self.findings_text.configure(state="normal")
        self.findings_text.delete("1.0", "end")
        if not rows:
            self.findings_text.insert("end", "Замечаний пока нет. Нажмите «Проверить базу».")
        for row in rows:
            self.findings_text.insert(
                "end",
                f"{row['title']}\n{row['message']}\n"
                f"{row['original'] or ''}  →  {row['suggestion'] or ''}\n\n",
            )
        self.findings_text.configure(state="disabled")

    def choose_database(self) -> None:
        choice = messagebox.askyesnocancel(
            "База данных",
            "Открыть существующую базу?\n\nДа - открыть существующую\nНет - создать новую",
        )
        if choice is None:
            return
        if choice:
            path = filedialog.askopenfilename(
                title="Выберите SQLite-базу",
                filetypes=(("SQLite", "*.sqlite3 *.db"), ("Все файлы", "*.*")),
            )
        else:
            path = filedialog.asksaveasfilename(
                title="Создать SQLite-базу",
                defaultextension=".sqlite3",
                initialfile="normocontrol.sqlite3",
                filetypes=(("SQLite", "*.sqlite3"), ("Все файлы", "*.*")),
            )
        if not path:
            return
        self.db = Database(Path(path))
        self.status.configure(text=f"База: {self.db.path.name}")
        self.refresh()

    def run_task(self, title: str, task) -> None:
        dialog = ProgressDialog(self, title)

        def worker():
            try:
                self.results.put(("ok", task()))
            except Exception as exc:
                self.results.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                status, result = self.results.get_nowait()
            except queue.Empty:
                self.after(120, poll)
                return
            dialog.destroy()
            self.refresh()
            if status == "error":
                messagebox.showerror(title, result)
                self.status.configure(text="Операция завершилась ошибкой")
            else:
                self.status.configure(text=f"{title}: завершено")
                messagebox.showinfo(title, str(result))

        self.after(120, poll)

    def add_materials(self) -> None:
        paths = filedialog.askopenfilenames(title="Выберите документы, стандарты или схемы")
        if not paths:
            return
        role_name = simpledialog.askstring(
            "Тип материалов",
            "Введите тип: Документы, Стандарты, Примеры или Схемы",
            initialvalue="Стандарты",
        )
        role = ROLES.get((role_name or "").strip().capitalize())
        if not role:
            messagebox.showerror("Тип материалов", "Неизвестный тип материалов")
            return

        def task():
            total = {"imported": 0, "errors": 0}
            for path in paths:
                result = import_source(self.db, Path(path), role)
                total["imported"] += result["imported"]
                total["errors"] += result["errors"]
            return total

        self.run_task("Импорт материалов", task)

    def analyze(self) -> None:
        self.run_task("Проверка базы", lambda: {"findings": run_analysis(self.db)})

    def map_reference(self) -> None:
        old = simpledialog.askstring("Обновить ссылку", "Старое обозначение:")
        if not old:
            return
        new = simpledialog.askstring("Обновить ссылку", "Новое обозначение:")
        if not new:
            return
        add_mapping(self.db, old, new)
        self.run_task("Поиск ссылок", lambda: {"findings": run_analysis(self.db)})

    def apply(self) -> None:
        output = filedialog.askdirectory(title="Папка для исправленных копий")
        if not output:
            return
        preview = preview_corrections(self.db)
        if not preview["items"]:
            messagebox.showinfo(
                "Выпуск исправленных копий",
                "Подтвержденных замен для DOCX-документов не найдено.",
            )
            return
        document_lines = "\n".join(
            f"- {item['title']}: {item['replacement_count']} замен"
            for item in preview["items"][:10]
        )
        if len(preview["items"]) > 10:
            document_lines += f"\n- еще документов: {len(preview['items']) - 10}"
        confirmed = messagebox.askyesno(
            "Подтвердить изменения",
            "Будут созданы исправленные копии. Исходные документы не изменяются.\n\n"
            f"Документов: {preview['documents']}\n"
            f"Замен: {preview['replacements']}\n\n"
            f"{document_lines}\n\n"
            "Применить эти изменения?",
        )
        if not confirmed:
            self.status.configure(text="Изменения отменены пользователем")
            return
        self.run_task(
            "Выпуск исправленных копий",
            lambda: run_corrections(self.db, Path(output), confirmed=True),
        )


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
