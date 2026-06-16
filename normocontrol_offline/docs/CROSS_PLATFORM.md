# Кроссплатформенность

Дата проверки: 2026-06-16.

## Вывод

Ядро программы переносимое: Python, SQLite, DOCX/PDF-разбор, OCR-вызов,
CustomTkinter и CLI не привязаны к macOS. Программа может работать на macOS,
Windows и Linux, если на целевой машине установлены внешние зависимости.

Фактически проверено на текущей машине:

- macOS arm64;
- Python 3.14.6;
- Tkinter 9.0;
- SQLite 3.53.2 с FTS5;
- customtkinter 5.2.2;
- PyMuPDF 1.27.2.3;
- pypdf 6.13.2;
- matplotlib 3.11.0;
- Tesseract с языками `rus` и `eng`;
- llama.cpp CLI доступен локально.

Windows и Linux в этой сессии не запускались физически. Для них выполнен
статический аудит кода и подготовлен проверочный скрипт окружения.

## Матрица поддержки

| Компонент | macOS | Windows | Linux | Комментарий |
|---|---|---|---|---|
| Desktop-окно | Проверено | Ожидается | Ожидается | Нужны Python и Tkinter |
| CLI | Проверено | Ожидается | Ожидается | Использует стандартный Python |
| SQLite/FTS5 | Проверено | Ожидается | Ожидается | Проверяется скриптом |
| DOCX | Проверено | Ожидается | Ожидается | Чтение/замены через zip/xml |
| PDF с текстом | Проверено | Ожидается | Ожидается | Через pypdf |
| PDF/изображения OCR | Проверено | Ожидается | Ожидается | Нужен Tesseract + `rus`/`eng` |
| Старый DOC | Частично | Требует LibreOffice | Требует LibreOffice | `textutil` на macOS ненадежен |
| Локальная LLM | Проверено как запуск | Ожидается | Ожидается | Нужен llama.cpp и GGUF-модель |
| Графики отчетов | Проверено | Ожидается | Ожидается | Через matplotlib |

## Проверка целевой машины

После установки зависимостей выполните:

```bash
cd normocontrol_offline
python scripts/check_environment.py
```

Если используется виртуальное окружение:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/check_environment.py
```

Windows:

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python scripts\check_environment.py
```

Скрипт проверяет:

- версию Python;
- Tkinter;
- SQLite FTS5;
- Python-зависимости;
- наличие Tesseract и языков `rus`, `eng`;
- LibreOffice или частичный macOS fallback `textutil`;
- наличие `llama-server`/`llama-completion`.

## Условия для Windows

Рекомендуемая версия: Windows 10/11 x64.

Нужно установить:

- Python 3.11-3.13, при установке включить `Add Python to PATH`;
- Tesseract OCR и русский языковой пакет;
- LibreOffice, если нужны старые `.doc`;
- llama.cpp и GGUF-модель, если нужна локальная LLM.

Риски:

- Tesseract и LibreOffice часто не добавляются в PATH автоматически;
- старые `.doc` без LibreOffice импортироваться не будут;
- кириллические пути должны работать, но для первых тестов лучше использовать
  короткий путь без спецсимволов, например `C:\NormControl`.

## Условия для Linux

Рекомендуемая база: Ubuntu/Debian.

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip tesseract-ocr tesseract-ocr-rus libreoffice
```

Если Tkinter отсутствует:

```bash
sudo apt install python3-tk
```

Риски:

- на минимальных серверных сборках нет GUI/Tkinter;
- для OCR нужны языковые пакеты Tesseract;
- для старых `.doc` нужен LibreOffice headless.

## Условия для macOS

Проверенная машина уже проходит базовую проверку. Для надежного `.doc` импорта
лучше дополнительно установить LibreOffice:

```bash
brew install --cask libreoffice
```

Сейчас macOS fallback `textutil` доступен, но он не гарантирует корректный
импорт всех старых `.doc`. Один из документов в текущем наборе уже требует
LibreOffice или пересохранения в `.docx`.

## Что не является полностью готовым

- Автономная сборка `.exe`/`.app`/AppImage пока не сделана.
- Windows и Linux не прогонялись на реальных машинах в этой сессии.
- Локальная Qwen3-0.6B запускается, но по качеству не подходит как основной
  нормоконтролер.
- Для промышленного режима нужно добавить CI на Windows, macOS и Linux.

## Рекомендованный следующий шаг

Создать автоматическую сборку и проверку:

- GitHub Actions: `windows-latest`, `macos-latest`, `ubuntu-latest`;
- запуск `python scripts/check_environment.py` без OCR-части;
- запуск `python -m unittest discover -s tests -v`;
- сборка portable-пакетов через PyInstaller или Briefcase.
